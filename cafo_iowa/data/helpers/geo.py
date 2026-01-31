import logging
import os
import time
import warnings
from itertools import combinations_with_replacement
from math import asin, cos, radians, sin, sqrt
from typing import Callable, Dict, List, Optional, Tuple

import geopandas as gpd
import googlemaps
import networkx as nx
import pandas as pd
import shapely
from fuzzywuzzy import fuzz
from geoalchemy2.elements import WKTElement
from networkx import connected_components, from_edgelist
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import clip_by_rect, nearest_points, unary_union
from tqdm import tqdm


def quarter_tiles(data: gpd.GeoDataFrame, id_col: str) -> gpd.GeoDataFrame:
    """
    Divides the bounding boxes in the given GeoDataFrame into four quarters based on their centroids.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame containing the bounding boxes.
        id_col (str): The column name in the GeoDataFrame representing the tile ID.

    Returns:
        gpd.GeoDataFrame: A new GeoDataFrame containing the quartered bounding boxes.
    """
    data_quartered = []

    for _, row in data.iterrows():

        poly = row.geometry
        x, y = poly.exterior.coords.xy
        # coordinates
        x1y1 = (x[0], y[0])
        x2y2 = (x[1], y[1])
        x3y3 = (x[2], y[2])
        x4y4 = (x[3], y[3])
        # midpoints
        mx1my1 = ((x[0] + x[1]) / 2, (y[0] + y[1]) / 2)
        mx2my2 = ((x[1] + x[2]) / 2, (y[1] + y[2]) / 2)
        mx3my3 = ((x[2] + x[3]) / 2, (y[2] + y[3]) / 2)
        mx4my4 = ((x[3] + x[0]) / 2, (y[3] + y[0]) / 2)
        # centroid
        cxcy = (poly.centroid.x, poly.centroid.y)

        # create quartered bounding boxes based on location around centroid
        data_quartered.extend(
            [
                {
                    f"{id_col}_qt": row[id_col] + "_TL",
                    id_col: row[id_col],
                    "geometry": Polygon([x1y1, mx1my1, cxcy, mx4my4, x1y1]),
                },
                {
                    f"{id_col}_qt": row[id_col] + "_TR",
                    id_col: row[id_col],
                    "geometry": Polygon([mx1my1, x2y2, mx2my2, cxcy, mx1my1]),
                },
                {
                    f"{id_col}_qt": row[id_col] + "_BL",
                    id_col: row[id_col],
                    "geometry": Polygon([mx4my4, cxcy, mx3my3, x4y4, mx4my4]),
                },
                {
                    f"{id_col}_qt": row[id_col] + "_BR",
                    id_col: row[id_col],
                    "geometry": Polygon([cxcy, mx2my2, x3y3, mx3my3, cxcy]),
                },
            ]
        )

    data_quartered = gpd.GeoDataFrame(data_quartered, crs=data.crs).reset_index(
        drop=True
    )

    return data_quartered


def add_buffer_geometry(data, buffer_size=200):
    """
    Adds a buffer to the geometry of a given GeoDataFrame.

    Parameters:
    - data (GeoDataFrame): The input GeoDataFrame.
    - buffer_size (float): The size of the buffer in meters. Default is 200.

    Returns:
    - GeoSeries: A GeoSeries containing the buffered geometries.
    """

    # change crs to calculate buffer in meters
    object_crs = data.crs
    estimated_utm = data.estimate_utm_crs()
    data = data.to_crs(estimated_utm)
    # add buffer to the bounding boxes
    data["geometry_buffer"] = data.buffer(buffer_size)
    # change crs back to original
    data = data.to_crs(object_crs)
    return data["geometry_buffer"]


def geocode(address, max_retries=3, retry_delay=1):
    """
    Geocodes the given address using the Google Maps Geocoding API.

    Args:
        address (str): The address to geocode.
        max_retries (int, optional): The maximum number of retries in case of geocoding failure. Defaults to 3.
        retry_delay (int, optional): The delay in seconds between retries. Defaults to 1.

    Returns:
        tuple: A tuple containing the latitude and longitude of the geocoded address.
               If geocoding fails, returns (None, None).
    """

    try:
        gmaps_key = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))
    except Exception as e:
        logging.error(f"Error: No google maps API key provided {str(e)}")
        return print(
            "Error: No google maps API key provided. Add API key to .env file."
        )

    for attempt in range(max_retries):
        try:
            geocode_result = gmaps_key.geocode(
                address, components={"country": "US", "administrative_area": "IA"}
            )
            if geocode_result:
                lat = geocode_result[0]["geometry"]["location"]["lat"]
                lng = geocode_result[0]["geometry"]["location"]["lng"]
                return lat, lng
            else:
                logging.warning(
                    f"Geocoding failed for address: {address}. Empty result."
                )
                return None, None
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(
                    f"Geocoding failed for address: {address}. Error: {str(e)}. Retrying in {retry_delay} seconds..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logging.error(
                    f"Geocoding failed for address: {address}. Error: {str(e)}. Max retries exceeded."
                )
                return None, None


