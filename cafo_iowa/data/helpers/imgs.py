import glob
import json
import logging
import os
import os.path
import re
import warnings
from functools import partial
from glob import glob
from multiprocessing import Pool

import click
import geopandas as gpd
import numpy as np
import rasterio
import tqdm
from PIL import Image, ImageDraw, ImageFont
from rasterio.mask import mask
from shapely.geometry import MultiPolygon, Point, Polygon
from tqdm import tqdm

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s
from cafo_iowa.data.helpers.gcs import download_single_img


def convert_tifs_to_jpegs(input_path, band_mode="RGB", rerun=False):
    """
    Convert TIFF files to JPEG format.

    Args:
        input_path (str): The path to the directory containing the TIFF files.
        band_mode (str, optional): The band mode to convert the image to (default is "RGB").
        rerun (bool, optional): Whether to rerun the conversion for existing JPEG files (default is False).

    Returns:
        None
    """
    logging.info(f"Converting TIFF files in {input_path} to JPEG format.")

    # get list of all tiled tif files
    tiled_tifs = glob.glob(input_path + "/*.tif")

    # set output path to same path as input path, except with "jpeg" instead of "tif"
    output_path = input_path.replace("tifs", "jpegs")

    # check if image folder exists yet
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    existing_jpegs = glob.glob(output_path + "/*.jpeg")

    if rerun:
        remaining_tifs = tiled_tifs
    else:
        remaining_tifs = [
            t
            for t in tiled_tifs
            if os.path.basename(t).replace(".tif", ".jpeg") not in existing_jpegs
        ]

    if len(remaining_tifs) == 0:
        logging.info("No TIFF files to convert to JPEGs.")
        return

    # Iterate through the TIFF files
    for t in tqdm(remaining_tifs, desc="Converting TIFFs to JPEGs"):
        tile_name = os.path.basename(t).split("/")[-1].replace(".tif", ".jpeg")
        tile_path = os.path.join(output_path, tile_name)

        if os.path.exists(tile_path) and not rerun:
            continue

        else:
            # Open the TIFF file
            with Image.open(t) as img:
                # Convert the image to band mode (RGB, GBA, etc.)
                if img.mode != band_mode:
                    img = img.convert(band_mode)
                # Save the image as a JPEG file
                img.save(tile_path, "JPEG")

    logging.info(f"Finished converting tifs to jpegs. Stored files in {output_path}.")


def mask_urban_single(fp, gdf, out_path=None):
    """
    Masks out urban areas in a single tile based on a geodataframe.

    Args:
        fp (str): The file path of the tile to be masked.
        gdf (geopandas.GeoDataFrame): The geodataframe containing the tile information.
        out_path (str, optional): The output file path for the masked tile. If not provided, the input file path will be used.

    Raises:
        ValueError: If an error occurs while masking the urban areas.

    Returns:
        None
    """
    if out_path is None:
        out_path = fp

    geo = gdf.dissolve()

    try:
        with rasterio.open(fp, "r") as src:
            # Make sure the crs is the same
            geo = geo.to_crs(src.crs)

            # Suppress specific rasterio warning
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="shapes are outside bounds of raster. Are they in different coordinate reference systems?",
                )
                # Mask out urban areas
                out_img, out_transform = mask(src, shapes=geo.geometry, invert=True)

            out_meta = src.meta.copy()
            out_meta.update(
                {
                    "height": out_img.shape[1],
                    "width": out_img.shape[2],
                    "transform": out_transform,
                }
            )

            # save masked image
            with rasterio.open(out_path, "w", **out_meta) as dest:
                dest.write(out_img)

            # return file name
            return out_path.split("/")[-1]

    except Exception as e:
        raise ValueError(f"ERROR: Could not mask urban areas in {fp}: {str(e)}")


