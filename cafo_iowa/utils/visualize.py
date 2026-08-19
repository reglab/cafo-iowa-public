import json
import os

import contextily as ctx
import folium
import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import sqlalchemy
import yaml
from matplotlib.patches import Patch
from rasterio.merge import merge as rasterio_merge
from rasterio.plot import show
from rasterio.windows import from_bounds as window_from_bounds
from rasterio.windows import transform as window_transform
from shapely import wkt
from shapely.geometry import box
from shapely.ops import unary_union  # NEW

import cafo_iowa.data.helpers.gcs as gcs
import cafo_iowa.db.models as m
import cafo_iowa.db.session as s


def plot_tiles_and_annotations(
    tile_id,
    display_image=False,
    session=None,
    config_filepath="cafo_iowa/data/cfg/config.yaml",
    save_to_file=False,
):
    """
    Plot the image, tile boundary, and annotations for a given tile ID.

    Args:
        tile_id (str): The ID of the tile to plot.
        display_image (bool, optional): Whether to display the image. Defaults to False.
        session (object, optional): The database session. Defaults to None.
        config_filepath (str, optional): The filepath of the configuration file. Defaults to "cafo_iowa/data/cfg/config.yaml".
        save_to_file (bool, optional): Whether to save the plot to a file. Defaults to False.
    """

    if session is None:
        session = s.get_session()

    engine = session.bind

    # if tile_id ends in "BL", "BR", "TL", or "TR", then it is a quartered buffer tile
    if any(suffix in tile_id for suffix in ["BL", "BR", "TL", "TR"]):
        subset = f"qt_tile_id = '{tile_id}'"
        tile_type = "quartered_buffer"
    else:
        subset = f"tile_id = '{tile_id}'"
        tile_type = "cropped"

    naip = gpd.read_postgis(
        f"SELECT * from processed.naip21 WHERE {subset}",
        engine,
        geom_col="geometry",
    )
    annotations = gpd.read_postgis(
        f"SELECT * from processed.cf_annotations WHERE {subset}",
        engine,
        geom_col="geometry",
    )

    if annotations.empty:
        print(f"Tile {tile_id} has not been annotated.")

    elif (annotations.qt_tile_id.unique().shape[0] != 4) and (tile_type == "cropped"):
        print(
            f"Note: Only {annotations.qt_tile_id.unique().shape[0]} of 4 quartered tiles in this tile have been annotated."
        )

    # remove rows with missing geometry
    annotations = annotations[~annotations["geometry"].isnull()]

    if display_image:
        with open(config_filepath, "r") as f:
            config = yaml.safe_load(f)

        img_path = gcs.download_single_img(tile_id, config_filepath=config_filepath)

        # Load the image
        image = rasterio.open(img_path)

    # Plot image
    fig, ax = plt.subplots(figsize=(10, 10))
    show(image, ax=ax) if display_image else None

    # Plot tile boundary
    naip.boundary.plot(ax=ax, edgecolor="red")

    # Plot annotations with different colors based on the label
    labels = annotations["label"].unique()
    colors = plt.get_cmap("Set3", len(labels))
    label_color_map = {label: colors(i) for i, label in enumerate(labels)}

    for label in labels:
        subset = annotations[annotations["label"] == label]
        subset.boundary.plot(ax=ax, edgecolor=label_color_map[label], label=label)

    # Remove axis legend
    ax.axis("off")

    plt.title(f"Image, Tile, and Annotations for {tile_id}")
    plt.legend()
    if save_to_file:
        if not os.path.exists("output/plots"):
            os.makedirs("output/plots")
        plt.savefig(f"output/plots/{tile_id}_annotations.png", dpi=300)
    plt.show()
    plt.close()


# # Example usage:
# plot_tiles_and_annotations(
#     "m_4309656_se_14_060_20210821_TL", display_image=True, save_to_file=True
# )


# Define custom basemap as a function
def add_google_satellite(map_object):
    google_sat_map = folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite",
        overlay=True,
        control=True,
    )
    google_sat_map.add_to(map_object)
    return map_object


# Define style functions with lower opacity
def get_style_function(color, opacity=0.5, weight=2):
    return lambda x: {
        "color": color,
        "opacity": opacity,
        "weight": weight,
    }


# Define a list of available styles with adjusted opacity
available_styles = [
    get_style_function("red", opacity=0.5, weight=5),
    get_style_function("yellow", opacity=0.5, weight=4),
    get_style_function("green", opacity=0.5, weight=3),
    get_style_function("pink", opacity=0.5, weight=2),
    get_style_function("blue", opacity=0.5, weight=1),
]