def geocode_addresses(
    addresses, cache_file="data/cache/locations.csv", max_retries=3, retry_delay=1
):
    """
    Geocodes a list of addresses and saves the results in a cache file.

    Args:
        addresses (list): A list of addresses to geocode.
        cache_file (str): The path to the cache file where the geocoded results will be saved.
        max_retries (int, optional): The maximum number of retries for geocoding an address. Defaults to 3.
        retry_delay (int, optional): The delay in seconds between retries. Defaults to 1.

    Returns:
        None
    """

    # check if cache file exists
    if os.path.exists(cache_file):
        cache = pd.read_csv(cache_file)
    else:
        cache = pd.DataFrame(columns=["address", "lat", "lng"])

    # remove missing addresses
    addresses = [address for address in addresses if pd.notna(address)]

    # remove leading and trailing whitespaces from addresses
    addresses = [str(address).strip() for address in addresses]

    # make sure addresses are unique
    addresses = list(set(addresses))

    # check if addresses are already in cache
    missing_addresses = [
        address for address in addresses if address not in cache["address"].values
    ]

    # Geocode missing addresses
    latitudes = []
    longitudes = []
    new_rows = []

    with tqdm(total=len(missing_addresses), desc="Geocoding addresses") as pbar:
        for address in missing_addresses:
            lat, lng = geocode(address, max_retries, retry_delay)
            latitudes.append(lat)
            longitudes.append(lng)
            new_rows.append({"address": address, "lat": lat, "lng": lng})
            pbar.update(1)

    # Add new rows to the cache
    if new_rows:
        new_cache = pd.DataFrame(new_rows)
        cache = pd.concat([cache, new_cache], ignore_index=True)
        cache.to_csv(cache_file, index=False)

    return cache


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two points on Earth using the haversine formula.

    Args:
        lat1 (float): Latitude of the first point in degrees.
        lon1 (float): Longitude of the first point in degrees.
        lat2 (float): Latitude of the second point in degrees.
        lon2 (float): Longitude of the second point in degrees.

    Returns:
        float: Distance between the two points in kilometers.
    """
    # Convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of the Earth in kilometers
    return c * r


def transform_coordinates(
    raw_coords: Polygon, tile_bounds: Tuple[float, float, float, float]
) -> List[Tuple[float, float]]:
    """
    Transforms raw pixel coordinates of a shapely Polygon to geographic coordinates based on the tile's bounds.
    """

    width = tile_bounds[2] - tile_bounds[0]
    height = tile_bounds[3] - tile_bounds[1]

    return [
        (
            tile_bounds[0] + (x / width) * (tile_bounds[2] - tile_bounds[0]),
            tile_bounds[3] - (y / height) * (tile_bounds[3] - tile_bounds[1]),
        )
        for x, y in raw_coords.exterior.coords
    ]


def clip_annotation_to_tile(
    annotation_geom: Polygon, tile_bounds: Tuple[float, float, float, float]
) -> Tuple[Polygon, bool]:
    """
    Clips the annotation geometry to the extent of the tile.
    """
    try:
        if not isinstance(annotation_geom, (Polygon, MultiPolygon)):
            warnings.warn("Annotation is not a polygon or multipolygon")
            return annotation_geom, False

        if not annotation_geom.is_valid:
            annotation_geom = annotation_geom.buffer(0)

        clipped_geom = clip_by_rect(annotation_geom, *tile_bounds)
        was_clipped = not annotation_geom.equals(clipped_geom)

        return clipped_geom, was_clipped
    except Exception as e:
        raise ValueError(
            f"Error during clipping: {str(e)}, {annotation_geom}, {tile_bounds}"
        )


def merge_overlapping_geometries(gdf):
    """
    Merge overlapping geometries in a GeoDataFrame efficiently using spatial indices and connected components.

    Parameters:
    gdf (GeoDataFrame): The input GeoDataFrame containing geometries.

    Returns:
    merged_gdf (GeoDataFrame): A new GeoDataFrame with merged geometries.
    """
    # Build a spatial index for the geometries
    sindex = gdf.sindex

    # Initialize an undirected graph
    G = nx.Graph()

    # Add all geometry indices as nodes in the graph
    G.add_nodes_from(gdf.index)

    # For each geometry, find potential overlaps using the spatial index
    for idx, geom in gdf.geometry.items():
        # Get candidate neighbors using the spatial index
        possible_matches_index = list(sindex.intersection(geom.bounds))
        # Exclude the geometry itself if present
        possible_matches_index = [i for i in possible_matches_index if i != idx]
        for other_idx in possible_matches_index:
            other_geom = gdf.geometry[other_idx]
            if geom.intersects(other_geom):
                # Add an edge between overlapping geometries
                G.add_edge(idx, other_idx)

    # Identify connected components (groups of overlapping geometries)
    connected_components = list(nx.connected_components(G))

    # Merge geometries within each connected component
    merged_geometries = []
    for component in connected_components:
        component_list = list(component)  # Convert the set to a list
        # Merge geometries in the component
        merged_geom = unary_union(gdf.loc[component_list].geometry)
        # Use attributes from the first geometry in the component
        merged_row = gdf.loc[component_list[0]].copy()
        merged_row.geometry = merged_geom
        merged_geometries.append(merged_row)

    # Create a new GeoDataFrame from merged geometries
    merged_gdf = gpd.GeoDataFrame(merged_geometries, crs=gdf.crs)
    return merged_gdf


def convert_geometries_to_wkt(data, srid):
    for col in data.columns:
        if col.startswith("geometry"):
            data[col] = data[col].apply(
                lambda x: WKTElement(x.wkt, srid=srid) if x is not None else None
            )
        elif col == "raw_coordinates":  # For specific cases like CF annotations
            data[col] = data[col].apply(
                lambda x: WKTElement(x.wkt) if x is not None else None
            )
    return data


def get_clusters(gdf: gpd.GeoDataFrame, buffer: float = 0) -> gpd.GeoDataFrame:

    if any(gdf.index.duplicated()):
        raise ValueError("Duplicated Index")

    object_crs = gdf.crs
    estimated_utm = gdf.estimate_utm_crs()

    # Check if estimated_utm CRS is in meters
    if (
        not estimated_utm.is_projected
        or estimated_utm.axis_info[0].unit_name != "metre"
    ):
        raise ValueError(
            "The estimated UTM CRS is not in meters. Please verify the CRS."
        )

    cluster_geoms = (
        gdf.to_crs(estimated_utm).buffer(buffer).to_crs(object_crs).unary_union
    )

    if not isinstance(cluster_geoms, shapely.geometry.MultiPolygon):
        cluster_geoms = shapely.geometry.MultiPolygon([cluster_geoms])

    parts = gpd.GeoDataFrame(
        geometry=list(cluster_geoms.geoms),
        crs=gdf.crs,
    )

    intermediate_clusters = (
        gdf.sjoin(parts, how="left", predicate="intersects")["index_right"]
        .rename("cluster_id")
        .to_frame()
        .reset_index()
    )

    G = from_edgelist(
        [
            edge
            for clique in intermediate_clusters.groupby("cluster_id")["index"].agg(list)
            for edge in combinations_with_replacement(clique, 2)
        ]
    )
    return (
        pd.DataFrame(
            enumerate(connected_components(G)), columns=["cluster_id", "index"]
        )
        .explode("index")
        .set_index("index")["cluster_id"]
    )


def merge_nearby_features(
    gdf: gpd.GeoDataFrame,
    grouping_columns: Optional[List[str]] = None,
    buffer_distance: float = 500,
    attributes_to_aggregate: Optional[Dict[str, Callable]] = None,
    missing_values_action: str = "exclude",
    aggregate_geometry: bool = True,
    geometry_merge_func: Callable = unary_union,
    fuzzy_match: bool = False,
    fuzzy_match_rules: Optional[Dict] = None,
) -> gpd.GeoDataFrame:
    """
    Merges nearby spatial features in a GeoDataFrame based on specified grouping columns and proximity.

    This function groups features by specified attributes and merges those that are within a certain
    buffer distance of each other. It can also merge all overlapping geometries without any grouping
    by leaving `grouping_columns` empty or None.

    Parameters:
    ----------
    gdf : gpd.GeoDataFrame
        Input GeoDataFrame containing spatial features.
    grouping_columns : list of str, optional
        List of column names to group by. If empty or None, all features are considered in one group.
        When fuzzy_match=True, for each grouping column, additional token-based variations will be
        automatically created for better matching (e.g., for column "owner", "owner_token_sort" and
        "owner_token_set" will be created).
    buffer_distance : float, optional
        Distance in meters to consider features as "nearby". Default is 500 meters.
        Set to 0 to merge overlapping or touching geometries.
    attributes_to_aggregate : dict, optional
        Dictionary specifying how to aggregate attributes.
        Format: {'column_name': aggregation_function}
        If None, attributes from the first feature in each group are retained.
    missing_values_action : str, optional
        Determines how to handle missing values in grouping columns.
        'exclude' (default): Exclude features with missing grouping values.
        'include': Include features with missing grouping values.
    aggregate_geometry : bool, optional
        If True (default), geometries of nearby features are merged.
    geometry_merge_func : callable, optional
        Function to merge geometries. Default is `shapely.ops.unary_union`.
    fuzzy_match : bool, optional
        If True, use fuzzy matching for grouping columns instead of exact matching.
        When enabled, automatically creates token-based variations of grouping columns
        for better matching of strings with different word orders or extra/missing words.
    fuzzy_match_rules : dict, optional
        Dictionary specifying fuzzy matching rules for each grouping column.
        If not provided and fuzzy_match is True, defaults to:
        {
            'default': {'method': 'ratio', 'threshold': 80},
            'match_rules': 'any'
        }
        To override defaults, specify rules in the format:
        {
            'column_name': {'method': str, 'threshold': int} | [{'method': str, 'threshold': int}, ...],
            'match_rules': 'any'|'all'|'majority',
            'default': {'method': str, 'threshold': int}
        }
        Available methods: 'ratio', 'partial_ratio', 'token_sort_ratio', 'token_set_ratio'

    Returns:
    -------
    gpd.GeoDataFrame
        A GeoDataFrame with merged features, including an 'original_ids' column indicating the
        original feature IDs included in each merged feature and a 'features_merged' column
        indicating the number of features that were merged.
    """

    if grouping_columns is None:
        grouping_columns = []

    # Create a working copy of the input GeoDataFrame
    gdf = gdf.copy()

    # Set default fuzzy matching rules if fuzzy_match is True
    if fuzzy_match:
        default_rules = {
            "default": {"method": "ratio", "threshold": 80},
            "match_rules": "any",
        }
        if fuzzy_match_rules:
            # If rules are provided, merge them with defaults
            # This ensures any missing keys in provided rules fall back to defaults
            default_rules.update(fuzzy_match_rules)
        fuzzy_match_rules = default_rules

        # Create token-based variations for each grouping column
        expanded_grouping_columns = []
        for col in grouping_columns:
            # Add the original column
            expanded_grouping_columns.append(col)

            # Create token sort variation
            token_sort_col = f"{col}_token_sort"
            gdf[token_sort_col] = gdf[col].apply(
                lambda s: " ".join(sorted(str(s).split())) if pd.notna(s) else s
            )
            expanded_grouping_columns.append(token_sort_col)

            # Create token set variation
            token_set_col = f"{col}_token_set"
            gdf[token_set_col] = gdf[col].apply(
                lambda s: " ".join(sorted(set(str(s).split()))) if pd.notna(s) else s
            )
            expanded_grouping_columns.append(token_set_col)

            # Update fuzzy match rules to include the new columns if not already specified
            if col in fuzzy_match_rules:
                if token_sort_col not in fuzzy_match_rules:
                    fuzzy_match_rules[token_sort_col] = {
                        "method": "ratio",
                        "threshold": 85,
                    }
                if token_set_col not in fuzzy_match_rules:
                    fuzzy_match_rules[token_set_col] = {
                        "method": "ratio",
                        "threshold": 85,
                    }

        # Use expanded grouping columns for the merge
        grouping_columns = expanded_grouping_columns

    # Determine the ID column or fallback to index
    id_col = "id" if "id" in gdf.columns else None

    original_crs = gdf.crs
    utm_crs = gdf.estimate_utm_crs()
    if not utm_crs.is_projected or utm_crs.axis_info[0].unit_name != "metre":
        raise ValueError(
            "The estimated UTM CRS is not in meters. Please verify the CRS."
        )

    gdf = gdf.to_crs(utm_crs)

    # Handle missing values in grouping columns
    if grouping_columns:
        # Create a boolean mask for missing or empty values
        missing_or_empty_mask = (
            gdf[grouping_columns].isna()
            | (gdf[grouping_columns].astype(str).apply(lambda x: x.str.strip() == ""))
        ).any(axis=1)

        if missing_values_action == "exclude":
            gdf_with_values = gdf[~missing_or_empty_mask].copy()
            gdf_missing_values = gdf[missing_or_empty_mask].copy()
        elif missing_values_action == "include":
            gdf_with_values = gdf.copy()
            gdf_missing_values = gpd.GeoDataFrame(columns=gdf.columns, crs=gdf.crs)
        else:
            raise ValueError("missing_values_action must be 'exclude' or 'include'")
    else:
        gdf_with_values = gdf.copy()
        gdf_missing_values = gpd.GeoDataFrame(columns=gdf.columns, crs=gdf.crs)

    merged_features = []

    # Group the GeoDataFrame by the specified grouping columns
    if grouping_columns:
        if fuzzy_match:
            # For fuzzy matching, we'll handle grouping differently
            # We'll process all features together and use fuzzy matching within spatial groups
            grouped = [(None, gdf_with_values)]
        else:
            grouped = gdf_with_values.groupby(grouping_columns)
    else:
        # If no grouping columns, treat all features as a single group
        grouped = [(None, gdf_with_values)]

    def combine_original_ids(sub_group):
        # If original_ids already exists, we combine them
        if "original_ids" in sub_group.columns:
            # Combine all lists of original_ids from the sub_group
            combined_ids = []
            for val in sub_group["original_ids"]:
                # Ensure that val is a list
                if isinstance(val, list):
                    combined_ids.extend(val)
                else:
                    combined_ids.append(val)
        else:
            # If no original_ids column, create from current IDs
            if id_col:
                combined_ids = sub_group[id_col].tolist()
            else:
                combined_ids = sub_group.index.tolist()
        return combined_ids

    def sum_features_merged(sub_group):
        # If features_merged already exists, sum it up
        if "features_merged" in sub_group.columns:
            return sub_group["features_merged"].sum()
        else:
            # Otherwise, the count is just the number of features
            return len(sub_group)

    def check_fuzzy_match(val1: str, val2: str, rules: Dict | List) -> bool:
        """Helper function to check if two values match according to fuzzy matching rules."""
        # Handle list of rules
        if isinstance(rules, list):
            return any(check_fuzzy_match(val1, val2, rule) for rule in rules)

        # Handle single rule
        method = rules.get("method", "ratio")
        threshold = rules.get(
            "threshold", 80
        )  # Fallback to 80 if no threshold specified

        if method == "ratio":
            return fuzz.ratio(val1, val2) >= threshold
        elif method == "partial_ratio":
            return fuzz.partial_ratio(val1, val2) >= threshold
        elif method == "token_sort_ratio":
            return fuzz.token_sort_ratio(val1, val2) >= threshold
        elif method == "token_set_ratio":
            return fuzz.token_set_ratio(val1, val2) >= threshold
        else:
            return fuzz.ratio(val1, val2) >= threshold

    # Iterate over each group
    for _, group in grouped:
        if len(group) == 1:
            group = group.copy()
            # Single feature: just add its IDs and merged count
            if id_col:
                original_ids = (
                    group["original_ids"].iloc[0]
                    if "original_ids" in group.columns
                    else [group[id_col].iloc[0]]
                )
            else:
                original_ids = (
                    group["original_ids"].iloc[0]
                    if "original_ids" in group.columns
                    else [group.index[0]]
                )

            features_merged_val = (
                group["features_merged"].iloc[0]
                if "features_merged" in group.columns
                else 1
            )

            group["original_ids"] = [original_ids]
            group["features_merged"] = features_merged_val
            merged_features.append(group)
            continue

        # Reset index to keep track of original indices if needed
        group = group.reset_index(drop=False)
        sindex = group.sindex

        G = nx.Graph()
        G.add_nodes_from(group.index)

        # Iterate over geometries to find nearby features
        for idx, geom in group.geometry.items():
            geom_buffer = geom.buffer(buffer_distance)
            possible_matches_index = list(sindex.intersection(geom_buffer.bounds))
            possible_matches_index = [i for i in possible_matches_index if i != idx]

            for other_idx in possible_matches_index:
                other_geom = group.geometry.iloc[other_idx]

                # Check if the actual distance is within buffer_distance
                if geom.distance(other_geom) <= buffer_distance:
                    # If using fuzzy matching, check similarity of grouping columns
                    if fuzzy_match and grouping_columns:
                        match_results = []
                        for col in grouping_columns:
                            val1 = str(group[col].iloc[idx])
                            val2 = str(group[col].iloc[other_idx])

                            # Get column-specific rules or fall back to default rules
                            rules = (
                                fuzzy_match_rules.get(col, fuzzy_match_rules["default"])
                                if col in fuzzy_match_rules
                                or "default" in fuzzy_match_rules
                                else {"method": "ratio", "threshold": 80}
                            )
                            match_results.append(check_fuzzy_match(val1, val2, rules))

                        # Determine if we should merge based on match_rules
                        match_rule = fuzzy_match_rules.get("match_rules", "any")
                        if match_rule == "all":
                            should_merge = all(match_results)
                        elif match_rule == "majority":
                            should_merge = sum(match_results) > len(match_results) / 2
                        else:  # "any" or default
                            should_merge = any(match_results)

                        if should_merge:
                            G.add_edge(idx, other_idx)
                    else:
                        G.add_edge(idx, other_idx)

        connected_components = nx.connected_components(G)
        neighbor_group_dict = {
            node: group_id
            for group_id, component in enumerate(connected_components)
            for node in component
        }
        group["neighbor_group"] = group.index.map(neighbor_group_dict)

        # Merge features within each neighbor group
        for _, sub_group in group.groupby("neighbor_group"):
            merged_row = {}

            # Retain grouping columns (if any)
            for col in grouping_columns:
                merged_row[col] = sub_group.iloc[0][col]

            # Aggregate attributes
            if attributes_to_aggregate:
                # Aggregate specified attributes
                for col, agg_func in attributes_to_aggregate.items():
                    merged_row[col] = agg_func(sub_group[col])

                # Retain the first value for other attributes
                for col in sub_group.columns:
                    if col not in (
                        grouping_columns
                        + list(attributes_to_aggregate.keys())
                        + ["geometry", "neighbor_group", "index"]
                    ):
                        merged_row[col] = sub_group.iloc[0][col]
            else:
                # If no aggregation specified, retain the first value
                for col in sub_group.columns:
                    if col not in grouping_columns + [
                        "geometry",
                        "neighbor_group",
                        "index",
                    ]:
                        merged_row[col] = sub_group.iloc[0][col]

            # Combine original_ids
            merged_row["original_ids"] = combine_original_ids(sub_group)
            # Sum features_merged
            merged_row["features_merged"] = sum_features_merged(sub_group)

            # Merge geometries if specified
            if aggregate_geometry:
                merged_geom = geometry_merge_func(sub_group.geometry)
                # Ensure the merged geometry is valid
                if isinstance(merged_geom, (Polygon, MultiPolygon)):
                    merged_row["geometry"] = merged_geom
                else:
                    merged_row["geometry"] = merged_geom.convex_hull
            else:
                merged_row["geometry"] = sub_group.unary_union

            # Convert the merged row to a GeoDataFrame
            merged_feature = gpd.GeoDataFrame([merged_row], crs=gdf.crs)
            merged_features.append(merged_feature)

    # Include features with missing grouping values if required
    if not gdf_missing_values.empty:
        gdf_missing_values = gdf_missing_values.copy()

        # If original_ids already exists, combine them; otherwise, use ID or index
        if "original_ids" in gdf_missing_values.columns:
            # already has original_ids, just ensure it's a list
            gdf_missing_values["original_ids"] = gdf_missing_values[
                "original_ids"
            ].apply(lambda x: x if isinstance(x, list) else [x])
        else:
            if id_col:
                gdf_missing_values["original_ids"] = gdf_missing_values[id_col].apply(
                    lambda x: [x]
                )
            else:
                gdf_missing_values["original_ids"] = (
                    gdf_missing_values.index.to_series().apply(lambda x: [x])
                )

        # If features_merged exists, use it; otherwise set to 1
        if "features_merged" not in gdf_missing_values.columns:
            gdf_missing_values["features_merged"] = 1

        merged_features.append(gdf_missing_values)

    # Concatenate all merged features into a single GeoDataFrame
    result = gpd.GeoDataFrame(
        pd.concat(merged_features, ignore_index=True), crs=gdf.crs
    )

    # Reproject the result back to the original CRS
    result = result.to_crs(original_crs)

    # Clean up temporary columns before returning if fuzzy match was used
    if fuzzy_match:
        # Remove the token-based columns we created
        for col in grouping_columns:
            if col.endswith(("_token_sort", "_token_set")):
                if col in result.columns:  # Check if column exists in result
                    result = result.drop(columns=[col])

    return result