def mask_urban_areas(
    in_path: str,
    out_path: str = None,
    session=None,
    n_cpu: int = 8,
    file_glob: str = "*.tif",
    regenerate: bool = False,
):
    """
    Masks out urban areas in GeoTIFF files using urban area boundaries from the database.

    This function:
    1. Loads urban area boundaries from the database
    2. Processes each GeoTIFF file in parallel using multiple CPUs
    3. Masks out areas that intersect with urban boundaries
    4. Saves the masked files to the output directory
    5. Maintains a cache of processed files to avoid reprocessing

    Args:
        in_path (str): Path to the directory containing input GeoTIFF files
        out_path (str, optional): Path to save masked files. If None, uses in_path
        session: Database session object. If None, a new session will be created
        n_cpu (int, optional): Number of CPUs to use for parallel processing. Defaults to 8
        file_glob (str, optional): File pattern to match. Defaults to "*.tif"
        regenerate (bool, optional): Whether to regenerate all files. Defaults to False

    Returns:
        None
    """
    if out_path is None:
        out_path = in_path

    if session is None:
        session = s.get_session()

    engine = session.get_bind()

    # Create output folder if it doesn't exist
    if not os.path.exists(out_path):
        os.makedirs(out_path)

    # Create or load the cache file
    cache_file = os.path.join(out_path, "masked_files_cache.json")
    if os.path.exists(cache_file) and not regenerate:
        with open(cache_file, "r") as f:
            processed_files = set(json.load(f))
    else:
        processed_files = set()

    logging.info(f"Masking urban areas in {in_path} and saving to {out_path}")

    # Get candidate files for processing
    candidate_fns = glob(os.path.join(in_path, file_glob))

    if regenerate:
        logging.info(f"Re-masking all tiles in {out_path}")
        processed_files.clear()

    # Remove processed files from candidate files
    candidate_fns = [
        fn for fn in candidate_fns if os.path.basename(fn) not in processed_files
    ]

    if len(candidate_fns) == 0:
        logging.info("All tiles have been masked")
        return

    gdf = gpd.read_postgis(
        "SELECT * from processed.urban_areas", engine, geom_col="geometry"
    )

    with Pool(n_cpu) as p:
        func = partial(
            mask_urban_single,
            gdf=gdf,
        )

        # Process the images
        results = list(
            tqdm.tqdm(
                p.imap_unordered(
                    func,
                    candidate_fns,
                ),
                total=len(candidate_fns),
            ),
        )

        # Update the processed files cache
        for fn in results:
            processed_files.add(os.path.basename(fn))

        # Save the updated cache
        with open(cache_file, "w") as f:
            json.dump(list(processed_files), f)

        logging.info("Masking complete")


def crop_single(
    fp: str,
    gdf: gpd.GeoDataFrame,
    out_path: str,
) -> None:
    """Crops a single GeoTIFF according to shape file bounds, optionally masks urban areas, and saves to out_path.

    Args:
        fp: file path of GeoTIFF to crop.
        gdf: GeoDataFrame containing shape file bounds of all tiles.
        out_path: folder to store cropped image.
    """

    # Create directory if it does not exist
    if not os.path.exists(out_path):
        os.makedirs(out_path)

    # Get the file name of the file
    fn = os.path.basename(fp)

    # Select the polygon from the shape file that matches the filenames in the file path
    geo = gdf[gdf["tile_id"] == fn.replace(".tif", "")]

    # If there are more than one polygon, error out
    if len(geo) != 1:
        print(f"There are {len(geo)} polygons for {fn}. There should be 1.")

    # Open the file using rasterio
    try:
        with rasterio.open(fp, "r") as src:
            # Make sure the CRS matches
            geo = geo.to_crs(src.crs)

            # Crop the image according to polygon bounds
            poly = geo.geometry.values[0]
            out_img, out_transform = mask(src, shapes=[poly], crop=True)

            # Prepare metadata for saving
            out_meta = src.meta.copy()
            out_meta.update(
                {
                    "driver": "GTiff",
                    "height": out_img.shape[1],
                    "width": out_img.shape[2],
                    "transform": out_transform,
                }
            )

            # Save the cropped and potentially urban-masked image to the output path
            with rasterio.open(os.path.join(out_path, fn), "w", **out_meta) as dest:
                dest.write(out_img)

    except Exception as e:
        print(f"Could not crop {fn}: {str(e)}")


