import json
import logging
from typing import Dict, List, Optional

import click
import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from shapely.geometry import Point, Polygon

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s
from cafo_iowa.data.helpers.geo import *
from cafo_iowa.data.helpers.matching import exact_match, fuzzy_match, tfidf_match
from cafo_iowa.db.funs import refresh_table, select_columns
from cafo_iowa.utils.utils import clean_text_for_matching, stable_hash

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Define dependencies when updating tables
# : if 'parcels' is updated, these tables also depend on it
DEPENDENCIES = {
    "naip21": ["naip21qt"],
    "naip21qt": ["permits", "cf_annotations"],
    "parcels": [
        "permits",
        "barnsparcels",
    ],
    "cf_annotations": ["barnsparcels"],
    "permits": ["permits_storage"],
}

# Common words to remove during fuzzy matching
FUZZY_WORDS_TO_REMOVE = [
    "LLC",
    "LP",
    "LC",
    "LLP",
    "LTD",
    "FARM",
    "CO",
    "CORP",
    "FARMS",
    "TRUST",
    "DAIRY",
    "INC",
    "REVOCABLE",
    "IRREVOCABLE",
    "FAMILY",
    "ACRES",
    "LAND",
    "REAL",
    "ESTATE",
    "RIDGE",
    "DATED",
    "BACON",
    "PORK",
    "PIG",
    "SWINE",
    "PIGS",
    "HOGS",
    "TRUCKING",
    "JOINT",
    "EST",
    "REM",
    "LF",
    "JT",
    "IRREVOCABLE",
    "REVOCABLE",
    "FEEDLOT",
    "LIVESTOCK",
]


def process_animal_weights(session):
    """
    Process and upload animal weight data to the database.

    This function:
    1. Loads animal weight data from a CSV file
    2. Adds an ID column
    3. Handles missing values
    4. Selects relevant columns
    5. Uploads the data to the AnimalWeights table

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Processing animal weights...")

    engine = session.bind

    data = pd.read_csv("data/animal_estimation/animal_weights.csv", index_col=False)

    # add id column
    data["id"] = range(1, len(data) + 1)

    # replace NaN with None
    data = data.replace({pd.NA: None, np.nan: None})

    # select columns
    data = select_columns(data, m.AnimalWeights, other_cols=False)

    # upload data
    refresh_table(session, data, m.AnimalWeights)


def process_urban(session):
    """
    Process urban area data and upload to the database.

    This function:
    1. Loads urban area data from the database
    2. Filters to only include urban areas that intersect with NAIP tiles
    3. Selects relevant columns
    4. Uploads the processed data to the UrbanAreas table

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Processing urban areas...")

    engine = session.bind

    # load the data, and subset it to only urban areas that intersect with NAIP tiles
    data = pd.read_sql(
        f"""
        SELECT * FROM raw.{m.UrbanAreasRaw.__tablename__}
        WHERE EXISTS (
            SELECT 1
            FROM raw.naip21 n
            WHERE ST_Intersects(raw.{m.UrbanAreasRaw.__tablename__}.geometry, n.geometry)
        )
        """,
        engine,
    )

    data = select_columns(data, m.UrbanAreas, other_cols=False)
    refresh_table(session, data, m.UrbanAreas)


def process_census_tracts(session):
    """
    Process census tract data and upload to the database.

    This function:
    1. Loads census tract data from the database
    2. Selects relevant columns
    3. Converts geometries to WKT format
    4. Uploads the processed data to the CensusTracts table

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Processing census tracts...")

    engine = session.bind

    data = gpd.read_postgis(
        f"SELECT * FROM raw.{m.CensusTractsRaw.__tablename__}",
        engine,
        geom_col="geometry",
    )

    # select columns
    data = select_columns(data, m.CensusTracts, other_cols=False)
    srid = int(data.crs.to_authority()[1])
    data = convert_geometries_to_wkt(data, srid)

    # upload data
    refresh_table(session, data, m.CensusTracts)


def process_naip(session):
    """
    Process NAIP satellite imagery data and upload to the database.

    This function:
    1. Loads NAIP tile data from the database
    2. Quarters tiles into smaller sections
    3. Adds urban area information
    4. Converts geometries to WKT format
    5. Uploads both original and quartered data to their respective tables

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Processing NAIP tiles...")

    engine = session.bind

    data = gpd.read_postgis(
        f"SELECT * FROM raw.{m.Naip21Raw.__tablename__}", engine, geom_col="geometry"
    )

    data_quartered = quarter_tiles(data, "id")
    data_quartered.rename(columns={"id": "naip_id", "id_qt": "id"}, inplace=True)
    data_quartered["geometry_buffer"] = add_buffer_geometry(
        data_quartered, buffer_size=200
    )

    # add urban columns
    urban = gpd.read_postgis(
        "SELECT * FROM processed.urban_areas", engine, geom_col="geometry"
    )

    data_quartered["is_urban"] = data_quartered["geometry"].apply(
        lambda x: urban["geometry"].intersects(x).any()
    )
    data_quartered["urban_area"] = data_quartered["geometry"].apply(
        lambda x: round((urban["geometry"].intersection(x).area.sum() / x.area), 2)
    )

    # convert geometries to WKT
    srid = int(data.crs.to_authority()[1])
    data = convert_geometries_to_wkt(data, srid)

    srid = int(data_quartered.crs.to_authority()[1])
    data_quartered = convert_geometries_to_wkt(data_quartered, srid)

    # select columns
    data = select_columns(data, m.Naip21, other_cols=False)
    data_quartered = select_columns(data_quartered, m.Naip21QT, other_cols=False)

    # upload data
    refresh_table(session, data, m.Naip21)
    refresh_table(session, data_quartered, m.Naip21QT)