# Main function to create a simple map
def simple_map(CRS="EPSG:4326", *objects):
    """A quick function to generate a folium map for any col from a dataframe.
    objects: list of GeoDataFrames

    Returns: folium map object
    """
    # Convert GeoDataFrames to the specified CRS
    objects = [obj.to_crs(CRS) if obj is not None else None for obj in objects]

    # Create a folium map object centered on the first GeoDataFrame
    if objects:
        map_data = folium.Map(
            location=[
                objects[0].geometry.centroid.y.mean(),
                objects[0].geometry.centroid.x.mean(),
            ],
            zoom_start=17,
        )
    else:
        raise ValueError("At least one GeoDataFrame must be provided")

    # Add the custom basemap
    map_data = add_google_satellite(map_data)

    # Add GeoDataFrames as GeoJSON layers with styles
    for obj, style in zip(objects, available_styles):
        if obj is not None:
            folium.GeoJson(obj, style_function=style).add_to(map_data)

    # Cycle through styles if more objects than styles
    if len(objects) > len(available_styles):
        for obj in objects[len(available_styles) :]:
            if obj is not None:
                folium.GeoJson(
                    obj,
                    style_function=get_style_function("black", opacity=0.5, weight=1),
                ).add_to(map_data)

    return map_data


def plot_facility_example(
    facility_row,
    facility_crs="EPSG:26915",
    buffer=1000,
    figsize=(4, 4),
    basemap_source=ctx.providers.Esri.WorldImagery,
    save_path=None,
    dpi=300,
    zoom=1,
    show_facility=True,
    show_barns=True,
    show_permits=True,
    show_text=True,
    show_legend=True,
    show_scale=True,
):
    """
    Plots an example facility on a satellite basemap with fixed output size.
    The output plot will always be 5 cm x 5 cm regardless of facility geometry buffering.

    Parameters:
    - facility_row: a Pandas Series representing one facility with keys:
          'facility_geom': either a WKT string or a shapely geometry.
          'barn_geometries': list of WKT strings or shapely geometries for barns.
          'permit_geometries': list of WKT strings or shapely geometries for permits.
          Also expects 'reported_animal_units', 'estimated_animal_units', and 'swine_cat_combined_label'.
    - facility_crs: CRS of the input geometries (default "EPSG:26915").
    - buffer: Buffer (in CRS units) to expand the plot extent around the facility boundary.
    - figsize: Tuple for figure size in inches (default set to 5cm x 5cm).
    - basemap_source: Contextily basemap source (default Esri World Imagery).
    - save_path: File path to save the figure; if None, the plot is not saved.
    - dpi: DPI for saving the figure (default 300).
    - zoom: Zoom factor >= 1. Narrows the viewport to buffer/zoom meters in each direction,
            centered at the same point. Scale bar label is divided by zoom accordingly.
    - show_facility: Whether to show the facility boundary (default True).
    - show_barns: Whether to show barn geometries (default True).
    - show_permits: Whether to show permit geometries (default True).
    - show_text: Whether to show the information text box (default True).
    - show_legend: Whether to show the legend (default True).
    - show_scale: Whether to show the scale bar (default True).
    """

    if zoom < 1:
        raise ValueError("zoom must be >= 1")

    # ---------- helpers -----------------------------------------------------
    def convert_geom(geom):
        """Return a shapely geometry whether input is WKT or already shapely."""
        return wkt.loads(geom) if isinstance(geom, str) else geom

    def merge_facility_geom(geom, heal=True):
        """
        Collapse adjacent polygons inside a Polygon/MultiPolygon to one piece.
        `heal=True` adds a .buffer(0) to fix tiny gaps or slivers.
        """
        if geom is None:
            return geom
        # if it's already a single Polygon, unary_union is a no-op
        merged = unary_union(geom)  # works on Polygon|MultiPolygon
        return merged.buffer(1) if heal else merged

    # ------------------------------------------------------------------------

    # Function to convert WKT strings to geometries if needed.
    def convert_geom(geom):
        return wkt.loads(geom) if isinstance(geom, str) else geom

    # ---------- facility geometry (combined) --------------------------------
    fac_geom_raw = convert_geom(facility_row["facility_geom"])
    fac_geom = merge_facility_geom(fac_geom_raw)

    # ---------- barn & permit geometries (unchanged) ------------------------
    barn_geoms = [convert_geom(g) for g in facility_row["barn_geoms"]]
    permit_geoms = [convert_geom(g) for g in facility_row["permit_geoms"]]

    # Create GeoDataFrames.
    fac_gdf = gpd.GeoDataFrame(
        {"id": ["Facility"]}, geometry=[fac_geom], crs=facility_crs
    )
    barn_gdf = gpd.GeoDataFrame(
        {"id": ["Barn"] * len(barn_geoms)}, geometry=barn_geoms, crs=facility_crs
    )
    permit_gdf = gpd.GeoDataFrame(
        {"id": ["Permit"] * len(permit_geoms)}, geometry=permit_geoms, crs=facility_crs
    )

    # Reproject to EPSG:3857 for basemap compatibility.
    fac_gdf = fac_gdf.to_crs(epsg=3857)
    barn_gdf = barn_gdf.to_crs(epsg=3857)
    permit_gdf = permit_gdf.to_crs(epsg=3857)

    # Create the plot with fixed figure size.
    fig, ax = plt.subplots(figsize=figsize)

    # Plot facility boundary.
    if show_facility:
        fac_gdf.boundary.plot(
            ax=ax, edgecolor="blue", linewidth=4, label="Facility Boundary"
        )

    # Plot barn geometries (filled with semi-transparent red).
    if show_barns:
        barn_gdf.plot(ax=ax, color="red", alpha=0.7, edgecolor="red", linewidth=1.5)

    # Plot permit geometries.
    if show_permits:
        if permit_gdf.geom_type.unique()[0] == "Point":
            permit_gdf.plot(
                ax=ax, color="yellow", markersize=20, label="Permit Locations"
            )
        else:
            permit_gdf.boundary.plot(
                ax=ax, edgecolor="green", linewidth=2, label="Permit Boundaries"
            )

    # Instead of using facility's bounds directly (which vary), we fix the extent based on the facility centroid.
    # Use the first permit's centroid as the center point
    if not permit_gdf.empty:
        center = permit_gdf.geometry.iloc[0].centroid
    else:
        center = fac_gdf.geometry.unary_union.centroid
    # Define a fixed half-width and half-height (in meters); here, we use the buffer parameter.
    half_width = buffer / zoom
    half_height = buffer / zoom
    ax.set_xlim(center.x - half_width, center.x + half_width)
    ax.set_ylim(center.y - half_height, center.y + half_height)

    # Add the basemap.
    ctx.add_basemap(ax, source=basemap_source, attribution="")

    # Add Scale Bar (10 meters)
    if show_scale:
        scale_length = 100 / zoom
        margin = 10 / zoom
        scale_x = center.x - half_width + margin
        scale_y = center.y + half_height - margin

        # Create alternating black and white stripes
        num_stripes = 5
        stripe_width = scale_length / num_stripes

        for i in range(num_stripes):
            # Alternate between black and white stripes
            is_black = i % 2 == 0
            stripe_start = scale_x + (i * stripe_width)
            stripe_end = stripe_start + stripe_width

            # Draw the stripe
            if is_black:
                # For black stripes, draw a thicker line with solid black fill
                ax.plot(
                    [stripe_start, stripe_end],
                    [scale_y, scale_y],
                    color="black",
                    linewidth=5,
                    solid_capstyle="butt",
                    solid_joinstyle="miter",
                )
            else:
                # For white stripes, draw a white line
                ax.plot(
                    [stripe_start, stripe_end],
                    [scale_y, scale_y],
                    color="white",
                    linewidth=5,
                    solid_capstyle="butt",
                    solid_joinstyle="miter",
                )

        # Add scale text
        ax.text(
            scale_x + scale_length / 2,
            scale_y - 40 / zoom,
            f"{int(scale_length)}m",
            ha="center",
            fontsize=8,
            color="black",
            bbox=dict(
                facecolor="white",
                edgecolor="black",
                alpha=1.0,
                boxstyle="round,pad=0.2",
            ),  # Add black border
        )

    # Create an annotation text.
    if show_text:
        rep = facility_row.get("reported_animal_units", "N/A")
        est = facility_row.get("estimated_animal_units", "N/A")
        swine = facility_row.get("swine_cat_combined_label", "N/A")
        try:
            rep_int = int(round(rep))
        except Exception:
            rep_int = rep
        try:
            est_int = int(round(est))
        except Exception:
            est_int = est
        annotation_text = f"Reported: {rep_int}\nEstimated: {est_int}\nType: {swine}"

        # Place the annotation in axes-relative coordinates.
        ax.text(
            0.97,
            0.97,
            annotation_text,
            transform=ax.transAxes,
            fontsize=12,
            color="black",
            fontweight="bold",
            verticalalignment="top",
            horizontalalignment="right",
            bbox=dict(facecolor="white", alpha=0.9, edgecolor="none"),
        )

    # Remove axes for a clean look.
    ax.axis("off")

    # Create custom legend entries.
    legend_elements = []
    if show_facility:
        legend_elements.append(
            Patch(
                facecolor="none",
                edgecolor="blue",
                linewidth=2,
                label="Facility Boundary",
            )
        )
    if show_barns:
        legend_elements.append(
            Patch(facecolor="red", edgecolor="red", alpha=0.3, label="Barn Areas")
        )
    if show_permits:
        if permit_gdf.geom_type.unique()[0] == "Point":
            legend_elements.append(
                Patch(facecolor="yellow", edgecolor="yellow", label="Permit Locations")
            )
        else:
            legend_elements.append(
                Patch(
                    facecolor="none",
                    edgecolor="green",
                    linewidth=2,
                    label="Permit Boundaries",
                )
            )
    if (
        legend_elements and show_legend
    ):  # Only add legend if there are elements to show and legend is enabled
        ax.legend(handles=legend_elements, loc="lower right")

    # Force the axes to fill the figure completely to avoid variable margins.
    ax.set_position([0, 0, 1, 1])

    # Save the plot if a save_path is provided.
    if save_path:
        plt.savefig(save_path, dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.show()
    return fig, ax


def build_facility_crop(
    facility_id,
    out_dir,
    buffer=75,
    output_pixels=1024,
    config_filepath="cafo_iowa/data/cfg/config.yaml",
    engine=None,
):
    """
    Build a square, georeferenced image crop for one facility, sized to guarantee every
    one of its barn annotations (processed.barns) is fully contained, plus marked/unmarked
    PNG renders for viewing.

    Unlike plot_facility_example, this takes a facility_id directly (small targeted
    queries) rather than a pre-built facility_row from the whole-dataset get_facilities()
    join, and it pulls real NAIP tiles (via cafo_iowa.data.helpers.gcs.download_single_img)
    rather than a contextily web basemap.

    Writes three files into out_dir:
      - crop.tif: the cropped mosaic, ALL original NAIP bands (R,G,B,NIR), native 1m
        resolution, real CRS/transform -- not meant for casual viewing.
      - image_unmarked.png: same crop, RGB-rendered, resampled to output_pixels x
        output_pixels, no annotations.
      - image_marked.png: same crop, RGB-rendered, with facility boundary, permit
        marker, and each barn individually numbered.

    Returns a dict: {facility_id, window_bounds (in EPSG:26915), window_crs, tile_crs,
    tiles_used, barns: [{number, id, geometry_wkt}]} -- for the caller to fold into its
    own metadata.json (this function doesn't know about inspection documents).
    """
    if engine is None:
        engine = s.get_engine()

    # ---- 1. targeted per-facility geometry fetch (NOT get_facilities()) ----
    fac = gpd.read_postgis(
        sqlalchemy.text(
            "SELECT facility_id, geometry FROM processed.facilities WHERE facility_id = :fid"
        ),
        engine, geom_col="geometry", params={"fid": facility_id},
    )
    if fac.empty:
        raise ValueError(f"No facility found for facility_id={facility_id!r}")
    facility_crs = fac.crs

    barns = gpd.read_postgis(
        sqlalchemy.text(
            "SELECT id, geometry FROM processed.barns WHERE facility_id = :fid"
        ),
        engine, geom_col="geometry", params={"fid": facility_id},
    )
    permits = gpd.read_postgis(
        sqlalchemy.text(
            "SELECT geometry FROM processed.permits WHERE facility_id = :fid"
        ),
        engine, geom_col="geometry", params={"fid": facility_id},
    )

    # ---- 2. window geometry: square, centered on the (first) permit point, sized to ----
    # ---- guarantee every barn is inside + a fixed buffer ----
    if not permits.empty:
        center = permits.geometry.iloc[0]
    else:
        center = fac.geometry.iloc[0].centroid

    if not barns.empty:
        half_side = buffer
        for geom in barns.geometry:
            minx, miny, maxx, maxy = geom.bounds
            for cx, cy in [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]:
                dist = ((cx - center.x) ** 2 + (cy - center.y) ** 2) ** 0.5
                half_side = max(half_side, dist + buffer)
    else:
        half_side = buffer

    window_bounds = (
        center.x - half_side, center.y - half_side,
        center.x + half_side, center.y + half_side,
    )
    window_geom_26915 = box(*window_bounds)

    # ---- 3. tile selection against the WINDOW (not the raw facility polygon) ----
    window_gdf = gpd.GeoDataFrame({"id": [0]}, geometry=[window_geom_26915], crs=facility_crs)
    with engine.connect() as conn:
        tiles = gpd.read_postgis(
            sqlalchemy.text(
                "SELECT id, geometry FROM processed.naip21_qt "
                "WHERE ST_Intersects(geometry, ST_GeomFromText(:wkt, :srid))"
            ),
            conn, geom_col="geometry",
            params={"wkt": window_geom_26915.wkt, "srid": facility_crs.to_epsg()},
        )
    if tiles.empty:
        raise ValueError(f"No naip21_qt tiles intersect the crop window for facility_id={facility_id!r}")
    tile_ids = tiles["id"].tolist()

    # ---- 4. fetch + mosaic tiles ----
    tile_paths = [gcs.download_single_img(t, config_filepath=config_filepath) for t in tile_ids]
    srcs = [rasterio.open(p) for p in tile_paths]
    tile_crs = srcs[0].crs
    merged_arr, merged_transform = rasterio_merge(srcs)
    for src in srcs:
        src.close()

    # ---- 5. reproject window to the raster's actual CRS (NAD83 UTM vs WGS84 UTM differ) ----
    window_gdf_tilecrs = window_gdf.to_crs(tile_crs)
    wminx, wminy, wmaxx, wmaxy = window_gdf_tilecrs.geometry.iloc[0].bounds

    pixel_window = window_from_bounds(wminx, wminy, wmaxx, wmaxy, transform=merged_transform)
    pixel_window = pixel_window.round_offsets().round_lengths()
    # clip to the merged raster's own extent
    full_h, full_w = merged_arr.shape[1], merged_arr.shape[2]
    col_off = max(0, int(pixel_window.col_off))
    row_off = max(0, int(pixel_window.row_off))
    col_end = min(full_w, col_off + int(pixel_window.width))
    row_end = min(full_h, row_off + int(pixel_window.height))

    cropped = merged_arr[:, row_off:row_end, col_off:col_end]
    from rasterio.windows import Window
    cropped_transform = window_transform(Window(col_off, row_off, col_end - col_off, row_end - row_off), merged_transform)

    os.makedirs(out_dir, exist_ok=True)

    # ---- 6. write crop.tif: all original bands, native resolution, real georeferencing ----
    crop_tif_path = os.path.join(out_dir, "crop.tif")
    with rasterio.open(
        crop_tif_path, "w", driver="GTiff",
        height=cropped.shape[1], width=cropped.shape[2], count=cropped.shape[0],
        dtype=cropped.dtype, crs=tile_crs, transform=cropped_transform,
    ) as dst:
        dst.write(cropped)

    # ---- 7. render PNGs (RGB only, resampled to output_pixels x output_pixels) ----
    rgb = np.dstack([cropped[0], cropped[1], cropped[2]])
    extent = (wminx, wmaxx, wminy, wmaxy)  # matches cropped_transform's actual bounds closely enough for display
    dpi = 100
    figsize = (output_pixels / dpi, output_pixels / dpi)

    def _new_ax():
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        ax.set_position([0, 0, 1, 1])
        ax.axis("off")
        ax.imshow(rgb, extent=extent, origin="upper")
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
        return fig, ax

    fig, ax = _new_ax()
    fig.savefig(os.path.join(out_dir, "image_unmarked.png"), dpi=dpi)
    plt.close(fig)

    fig, ax = _new_ax()
    fac_tilecrs = fac.to_crs(tile_crs)
    fac_tilecrs.boundary.plot(ax=ax, edgecolor="blue", linewidth=2)
    if not permits.empty:
        permits.to_crs(tile_crs).plot(ax=ax, color="yellow", edgecolor="black", markersize=40)
    barn_meta = []
    if not barns.empty:
        barns_tilecrs = barns.to_crs(tile_crs)
        for i, (_, row) in enumerate(barns_tilecrs.iterrows(), start=1):
            gpd.GeoSeries([row.geometry], crs=tile_crs).boundary.plot(ax=ax, edgecolor="red", linewidth=2)
            c = row.geometry.centroid
            ax.annotate(
                str(i), (c.x, c.y), color="white", fontsize=14, fontweight="bold",
                ha="center", va="center",
                path_effects=[pe.withStroke(linewidth=3, foreground="red")],
            )
            barn_meta.append({"number": i, "id": barns.iloc[i - 1]["id"], "geometry_wkt": barns.iloc[i - 1].geometry.wkt})
    fig.savefig(os.path.join(out_dir, "image_marked.png"), dpi=dpi)
    plt.close(fig)

    return {
        "facility_id": facility_id,
        "window_bounds_epsg26915": window_bounds,
        "window_crs": "EPSG:26915",
        "tile_crs": str(tile_crs),
        "tiles_used": tile_ids,
        "barns": barn_meta,
    }