def quarter_single(
    fp: str,
    gdf: gpd.GeoDataFrame,
    out_path: str,
) -> None:
    """Quarters a single GeoTIFF according to shape file bounds and optionally removes urban areas.
       Returns 4 tiles, using the same file name as the input file.

    Args:
        fp: file path of GeoTIFF to quarter.
        gdf: GeoDataFrame containing shape file bounds of tiles.
        out_path: folder to store quartered images.
    """

    # Create directory if it does not exist
    if not os.path.exists(out_path):
        os.makedirs(out_path)

    # Get the file name of the file
    fn = os.path.basename(fp)

    # Select all tiles from the gdf that match the filenames in the file path
    geos = gdf[gdf.tile_id == fn.replace(r".tif", "")]

    # If the length of the geos is not 4, print the filename and the length
    if len(geos) != 4:
        print(f"There are {len(geos)} polygons for {fn}. There should be 4.")

    # Open the file using rasterio
    try:
        with rasterio.open(fp, "r") as src:
            # Make sure the crs is the same
            geos = geos.to_crs(src.crs)

            # For each row in the geos, crop the image and save it to the out_path
            for _, row in geos.iterrows():
                poly = row.geometry
                out_img, out_transform = mask(src, shapes=[poly], crop=True)
                out_meta = src.meta.copy()
                out_meta.update(
                    {
                        "height": out_img.shape[1],
                        "width": out_img.shape[2],
                        "transform": out_transform,
                    }
                )

                with rasterio.open(
                    os.path.join(out_path, row.qt_tile_id + ".tif"), "w", **out_meta
                ) as dest:
                    dest.write(out_img)

    except Exception as e:
        raise ValueError(f"ERROR: Could not quarter {fn}: {str(e)}")


def crop_naip(
    in_path: str,
    out_path: str,
    quarter: bool = False,
    buffer: bool = False,
    file_glob: str = "*.tif",
    n_cpu: int = 8,
    session=None,
    regenerate: bool = False,
):
    """
    Crops and optionally quarters NAIP GeoTIFF files based on their boundaries in the database.

    This function:
    1. Loads tile boundaries from the database
    2. Processes each GeoTIFF file in parallel using multiple CPUs
    3. Crops files to their exact boundaries
    4. Optionally quarters files into smaller sections
    5. Optionally applies buffers to quartered tiles
    6. Maintains a cache of processed files to avoid reprocessing

    Args:
        in_path (str): Path to the directory containing input GeoTIFF files
        out_path (str): Path to save processed files
        quarter (bool, optional): Whether to quarter the tiles. Defaults to False
        buffer (bool, optional): Whether to apply buffers to quartered tiles. Defaults to False
        file_glob (str, optional): File pattern to match. Defaults to "*.tif"
        n_cpu (int, optional): Number of CPUs to use for parallel processing. Defaults to 8
        session: Database session object. If None, a new session will be created
        regenerate (bool, optional): Whether to regenerate all files. Defaults to False

    Raises:
        ValueError: If buffer is True but quarter is False

    Returns:
        None
    """
    if buffer and not quarter:
        raise ValueError("Buffering only works with quartered tiles")

    # Create output folder if it doesn't exist
    if not os.path.exists(out_path):
        os.makedirs(out_path)

    # Get candidate files for processing
    candidate_fns = glob(os.path.join(in_path, file_glob))

    if regenerate:
        logging.info(f"Regenerating all tiles in {out_path}")
        existing_fns = []
    else:
        existing_fns = [
            os.path.basename(fn) for fn in glob(os.path.join(out_path, file_glob))
        ]

    # Remove existing files from candidate files
    if quarter:
        existing_fns = [re.sub(r"(.{3})\.tif$", ".tif", fn) for fn in existing_fns]

    candidate_fns = [
        fn for fn in candidate_fns if os.path.basename(fn) not in existing_fns
    ]

    # get naip shp data
    if session is None:
        session = s.get_session()

    engine = session.get_bind()

    # Get the shape file data
    if quarter and buffer:
        gdf = gpd.read_postgis(
            f"SELECT * FROM processed.{m.Naip21QT.__tablename__}",
            engine,
            geom_col="geometry_buffer",
        )
    elif quarter and not buffer:
        gdf = gpd.read_postgis(
            f"SELECT * FROM processed.{m.Naip21QT.__tablename__}",
            engine,
            geom_col="geometry",
        )
    else:
        gdf = gpd.read_postgis(
            f"SELECT * FROM processed.{m.Naip21.__tablename__}",
            engine,
            geom_col="geometry",
        )

    with Pool(n_cpu) as p:
        if quarter:
            logging.info(f"Quartering tiles from {in_path} and saving to {out_path}")
            func = partial(
                quarter_single,
                gdf=gdf,
                out_path=out_path,
            )
        else:
            logging.info(f"Cropping tiles from {in_path} and saving to {out_path}")

            func = partial(
                crop_single,
                gdf=gdf,
                out_path=out_path,
            )

        # Process the images
        _ = list(
            tqdm.tqdm(
                p.imap_unordered(
                    func,
                    candidate_fns,
                ),
                total=len(candidate_fns),
            )
        )

        if quarter:
            logging.info("Quartering complete")
        else:
            logging.info("Cropping complete")