def process_parcels(
    session,
    match_strategy: str = "combined",  # One of "exact", "fuzzy", "tfidf", or "combined"
    buffer_distance: float = 500,  # Distance in meters to consider features as "nearby"
    fuzzy_threshold: float = 75,  # Threshold for fuzzy matching (0-100)
    tfidf_threshold: float = 0.5,  # Threshold for TF-IDF matching (0-1)
    missing_values_action: str = "exclude",  # How to handle missing values
    words_to_remove: Optional[
        List[str]
    ] = None,  # Words to remove during fuzzy matching
):
    """
    Process and merge parcel data using configurable matching strategies.


    1. Manual Review Processing:
       - Loads manual parcel associations from CSV
       - Uses networkx to identify connected components
       - Merges parcels based on manual associations

    2. Parcel Number Matching:
       - Combines parcels with identical parcel numbers within the same county
       - Handles missing parcel numbers separately

    3. Geometry-based Matching:
       - Shrinks parcel geometries slightly to account for data inaccuracies
       - Merges parcels with overlapping geometries

    4. Owner Name Matching (configurable strategy):
       - Exact matching: Matches identical owner names within buffer distance
       - Fuzzy matching: Matches similar owner names using string similarity
       - TF-IDF matching: Matches owner names using term frequency analysis
       - Combined strategy: Applies multiple strategies in sequence

    Args:
        session: Database session object
        match_strategy (str, optional): Strategy for matching parcels. One of:
            - "exact": Matches identical owner names
            - "fuzzy": Matches similar owner names using string similarity
            - "tfidf": Matches owner names using term frequency analysis
            - "combined": Applies multiple strategies in sequence
            Defaults to "combined".
        buffer_distance (float, optional): Distance in meters to consider features as "nearby".
            Defaults to 500.
        fuzzy_threshold (float, optional): Threshold for fuzzy matching (0-100).
            Defaults to 75.
        tfidf_threshold (float, optional): Threshold for TF-IDF matching (0-1).
            Defaults to 0.5.
        missing_values_action (str, optional): How to handle missing values.
            One of "exclude" or "include". Defaults to "exclude".
        words_to_remove (List[str], optional): List of words to remove during fuzzy matching.
            If None, uses default list of business designations.

    Returns:
        None

    Note:
        The function maintains a cache of processed files to avoid reprocessing.
        The matching process is deterministic and reproducible due to fixed random seeds.
    """
    logging.info("Processing parcels...")

    # Set random seeds for reproducibility
    np.random.seed(42)

    engine = session.bind

    data = gpd.read_postgis(
        f"SELECT * from raw.{m.ParcelsRaw.__tablename__}", engine, geom_col="geometry"
    )

    # Sort data by ID to ensure consistent processing order
    if "id" in data.columns:
        data = data.sort_values(by=["id"])

    # make geometries valid
    data["geometry"] = data["geometry"].apply(
        lambda x: x if x.is_valid else x.buffer(0)
    )

    # add data from manual review
    manual_review = pd.read_csv(
        "data/manual_review/parcel-parcel-association.csv", index_col=False
    )

    # Process manual review data to merge parcels
    if not manual_review.empty:
        logging.info(f"Processing {len(manual_review)} manual parcel associations...")

        # Normalize parcel ID columns to strings (strip whitespace and ensure consistency)
        manual_review["parcel_id1"] = (
            manual_review["parcel_id1"].astype(str).str.strip()
        )
        manual_review["parcel_id2"] = (
            manual_review["parcel_id2"].astype(str).str.strip()
        )

        # Step 1: Build the graph of associations
        G = nx.Graph()
        G.add_edges_from(zip(manual_review["parcel_id1"], manual_review["parcel_id2"]))

        # Step 2: Find connected components (groups of associated parcels)
        components = list(nx.connected_components(G))

        # Step 3: Create a mapping of parcel_id -> group_id
        parcel_groups = {}
        for i, group in enumerate(components):
            group_id = f"manual_group_{i}"
            for parcel_id in group:
                parcel_groups[parcel_id] = group_id

        # Step 4: Map group IDs to the data using the normalized ID string
        data["manual_group"] = data["id"].map(parcel_groups)

        # Step 5: Dissolve grouped parcels
        data_with_groups = data[data["manual_group"].notna()].copy()
        data_without_groups = data[data["manual_group"].isna()].copy()

        if not data_with_groups.empty:
            nrows_before = len(data_with_groups)
            data_with_groups = data_with_groups.dissolve(
                by="manual_group", as_index=False
            )
            logging.info(
                f"After manual review processing with networkx, merged {nrows_before - len(data_with_groups)} parcels."
            )

        # Step 6: Combine the dissolved and undissolved data
        data = pd.concat([data_with_groups, data_without_groups], ignore_index=True)
        data = data.drop(columns=["manual_group", "id_str"], errors="ignore")

        # Combine the dissolved data with the original data that didn't have groups
        data = pd.concat([data_with_groups, data_without_groups], ignore_index=True)

        # Drop the manual_group column as it's no longer needed
        data = data.drop(columns=["manual_group"])

    # combine parcels with same parcelnumb (if not NA) if in the same county
    nrows_before = data.shape[0]
    na_rows = data[data["parcelnumb"].isna()]
    non_na_rows = data[data["parcelnumb"].notna()]
    non_na_rows = non_na_rows.dissolve(by=["parcelnumb", "county"], as_index=False)
    data = pd.concat([non_na_rows, na_rows], ignore_index=True)
    logging.info(
        f"Combined {nrows_before - data.shape[0]} rows with same parcelnumb and county."
    )

    # combine parcels with overlapping geometries
    nrows_before = data.shape[0]

    # first, shrink parcel geometries by 0.1 meters to account for data inaccuracies
    orig_crs = data.crs
    data = data.to_crs(data.estimate_utm_crs())
    data["geometry"] = data["geometry"].apply(lambda x: x.buffer(-0.1))
    data = data.to_crs(orig_crs)

    # merge parcels with overlapping geometries
    data = exact_match(
        data,
        grouping_columns=[],
        buffer_distance=0,
        missing_values_action=missing_values_action,
    )
    logging.info(
        f"Combined {nrows_before - data.shape[0]} parcels with overlapping geometries."
    )

    # Merge nearby parcels with similar owner names
    nrows_before = data.shape[0]

    # Clean owner names for exact and TF-IDF matching (basic cleaning)
    data["owner_clean"] = data["owner"].apply(
        lambda s: (
            clean_text_for_matching(s, standardize_separators=True)
            if pd.notna(s)
            else s
        )
    )

    # Clean owner names specifically for fuzzy matching (removing business designations)
    data["owner_fuzzy"] = data["owner"].apply(
        lambda s: (
            clean_text_for_matching(
                s,
                words_to_remove=words_to_remove or FUZZY_WORDS_TO_REMOVE,
            )
            if pd.notna(s)
            else s
        )
    )

    # Apply the specified matching strategy
    if match_strategy == "exact":
        data = exact_match(
            data,
            grouping_columns=["owner_clean"],
            buffer_distance=buffer_distance,
            missing_values_action=missing_values_action,
        )
    elif match_strategy == "tfidf":
        data = tfidf_match(
            data,
            grouping_columns=["owner_clean"],
            buffer_distance=buffer_distance,
            similarity_threshold=tfidf_threshold,
            missing_values_action=missing_values_action,
        )
    elif match_strategy == "fuzzy":
        data = fuzzy_match(
            data,
            grouping_columns=["owner_fuzzy"],
            buffer_distance=buffer_distance,
            threshold=fuzzy_threshold,
            missing_values_action=missing_values_action,
            words_to_remove=words_to_remove or FUZZY_WORDS_TO_REMOVE,
        )
    elif match_strategy == "combined":
        # First try exact matching
        data = exact_match(
            data,
            grouping_columns=["owner_clean"],
            buffer_distance=buffer_distance,
            missing_values_action=missing_values_action,
        )

        # Try fuzzy matching on remaining parcels
        data = fuzzy_match(
            data,
            grouping_columns=["owner_fuzzy"],
            buffer_distance=buffer_distance,
            threshold=fuzzy_threshold,
            missing_values_action=missing_values_action,
            words_to_remove=words_to_remove or FUZZY_WORDS_TO_REMOVE,
        )

        # Then try TF-IDF matching on remaining parcels
        data = tfidf_match(
            data,
            grouping_columns=["owner_clean"],
            buffer_distance=buffer_distance,
            similarity_threshold=tfidf_threshold,
            missing_values_action=missing_values_action,
        )

    else:
        raise ValueError(
            f"Invalid match_strategy: {match_strategy}. Must be one of 'exact', 'fuzzy', 'tfidf', or 'combined'."
        )

    logging.info(
        f"Combined {nrows_before - data.shape[0]} nearby parcels with similar owner names using {match_strategy} matching."
    )

    # convert geometries to WKT
    srid = int(data.crs.to_authority()[1])
    data = convert_geometries_to_wkt(data, srid)

    # select columns
    data = select_columns(data, m.Parcels, other_cols=False)

    # upload
    refresh_table(session, data, m.Parcels)


