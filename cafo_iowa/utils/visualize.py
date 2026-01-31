import os

import contextily as ctx
import folium
import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import rasterio
import yaml
from matplotlib.patches import Patch
from rasterio.plot import show
from shapely import wkt
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
    - show_facility: Whether to show the facility boundary (default True).
    - show_barns: Whether to show barn geometries (default True).
    - show_permits: Whether to show permit geometries (default True).
    - show_text: Whether to show the information text box (default True).
    - show_legend: Whether to show the legend (default True).
    - show_scale: Whether to show the scale bar (default True).
    """

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
    half_width = buffer
    half_height = buffer
    ax.set_xlim(center.x - half_width, center.x + half_width)
    ax.set_ylim(center.y - half_height, center.y + half_height)

    # Add the basemap.
    ctx.add_basemap(ax, source=basemap_source, attribution="")

    # Add Scale Bar (10 meters)
    if show_scale:
        scale_length = 100  # 100 meters
        scale_x = center.x - half_width + 10
        scale_y = center.y + half_height - 10

        # Create alternating black and white stripes
        stripe_width = 20  # width of each stripe in meters
        num_stripes = int(scale_length / stripe_width)

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
            scale_y - 40,
            "100m",
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