@click.command()
@click.argument("in_path")
@click.argument("out_path")
@click.option(
    "-q",
    "--quarter",
    is_flag=True,
    default=False,
    show_default=True,
    help="If True, then GeoTiffs are split into quarters and saved using qt_tile_id file name",
)
@click.option(
    "-b",
    "--buffer",
    is_flag=True,
    default=False,
    show_default=True,
    help="If True, then GeoTiffs are split into quarters (including buffer) and saved using qt_tile_id file name",
)
@click.option(
    "-f",
    "--file_glob",
    type=str,
    default="*.tif",
    show_default=True,
    help="Regex for file filter",
)
@click.option(
    "-n",
    "--n_cpu",
    type=int,
    default=8,
    show_default=True,
    help="Number of CPUs for multiprocessing",
)
@click.option(
    "-sess",
    "--session",
    default=None,
    help="Database session",
)
@click.option(
    "-regen",
    "--regenerate",
    is_flag=True,
    default=False,
    show_default=True,
    help="Regenerate all tiles, even if they already exist in the out_path",
)
def crop_naip_cli(
    in_path,
    out_path,
    quarter,
    buffer,
    file_glob,
    n_cpu,
    session,
    regenerate,
):
    crop_naip(
        in_path,
        out_path,
        quarter,
        buffer,
        file_glob,
        n_cpu,
        session,
        regenerate,
    )


if __name__ == "__main__":
    crop_naip_cli()