# Process Permit data
def process_permits(
    session,
    buffer_distance=1000,  # radius (meters) around each permit geometry for fuzzy matching
    fuzzy_threshold=80,  # threshold for fuzzy matching
    nearest_parcel_distance_m=150,  # distance for "assign nearest parcel" for those without parcel id
):
    logging.info("Processing permits...")
    # set random seeds for reproducibility
    np.random.seed(42)

    engine = session.bind

    # ---------------------------------------------------------------------
    # 1a) Load raw data from PermitsRaw
    # ---------------------------------------------------------------------
    data = gpd.read_postgis(
        f"SELECT * FROM raw.{m.PermitsRaw.__tablename__}", engine, geom_col="geometry"
    )

    # Sort data by ID to ensure consistent processing order
    if "id" in data.columns:
        data = data.sort_values(by=["id"])

    # ---------------------------------------------------------------------
    # 1b) Manual review
    # ---------------------------------------------------------------------

    # load empty permits from manual review
    empty_permits = pd.concat(
        [
            # pd.read_csv("data/manual_review/permits-empty_helena.csv", index_col=False),
            pd.read_csv("data/manual_review/permits-empty_arun.csv", index_col=False),
        ],
        ignore_index=True,  # Reset index after concatenation to avoid duplicate indices
    )

    # remove empty permits
    data = data[~data["id"].isin(empty_permits["permit_id"])]
    logging.info(f"Removed {len(empty_permits)} empty permits")

    # load destroyed permits from manual review
    destroyed_permits = pd.read_csv(
        "data/manual_review/permits-partially-destroyed_helena.csv", index_col=False
    )
    data = data[~data["id"].isin(destroyed_permits["permit_id"])]
    logging.info(f"Removed {len(destroyed_permits)} destroyed permits")

    # add new locations to manually reviewed permits
    permits_relocation = pd.read_csv(
        "data/manual_review/permit_relocations.csv", index_col=False
    )

    # Create Point geometries from location strings, ensuring correct order (lon, lat)
    permits_relocation["geometry"] = permits_relocation["location"].apply(
        lambda x: Point([float(coord.strip()) for coord in x.split(",")][::-1])
    )

    # Create GeoDataFrame with WGS84 CRS (EPSG:4326)
    permits_relocation = gpd.GeoDataFrame(permits_relocation, crs="EPSG:4326")

    # Convert to the same CRS as the data
    permits_relocation = permits_relocation.to_crs(data.crs)

    # Replace geometry for permits in data with the new geometry from permits_relocation
    updated_count = 0
    for _, row in permits_relocation.iterrows():
        permit_id = row["permit_id"]
        new_geometry = row["geometry"]

        # Find the index of the permit in data
        permit_indices = data[data["id"] == permit_id].index
        if not permit_indices.empty:
            # Update the geometry for this permit
            for idx in permit_indices:
                # Create a new GeoDataFrame with just this row to ensure proper assignment
                temp_gdf = gpd.GeoDataFrame(
                    data.loc[[idx]], geometry="geometry", crs=data.crs
                )
                temp_gdf.loc[idx, "geometry"] = new_geometry
                data.loc[idx, "geometry"] = temp_gdf.loc[idx, "geometry"]
            updated_count += 1

    logging.info(f"Updated geometry for {updated_count} permits from manual review")

    # ---------------------------------------------------------------------
    # 1c) Add variables
    # ---------------------------------------------------------------------

    data.rename(columns={"totalanima": "animal_units"}, inplace=True)
    data["swine_animal_units"] = data.filter(regex="^swine_").sum(axis=1)

    # Add categorical variables
    def determine_type(row):
        animal_types = []
        if row.get("horses", 0) > 0:
            animal_types.append("horses")
        if row["swine_animal_units"] > 0:
            animal_types.append("swine")
        if row.get("cattle_bee", 0) > 0 or row.get("cattle_b_1", 0) > 0:
            animal_types.append("cattle")
        if row.get("chicken_la", 0) > 0 or row.get("chicken_pu", 0) > 0:
            animal_types.append("chicken")
        if not animal_types:
            return "other"
        return "-".join(sorted(animal_types))

    def determine_swine_type(row):
        swine_types = []
        if row.get("swine_gest", 0) > 0:
            swine_types.append("gestation")
        if row.get("swine_gilt", 0) > 0:
            swine_types.append("gilt")
        if row.get("swine_grow", 0) > 0:
            swine_types.append("grow")
        if row.get("swine_nurs", 0) > 0:
            swine_types.append("nursery")
        if row.get("swine_sow", 0) > 0:
            swine_types.append("sow")
        if row.get("swine_wean", 0) > 0:
            swine_types.append("wean")
        if not swine_types:
            return "none"
        return "-".join(sorted(swine_types))

    data["animal_type"] = data.apply(determine_type, axis=1)
    data["swine_type"] = data.apply(determine_swine_type, axis=1)

    # ---------------------------------------------------------------------
    # 2) Geocode addresses
    # ---------------------------------------------------------------------
    data["address_geo"] = data["address"].str.cat(
        [data["city"], data["state"], data["zip"].astype(str)], sep=", "
    )
    locations = geocode_addresses(data["address_geo"]).rename(
        {"address": "address_geo", "lat": "lat_geo", "lng": "lng_geo"}, axis=1
    )
    locations = locations.drop_duplicates(subset=["address_geo"])
    data = pd.merge(data, locations, on="address_geo", how="left")

    data["distance_km"] = data.apply(
        lambda x: haversine_distance(
            x.get("lat_geo"), x.get("lng_geo"), x.get("latitude"), x.get("longitude")
        ),
        axis=1,
    )

    # ---------------------------------------------------------------------
    # 3) Add NAIP foreign IDs via a spatial join
    # ---------------------------------------------------------------------
    naip_qt = gpd.read_postgis(
        f"""
        SELECT
            id AS naip_qt_id,
            naip_id,
            geometry
        FROM processed.{m.Naip21QT.__tablename__}
        """,
        engine,
        geom_col="geometry",
    )
    data = gpd.sjoin(data, naip_qt, how="left", predicate="intersects")
    data.drop(columns=["index_right"], inplace=True)

    # ---------------------------------------------------------------------
    # 4) Load parcels for matching
    # ---------------------------------------------------------------------
    parcels = gpd.read_postgis(
        f"""
        SELECT
            id AS parcel_id,
            owner,
            geometry
        FROM processed.{m.Parcels.__tablename__}
        """,
        engine,
        geom_col="geometry",
    )

    # ---------------------------------------------------------------------
    # 5) Create permit-parcel associations based on geometry
    # ---------------------------------------------------------------------
    # Spatial join to get geometry-based matches
    geometry_matches = gpd.sjoin(
        data,
        parcels[["parcel_id", "owner", "geometry"]],
        how="left",
        predicate="intersects",
    )
    geometry_matches.drop(columns=["index_right"], inplace=True)

    # Create geometry-based associations
    geometry_associations = geometry_matches[
        geometry_matches["parcel_id"].notna()
    ].copy()
    geometry_associations["match_type"] = "geometry"
    geometry_associations["fuzzy_match_score"] = None
    geometry_associations["is_primary_match"] = True  # Geometry matches are primary

    # ---------------------------------------------------------------------
    # 6) Create permit-parcel associations based on fuzzy name matching
    # ---------------------------------------------------------------------
    # Clean facility names for exact and TF-IDF matching (basic cleaning)
    data["facilityna_clean"] = data["facilityna"].apply(
        lambda s: (
            clean_text_for_matching(s, standardize_separators=True)
            if pd.notna(s)
            else s
        )
    )

    # Clean facility names specifically for fuzzy matching (removing business designations)
    data["facilityna_fuzzy"] = data["facilityna"].apply(
        lambda s: (
            clean_text_for_matching(
                s,
                words_to_remove=FUZZY_WORDS_TO_REMOVE,
            )
            if pd.notna(s)
            else s
        )
    )

    # Clean owner names for fuzzy matching
    parcels["owner_fuzzy"] = parcels["owner"].apply(
        lambda s: (
            clean_text_for_matching(
                s,
                words_to_remove=FUZZY_WORDS_TO_REMOVE,
            )
            if pd.notna(s)
            else s
        )
    )

    # Buffer permit geometry to buffer_distance
    data_buffered = data.copy()
    data_buffered["geometry_buffer"] = data_buffered["geometry"].buffer(buffer_distance)
    data_buffered = data_buffered.set_geometry("geometry_buffer")

    # Spatial join to find candidate parcels within buffer_distance
    fuzzy_candidates = gpd.sjoin(
        data_buffered.drop(columns=["geometry"]),
        parcels[["parcel_id", "owner_fuzzy", "owner", "geometry"]],
        how="left",
        predicate="intersects",
    )

    # Evaluate fuzzy matches for each permit
    fuzzy_associations = []
    for permit_idx, group in fuzzy_candidates.groupby(level=0):
        facility_name = group["facilityna_fuzzy"].iloc[0]
        if pd.isna(facility_name):
            continue

        # Get all candidate owners for this permit
        candidate_owners = group["owner_fuzzy"].dropna().unique()
        if len(candidate_owners) == 0:
            continue

        # Calculate fuzzy match scores for each candidate owner
        for owner in candidate_owners:
            # Use both token_sort_ratio and partial_ratio and take the higher score
            token_sort_score = fuzz.token_sort_ratio(facility_name, owner)
            partial_score = fuzz.partial_ratio(facility_name, owner)
            best_score = max(token_sort_score, partial_score)

            if best_score >= fuzzy_threshold:
                best_parcel_id = group[group["owner_fuzzy"] == owner]["parcel_id"].iloc[
                    0
                ]

                fuzzy_associations.append(
                    {
                        "permit_id": group["id"].iloc[0],
                        "parcel_id": best_parcel_id,
                        "match_type": "fuzzy_name",
                        "fuzzy_match_score": best_score,
                        "is_primary_match": False,  # Fuzzy matches are secondary to geometry matches
                    }
                )

    fuzzy_associations_df = pd.DataFrame(fuzzy_associations)

    # ---------------------------------------------------------------------
    # 7) Create permit-parcel associations for unmatched permits using nearest parcel
    # ---------------------------------------------------------------------
    # Get permits that don't have any matches yet
    matched_permit_ids = set(geometry_associations["id"]).union(
        set(fuzzy_associations_df["permit_id"])
    )
    unmatched_permits = data[~data["id"].isin(matched_permit_ids)].copy()

    if not unmatched_permits.empty:
        logging.info(
            f"There are {len(unmatched_permits)} permits with no matches. "
            f"Assigning the nearest parcel now..."
        )

        def assign_nearest_parcel(row, parcels_gdf, max_distance=None):
            distances = parcels_gdf.distance(row["geometry"])
            nearest_idx = distances.idxmin()
            nearest_distance = distances[nearest_idx]
            if max_distance is not None and nearest_distance > max_distance:
                return None, None
            return parcels_gdf.loc[nearest_idx, "parcel_id"], nearest_distance

        nearest_associations = []
        for _, permit in unmatched_permits.iterrows():
            parcel_id, distance = assign_nearest_parcel(
                permit, parcels, max_distance=nearest_parcel_distance_m
            )
            if parcel_id is not None:
                nearest_associations.append(
                    {
                        "permit_id": permit["id"],
                        "parcel_id": parcel_id,
                        "match_type": "nearest",
                        "fuzzy_match_score": None,
                        "is_primary_match": True,  # These are primary matches since they're the only match
                    }
                )

        nearest_associations_df = pd.DataFrame(nearest_associations)
        logging.info(
            f"Assigned {len(nearest_associations_df)} permits "
            f"to a nearest parcel within {nearest_parcel_distance_m} meters."
        )
    else:
        nearest_associations_df = pd.DataFrame(
            columns=[
                "permit_id",
                "parcel_id",
                "match_type",
                "fuzzy_match_score",
                "is_primary_match",
            ]
        )

    # ---------------------------------------------------------------------
    # 8) Manual review
    # ---------------------------------------------------------------------

    # load permit-parcel associations from manual review
    permit_parcel_association_manual = pd.read_csv(
        "data/manual_review/permit-parcel-association.csv", index_col=False
    )

    # Add required columns to manual review data to match the structure of other associations
    permit_parcel_association_manual["match_type"] = "manual_review"
    permit_parcel_association_manual["fuzzy_match_score"] = None
    permit_parcel_association_manual["is_primary_match"] = (
        True  # Manual reviews are considered primary matches
    )

    # load permit-parcels associations from manual review that need to be removed
    permit_parcel_association_manual_remove = pd.read_csv(
        "data/manual_review/permit-parcel-association-remove.csv", index_col=False
    )

    # ---------------------------------------------------------------------
    # 8) Combine and store associations
    # ---------------------------------------------------------------------
    # Prepare geometry associations
    geometry_associations_df = geometry_associations[
        ["id", "parcel_id", "match_type", "fuzzy_match_score", "is_primary_match"]
    ].rename(columns={"id": "permit_id"})

    # Combine all types of associations
    all_associations = pd.concat(
        [
            geometry_associations_df,
            fuzzy_associations_df,
            nearest_associations_df,
            permit_parcel_association_manual,
        ],
        ignore_index=True,
    )

    # Remove duplicates where a parcel is matched both by geometry and fuzzy name
    # Keep the geometry match in these cases
    all_associations = all_associations.sort_values(
        by=["permit_id", "parcel_id", "is_primary_match"], ascending=[True, True, False]
    ).drop_duplicates(subset=["permit_id", "parcel_id"], keep="first")

    # Add an auto-incrementing id column
    all_associations["id"] = range(1, len(all_associations) + 1)

    # remove permit-parcel associations from manual review that need to be removed
    if not permit_parcel_association_manual_remove.empty:
        logging.info(
            f"Removing {len(permit_parcel_association_manual_remove)} erroneous permit-parcel associations from manual review"
        )

        # Create a composite key for matching
        all_associations["composite_key"] = (
            all_associations["permit_id"].astype(str)
            + "_"
            + all_associations["parcel_id"].astype(str)
        )
        permit_parcel_association_manual_remove["composite_key"] = (
            permit_parcel_association_manual_remove["permit_id"].astype(str)
            + "_"
            + permit_parcel_association_manual_remove["parcel_id"].astype(str)
        )

        # Remove the associations that match the manual review removal list
        all_associations = all_associations[
            ~all_associations["composite_key"].isin(
                permit_parcel_association_manual_remove["composite_key"]
            )
        ]

        # Drop the temporary composite key column
        all_associations = all_associations.drop(columns=["composite_key"])

    # Store associations
    refresh_table(session, all_associations, m.PermitParcels)

    # ---------------------------------------------------------------------
    # 9) Convert geometry to WKT, finalize columns, store permits
    # ---------------------------------------------------------------------
    srid = int(data.crs.to_authority()[1])
    data = convert_geometries_to_wkt(data, srid)

    # Remove parcel-related columns since we're using the association table now
    data = select_columns(data, m.Permits, other_cols=False)
    refresh_table(session, data, m.Permits)

    logging.info(f"Created {len(all_associations)} permit-parcel associations")
    logging.info(f"Geometry matches: {len(geometry_associations_df)}")
    logging.info(f"Fuzzy name matches: {len(fuzzy_associations_df)}")
    logging.info(
        f"-- of which {(all_associations.match_type == 'fuzzy_name').sum()} differ from geometry matches"
    )
    logging.info(f"Nearest parcel matches: {len(nearest_associations_df)}")