def create_annotated_tile_image(
    tile_id: str,
    session=None,
    output_path: str = None,
    highlight_permit_ids: list = None,
) -> str:
    """
    Creates an annotated image of a tile with permits as points and barns as polygons.
    Permits and their associated parcel boundaries will be highlighted in yellow if their IDs
    are in highlight_permit_ids.

    This function:
    1. Downloads the tile image from Google Cloud Storage
    2. Retrieves permits, barns, and parcels from the database
    3. Draws annotations on the image:
       - Permits as points with animal unit counts
       - Barns as polygons
       - Parcel boundaries
       - Highlighted permits and their parcels in yellow
    4. Saves the annotated image

    Args:
        tile_id (str): The ID of the tile to annotate
        session: Database session. If None, a new session will be created
        output_path (str, optional): Path to save the annotated image. If None, will use the tile_id as filename
        highlight_permit_ids (list, optional): List of permit IDs to highlight in a different color

    Returns:
        str: Path to the saved annotated image
    """
    # Get database session if not provided
    if session is None:
        from cafo_iowa.db import session as s

        session = s.get_session()

    img_path = download_single_img(tile_id)

    # First read with rasterio to get the georeferencing
    with rasterio.open(img_path) as src:
        transform = src.transform
        crs = src.crs

    # Read and convert the image using PIL
    with Image.open(img_path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Get image dimensions
        width, height = img.size

        # Create a copy for drawing annotations
        annotated_img = img.copy()
        draw = ImageDraw.Draw(annotated_img)

    # Get the tile bounds from the database
    engine = session.get_bind()
    tile_gdf = gpd.read_postgis(
        f"""
        SELECT geometry_buffer
        FROM processed.naip21_qt
        WHERE id = '{tile_id}'
        """,
        engine,
        geom_col="geometry_buffer",
    )

    if tile_gdf.empty:
        raise ValueError(f"No tile found with ID {tile_id}")

    # Get permits for this tile
    permits = gpd.read_postgis(
        f"""
        SELECT
            facilityid,
            animal_units,
            ST_Transform(geometry, {crs.to_epsg()}) as geometry
        FROM processed.permits p
        WHERE naip_qt_id = '{tile_id}'
        """,
        engine,
        geom_col="geometry",
    )

    # Get barns in the tile
    barns = gpd.read_postgis(
        f"""
        SELECT
            b.id,
            b.facility_id,
            b.barn_cluster_id,
            ST_Transform(b.geometry, {crs.to_epsg()}) as geometry
        FROM processed.barns b
        WHERE ST_Intersects(
            b.geometry,
            (SELECT geometry FROM processed.naip21_qt WHERE id = '{tile_id}')
        )
        AND b.geometry is not null
        """,
        engine,
        geom_col="geometry",
    )

    # Get parcels for this tile and their associated permits using permit_parcels table
    parcels = gpd.read_postgis(
        f"""
        WITH highlighted_permits AS (
            SELECT id
            FROM processed.permits
            WHERE facilityid = ANY(ARRAY{highlight_permit_ids if highlight_permit_ids else []}::integer[])
        )
        SELECT
            p.id as parcel_id,
            ST_Transform(p.geometry, {crs.to_epsg()}) as geometry,
            EXISTS (
                SELECT 1 FROM highlighted_permits hp
                JOIN processed.permit_parcels pp ON pp.permit_id = hp.id
                WHERE pp.parcel_id = p.id
            ) as is_highlighted
        FROM processed.parcels p
        WHERE ST_Intersects(
            p.geometry,
            (SELECT geometry FROM processed.naip21_qt WHERE id = '{tile_id}')
        )
        """,
        engine,
        geom_col="geometry",
    )

    # Calculate annotation sizes based on image dimensions
    marker_size = max(15, int(width * 0.005))
    line_width = max(2, int(width * 0.0005))
    parcel_line_width = max(3, int(width * 0.0007))

    # Function to convert geographic coordinates to pixel coordinates
    def geo_to_pixel(lon, lat):
        # Calculate pixel coordinates based on the transform
        x = (lon - transform[2]) / transform[0]
        y = (lat - transform[5]) / transform[4]
        return (int(x), int(y))

    # Draw parcel boundaries
    if not parcels.empty:
        for _, parcel in parcels.iterrows():
            # Get the polygon coordinates
            polygon = parcel.geometry
            if isinstance(polygon, (Polygon, MultiPolygon)):
                # Handle both single polygons and multipolygons
                if isinstance(polygon, MultiPolygon):
                    polygons = list(polygon.geoms)
                else:
                    polygons = [polygon]

                for poly in polygons:
                    # Convert polygon coordinates to pixel coordinates
                    pixel_coords = [geo_to_pixel(x, y) for x, y in poly.exterior.coords]
                    # Draw the polygon outline with color based on highlight status
                    fill_color = (
                        (255, 255, 0) if parcel.is_highlighted else (255, 20, 147)
                    )  # Yellow if highlighted, else Bright Pink
                    draw.line(pixel_coords, fill=fill_color, width=parcel_line_width)

    # Draw barns (filled blue with some transparency)
    if not barns.empty:
        for _, barn in barns.iterrows():
            # Get the polygon coordinates
            polygon = barn.geometry
            if isinstance(polygon, (Polygon, MultiPolygon)):
                # Handle both single polygons and multipolygons
                if isinstance(polygon, MultiPolygon):
                    polygons = list(polygon.geoms)
                else:
                    polygons = [polygon]

                for poly in polygons:
                    # Convert polygon coordinates to pixel coordinates
                    pixel_coords = [geo_to_pixel(x, y) for x, y in poly.exterior.coords]

                    # Draw filled polygon with transparency
                    draw.polygon(
                        pixel_coords, fill=(0, 0, 255, 96)
                    )  # Blue with alpha=96
                    # Draw the polygon outline
                    draw.line(pixel_coords, fill=(0, 0, 255), width=line_width)

    # Draw permit points (red or yellow stars depending on highlight status)
    if not permits.empty:
        for _, permit in permits.iterrows():
            # Get the point coordinates
            point = permit.geometry
            if isinstance(point, Point):
                x, y = geo_to_pixel(point.x, point.y)

                # Draw a star shape
                star_points = []
                for i in range(5):
                    # Outer point
                    angle = i * 2 * np.pi / 5 - np.pi / 2
                    star_points.append(
                        (
                            x + marker_size * np.cos(angle),
                            y + marker_size * np.sin(angle),
                        )
                    )
                    # Inner point
                    angle += np.pi / 5
                    star_points.append(
                        (
                            x + marker_size * 0.4 * np.cos(angle),
                            y + marker_size * 0.4 * np.sin(angle),
                        )
                    )

                # Choose color based on whether permit should be highlighted
                if highlight_permit_ids and permit.facilityid in highlight_permit_ids:
                    fill_color = (255, 255, 0)  # Yellow for highlighted permits
                else:
                    fill_color = (255, 0, 0)  # Red for regular permits

                # Draw the star
                draw.polygon(star_points, fill=fill_color)

    # Save the annotated image
    if output_path is None:
        output_path = f"{tile_id}.jpeg"

    # Save with high quality settings
    annotated_img.save(output_path, format="jpeg", optimize=False, quality=100)

    return output_path


def prepare_tiles_for_relabeling(
    tile_ids, output_dir, session=None, highlight_permit_ids=None
):
    """
    Prepare tiles for relabeling by creating annotated versions with barns, facilities, and other geometries.

    This function:
    1. Creates an output directory if it doesn't exist
    2. For each tile ID:
       - Creates an annotated version using create_annotated_tile_image
       - Includes permits, barns, and parcel boundaries
       - Highlights specified permits and their parcels
    3. Returns paths to all created annotated images

    Args:
        tile_ids (list): List of tile IDs that need relabeling
        output_dir (str): Directory to store annotated images
        session: Database session. If None, a new session will be created
        highlight_permit_ids (list, optional): List of permit IDs to highlight in a different color

    Returns:
        list: Paths to the created annotated images
    """
    import os

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Get database session if not provided
    if session is None:

        session = s.get_session()

    annotated_paths = []
    for tile_id in tile_ids:
        # Create output path for this tile
        output_path = os.path.join(output_dir, f"{tile_id}.jpeg")

        # Use existing function to create annotated image
        annotated_path = create_annotated_tile_image(
            tile_id=tile_id,
            session=session,
            output_path=output_path,
            highlight_permit_ids=highlight_permit_ids,
        )

        annotated_paths.append(annotated_path)

    return annotated_paths