def process_permits_storage(session):
    """
    Process permit storage data and upload to the database.

    This function:
    1. Loads permit storage data from the database
    2. Converts Yes/No columns to boolean values
    3. Merges with permit IDs
    4. Selects relevant columns
    5. Uploads the processed data to the PermitsStorage table

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Processing permits waste storage...")

    engine = session.bind

    data = pd.read_sql(f"SELECT * FROM raw.{m.PermitsStorageRaw.__tablename__}", engine)

    # change columns from Yes/No to boolean
    for col in data.columns:
        if col == "other_cols":
            continue
        if (
            (data[col].dtype == "object")
            & (data[col].nunique() <= 2)
            & (data[col].isin(["No", "Yes"]).all())
        ):
            data[col] = data[col].apply(lambda x: x.lower() == "yes")

    # load permits
    permits = pd.read_sql(
        f"SELECT id as permit_id FROM processed.{m.Permits.__tablename__}", engine
    )

    # merge permits with permits storage
    data = pd.merge(data, permits, left_on="id", right_on="permit_id", how="left")
    data["permit_id"] = data["permit_id"].apply(
        lambda x: np.nan if pd.isna(x) else int(x)
    )
    data["permit_id"] = data["permit_id"].astype("Int64")
    data = select_columns(data, m.PermitsStorage, other_cols=False)

    refresh_table(session, data, m.PermitsStorage)


def process_label_batches(session, update_existing=True):
    """
    Process label batch data and upload to the database.

    This function:
    1. Loads label batch data from the database
    2. Ensures tile IDs and facility IDs are properly formatted as lists
    3. Selects relevant columns
    4. Uploads the processed data to the LabelBatches table

    Args:
        session: Database session object
        update_existing (bool, optional): Whether to update existing records. Defaults to True.

    Returns:
        None
    """
    logging.info("Processing label batches...")

    engine = session.bind

    data = pd.read_sql(f"SELECT * FROM raw.{m.LabelBatchesRaw.__tablename__}", engine)

    # Ensure the qt_tile_ids and facility_ids columns are treated as lists of strings/ints
    data["naip_qt_ids"] = data["naip_qt_ids"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else x
    )
    data["facility_ids"] = data["facility_ids"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else x
    )

    data = select_columns(data, m.LabelBatches, other_cols=False)

    refresh_table(session, data, m.LabelBatches)


def process_cf_annotations(session):
    """Process annotations."""
    logging.info("Processing CF annotations and barns...")

    engine = session.bind

    data = gpd.read_postgis(
        f"SELECT * FROM raw.{m.CFAnnotationsRaw.__tablename__}",
        engine,
        geom_col="geometry",
    )

    naip_qt = gpd.read_postgis(
        f"SELECT id, geometry FROM processed.{m.Naip21QT.__tablename__}",
        engine,
        geom_col="geometry",
    )

    naip_qt_buffer = gpd.read_postgis(
        f"SELECT id, geometry_buffer FROM processed.{m.Naip21QT.__tablename__}",
        engine,
        geom_col="geometry_buffer",
    )

    # process annotations
    data.rename(columns={"geometry": "raw_coordinates"}, inplace=True)
    data["geometry_buffer"] = None
    data["geometry"] = None
    data["clipped_annotation"] = False
    data["clipped_annotation_empty"] = False
    # Transform coordinates
    logging.info("Transforming relative coordinates to geographic coordinates.")
    naip_crs = naip_qt.crs

    for i, annotation in data.iterrows():
        tile_buffer = naip_qt_buffer[naip_qt_buffer["id"] == annotation["naip_qt_id"]]

        if tile_buffer.empty:
            logging.warning(
                f"No matching NAIP tile found for tile_id: {annotation['naip_qt_id']}"
            )
            continue

        if annotation["label"] != "Blank" and annotation["type"] == "segment":
            raw_polygon = annotation["raw_coordinates"]
            tile_bounds = tile_buffer.total_bounds
            transformed_coords = transform_coordinates(raw_polygon, tile_bounds)

            transformed_polygon = Polygon(transformed_coords)

            if not transformed_polygon.is_valid:
                transformed_polygon = transformed_polygon.buffer(0)

            data.at[i, "geometry_buffer"] = transformed_polygon
        else:
            data.at[i, "geometry_buffer"] = None

    # Clip annotations to the extent of the quartered NAIP tiles
    logging.info("Clipping annotations to the extent of the quartered NAIP tiles.")
    for idx, row in data.iterrows():
        if row["geometry_buffer"] is not None:
            tile = naip_qt[naip_qt["id"] == row["naip_qt_id"]]
            if not tile.empty:
                tile_bounds = tile.total_bounds
                geom = row["geometry_buffer"]
                clipped_geom, was_clipped = clip_annotation_to_tile(geom, tile_bounds)
                data.at[idx, "geometry"] = clipped_geom if was_clipped else geom
                data.at[idx, "clipped_annotation"] = was_clipped
                # if geometry is empty, set to None
                if clipped_geom.is_empty:
                    data.at[idx, "geometry"] = None
                    data.at[idx, "clipped_annotation_empty"] = True
            else:
                logging.warning(
                    f"No matching NAIP tile found for tile_id: {row['qt_tile_id']}"
                )

    # Check what share of annotations were clipped
    n_clipped = data["clipped_annotation"].sum()
    logging.info(f"Clipped {n_clipped} out of {data.shape[0]} annotations.")

    # create barns data
    data.crs = naip_crs
    barns = data.copy()

    # only keep annotations that are not empty
    barns = data[barns.geometry.notnull()].copy()
    # merge nearby annotations into barns
    barns = merge_nearby_features(
        barns,
        grouping_columns=[],
        buffer_distance=0.5,  # overlap threshold in meters
    )

    # make sure all geometries are valid
    barns.geometry = barns.geometry.apply(
        lambda x: x.buffer(0) if not x.is_valid else x
    )

    # Generate stable IDs based on geometry
    barns["id"] = barns.apply(lambda row: stable_hash(str(row.geometry.wkt)), axis=1)

    # only keep barns that are inside Iowa state
    nrows_before = barns.shape[0]
    iowa = gpd.read_postgis(
        f"SELECT * FROM processed.{m.CensusTracts.__tablename__}",
        engine,
        geom_col="geometry",
    )

    iowa = iowa.unary_union
    barns = barns[barns.intersects(iowa)]
    logging.info(f"Removed {nrows_before - barns.shape[0]} barns outside of Iowa.")

    # only keep barns that have an area of greater than 150 m2
    nrows_before = barns.shape[0]
    barns = barns[barns.geometry.area > 150]
    logging.info(
        f"Removed {nrows_before - barns.shape[0]} barns with area less than 150 m2."
    )

    # remove barns from manual review
    manual_review_barns = pd.read_csv(
        "data/manual_review/barns_to_remove.csv", index_col=False
    )

    nrows_before = barns.shape[0]
    barns = barns[~barns["id"].isin(manual_review_barns["barn_id"])]
    logging.info(f"Removed {nrows_before - barns.shape[0]} barns from manual review.")

    # create barn clusters
    barns["barn_cluster_id"] = get_clusters(barns, 20)
    barn_clusters = barns.dissolve(by="barn_cluster_id", as_index=False)

    # Generate stable IDs for barn clusters based on geometry
    barn_clusters["id"] = barn_clusters.apply(
        lambda row: stable_hash(str(row.geometry.wkt)), axis=1
    )

    # Create mapping from old index-based IDs to new stable hash IDs
    id_mapping = dict(zip(barn_clusters["barn_cluster_id"], barn_clusters["id"]))

    # Update barn_cluster_id in barns table to use stable hash IDs
    barns["barn_cluster_id"] = barns["barn_cluster_id"].map(id_mapping)

    # add barn id column to data
    barn_map = {}
    for _, row in barns.iterrows():
        for oid in row["original_ids"]:
            barn_map[oid] = row["id"]  # Use the stable hash ID instead of the index

    data["barn_id"] = data["id"].map(barn_map)

    # convert geometries to WKT
    srid = int(data.crs.to_authority()[1])
    for df in [data, barns, barn_clusters]:
        df = convert_geometries_to_wkt(df, srid)

    # select columns
    data = select_columns(data, m.CFAnnotations, other_cols=False)
    barns = select_columns(barns, m.Barns, other_cols=False)
    barn_clusters = select_columns(barn_clusters, m.BarnClusters, other_cols=False)

    # upload data
    refresh_table(session, data, m.CFAnnotations)
    refresh_table(session, barns, m.Barns)
    refresh_table(session, barn_clusters, m.BarnClusters)


def process_barncluster_parcels(session):
    """
    Create and process associations between barn clusters and parcels.

    This function:
    1. Loads barn cluster and parcel data from the database
    2. Performs spatial joins to find intersecting parcels
    3. Incorporates manual review data
    4. Creates many-to-many associations
    5. Uploads the associations to the BarnClusterParcels table

    Args:
        session: Database session object

    Returns:
        None
    """
    logging.info("Creating Barns-Parcels associations...")
    engine = session.bind

    # Read Barn Clusters
    barn_clusters = gpd.read_postgis(
        f"SELECT id as barn_cluster_id, geometry FROM processed.{m.BarnClusters.__tablename__}",
        engine,
        geom_col="geometry",
    )

    # Read Parcels
    parcels = gpd.read_postgis(
        f"SELECT id AS parcel_id, geometry FROM processed.{m.Parcels.__tablename__}",
        engine,
        geom_col="geometry",
    )

    if barn_clusters.crs is None:
        barn_clusters.set_crs(parcels.crs, inplace=True)

    # Spatial join to find which parcels intersect which barns
    barns_join = gpd.sjoin(barn_clusters, parcels, how="left", predicate="intersects")
    barns_join.drop(columns=["index_right"], inplace=True)

    # Filter out rows where no parcel match was found
    barns_join = barns_join[barns_join["parcel_id"].notna()]

    # Create the association DataFrame
    barnclusters_parcels = barns_join[["barn_cluster_id", "parcel_id"]].copy()

    # load data from manual review
    barncluster_parcels_manual = pd.read_csv(
        "data/manual_review/barncluster-parcel-association.csv", index_col=False
    )

    # merge manual review with automatic associations
    nrows_before = barnclusters_parcels.shape[0]
    barnclusters_parcels = pd.concat(
        [barnclusters_parcels, barncluster_parcels_manual], ignore_index=True
    )
    # drop duplicates
    barnclusters_parcels.drop_duplicates(inplace=True)
    logging.info(
        f"Added {barnclusters_parcels.shape[0] - nrows_before} barncluster-parcel associations from manual review."
    )
    barnclusters_parcels["id"] = range(1, len(barnclusters_parcels) + 1)

    # Insert associations using refresh_table
    refresh_table(session, barnclusters_parcels, m.BarnClusterParcels)
    logging.info("BarnsCluster-Parcels associations created successfully.")


# Define the mapping of sources to their respective functions
SOURCE_FUNCTIONS = {
    "animal_weights": process_animal_weights,
    "urban_areas": process_urban,
    "census_tracts": process_census_tracts,
    "naip21": process_naip,
    "naip21qt": process_naip,
    "parcels": process_parcels,
    "permits": process_permits,
    "permits_storage": process_permits_storage,
    "label_batches": process_label_batches,
    "cf_annotations": process_cf_annotations,
    "barnsparcels": process_barncluster_parcels,
}


def process_source_with_dependencies(session, source, update_dependencies):
    SOURCE_FUNCTIONS[source](session=session)

    if source in DEPENDENCIES:
        if update_dependencies:
            for dep_source in DEPENDENCIES[source]:
                logging.info(
                    f"Updating dependent source: {dep_source} due to {source} update."
                )
                SOURCE_FUNCTIONS[dep_source](session=session)
        else:
            deps = ", ".join(DEPENDENCIES[source])
            logging.warning(
                f"The '{source}' table was updated. The following tables depend on '{source}': {deps}. "
                "You might want to re-run the script with --update-dependencies or process them manually."
            )


@click.command()
@click.option(
    "--data_sources",
    prompt="Data sources to process (comma-separated): animal_weights, urban_areas, census_tracts, naip21, parcels, permits, permits_storage, label_batches, cf_annotations, barnsparcels, all",
    help="Data sources to process, choose from animal_weights, urban_areas, census_tracts, naip21, parcels, permits, permits_storage, label_batches, cf_annotations, barnsparcels, or all.",
    type=str,
    required=True,
)
@click.option(
    "--update-dependencies",
    is_flag=True,
    default=True,
    help="If set, automatically update tables that depend on the processed tables.",
)
def process_data_cli(data_sources, update_dependencies):
    """
    CLI command to process data sources.
    """
    sources = [source.strip() for source in data_sources.lower().split(",")]

    if "all" in sources:
        sources = list(SOURCE_FUNCTIONS.keys())

    for source in sources:
        if source not in SOURCE_FUNCTIONS:
            click.echo(f"Invalid data source: {source}")
            continue

        click.echo(f"Processing {source}...")
        s.execute_with_session(
            lambda session: process_source_with_dependencies(
                session, source, update_dependencies
            )
        )
        click.echo(f"Finished processing {source}")


if __name__ == "__main__":
    process_data_cli()
