#get_facilities_data.py
"""
This file contains functions that create some of the facilities data.
"""
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads

import cafo_iowa.db.session as s

pd.set_option("display.max_columns", None)

CATEGORY_MAP = {
    "swine": [
        "swine_gest",
        "swine_sow",
        "swine_nurs",
        "swine_grow",
        "swine_wean",
        "swine_gilt",
    ],
    "cattle": [
        "cattle_bee",
        "cattle_b_1",
        "immature_d",
        "mature_dai",
        "cattle_dai",
        "cattle_vea",
        "cow_calf",
    ],
    "poultry": ["chicken_la", "chicken_pu", "turkey_fin", "turkey_pou", "ducks"],
    "other": ["fish___25", "fish_____2", "goats", "horses", "sheep_and"],
}


def calculate_total_area(geoms, utm_crs):
    """
    Calculate total area in sqm for valid geometries.
    s"""
    if geoms:
        valid_geoms = [geom for geom in geoms if geom and not geom.is_empty]
        if valid_geoms:
            gdf = gpd.GeoSeries(valid_geoms, crs=utm_crs)
            return gdf.to_crs(utm_crs).area.sum()
    return 0


def classify_animals(row, category_map=CATEGORY_MAP):
    """
    Classify *all* animal columns (across all categories) that have > 0 in `row`.
    Returns a comma-separated list of active columns, or None if none.

    Example outputs:
      - "swine_gest, swine_wean, cattle_bee"
      - None
    """
    # Flatten all category_map columns into one list
    all_animal_cols = [col for cols in category_map.values() for col in cols]

    # Filter for columns > 0
    active_columns = [col for col in all_animal_cols if row.get(col, 0) > 0]

    if not active_columns:
        return None  # or "no_animals", depending on your preference

    # Return them as a comma-separated, sorted string
    return ", ".join(sorted(active_columns))


def classify_animals_combined(row, category_map=CATEGORY_MAP):
    """
    Classify animals into a single category or 'two_or_more_categories' if
    multiple top-level categories are present. Returns None if none.

    Example outputs:
      - "swine"
      - "cattle"
      - "two_or_more_categories"
      - None
    """
    active_categories = []
    for category, animal_types in category_map.items():
        # If any of these columns is > 0, we consider that category active
        if any(row.get(a_type, 0) > 0 for a_type in animal_types):
            active_categories.append(category)

    if not active_categories:
        return None

    if len(active_categories) > 1:
        return "two_or_more_categories"

    return active_categories[0]


def classify_swines(row, category_map=CATEGORY_MAP):
    """
    Classify *all* active swine columns that are > 0 in `row`.
    Returns a comma-separated list, or None if none are active.

    Example outputs:
      - "swine_gest, swine_wean"
      - None
    """
    swine_types = category_map.get("swine", [])
    active_swine_types = [t for t in swine_types if row.get(t, 0) > 0]

    if not active_swine_types:
        return None  # or "no_swine_types"

    # Return them as a comma-separated, sorted string
    return ", ".join(sorted(active_swine_types))


def classify_swines_combined(row, category_map=CATEGORY_MAP):
    """
    Classify swine animals in a row. Possible outcomes:
      - None, if no swine columns are active
      - "two_or_more_types" if more than one swine column is active (and no non-swine active)
      - the single swine column name if exactly one swine column is active (and no non-swine active)
      - "swine_and_other" if there are one or more active swine columns PLUS at least one active non-swine column

    Example outputs:
      - "swine_gest"
      - "two_or_more_types"
      - "swine_and_other"
      - None
    """

    # 1) Determine which swine types are > 0
    swine_types = category_map.get("swine", [])
    active_swine_types = [t for t in swine_types if row.get(t, 0) > 0]

    # 2) Determine which NON-swine types are > 0
    #    Flatten every category except 'swine'
    non_swine_cols = [
        c for cat, cols in category_map.items() if cat != "swine" for c in cols
    ]
    active_non_swine = [col for col in non_swine_cols if row.get(col, 0) > 0]

    # 3) If no swine columns are active, return None
    if not active_swine_types:
        return None

    # 4) Check if there's at least one non-swine active
    if len(active_non_swine) > 0:
        # We have at least one swine + at least one non-swine
        return "swine_and_other_animal"

    # 5) If we only have swine columns, see if there's more than one
    if len(active_swine_types) > 1:
        return "two_or_more_swine_types"
    elif len(active_swine_types) == 1:
        # Exactly one swine column is active
        return active_swine_types[0]
    else:
        return None


def gather_animal_units_dict(row, category_map=CATEGORY_MAP):
    """
    Returns a dictionary of {animal_col: value} for all columns that have > 0 in `row`.
    If none are > 0, return None (or an empty dict, depending on your preference).
    """
    all_animal_cols = [col for cols in category_map.values() for col in cols]

    result = {}
    for col in all_animal_cols:
        val = row.get(col, 0)
        if val > 0:
            result[col] = val
    return result if result else None


def get_facilities(match_barns_to_empty_facilities=True, buffer_size=100):
    """
    Retrieve facilities data from the database.

    Parameters:
    -----------
    match_barns_to_empty_facilities : bool, optional
        Whether to match barns to empty facilities, by default True
    buffer_size : int, optional
        Buffer size for matching barns to facilities, by default 100

    Returns:
    --------
    geopandas.GeoDataFrame
        A GeoDataFrame containing facilities data
    """
    # select the closest non-empty facility for each permit
    query = """
    WITH aggregated_barns AS (
        SELECT
            f.facility_id,
            COALESCE(SUM(ST_Area(b.geometry)), 0) AS barn_sqm,  -- Calculate barn area in square meters
            COALESCE(ARRAY_AGG(ST_AsText(b.geometry)), ARRAY[]::text[]) AS barn_geoms,  -- Convert to WKT for proper serialization
            COUNT(b.id) AS barn_count,  -- Count of barns for each facility
            COALESCE(ARRAY_AGG(b.id::text), ARRAY[]::text[]) AS barn_ids,  -- Collect barn ids as an array
            COALESCE(ARRAY_AGG(DISTINCT b.barn_cluster_id::text), ARRAY[]::text[]) AS barn_cluster_ids,
            COUNT(DISTINCT b.barn_cluster_id) AS barn_cluster_count,
            COALESCE(ARRAY_AGG(DISTINCT ST_AsText(bc.geometry)), ARRAY[]::text[]) AS barn_cluster_geometries
        FROM processed.facilities f
        LEFT JOIN processed.barns b ON f.facility_id = b.facility_id
        LEFT JOIN processed.barnclusters bc ON b.barn_cluster_id = bc.id
        GROUP BY f.facility_id
    ),
    aggregated_parcels AS (
        SELECT
            f.facility_id,
            COUNT(DISTINCT pa.id) AS parcel_count,  -- Count of unique parcels
            COALESCE(ARRAY_AGG(p_raw.id::text), ARRAY[]::text[]) AS parcel_ids,  -- Collect parcel ids as an array
            COALESCE(ARRAY_AGG(DISTINCT p_raw.owner), ARRAY[]::text[]) AS parcel_owners,  -- Collect parcel owners
            COALESCE(ARRAY_AGG(DISTINCT ST_AsText(p_raw.geometry)), ARRAY[]::text[]) AS parcel_geometries  -- Collect parcel geometries
        FROM processed.facilities f
        LEFT JOIN processed.parcels pa ON f.facility_id = pa.facility_id
        LEFT JOIN raw.parcels p_raw ON p_raw.id = ANY(pa.original_ids)
        GROUP BY f.facility_id
    ),
    waste_management AS (
        SELECT
            ps.permit_id,
            CASE
                WHEN ps.lagoon_anaerobic = TRUE THEN 'anaerobic_storage'
                WHEN ps.below_buildings_pits = TRUE OR ps.below_buildings_pits_deep = TRUE OR ps.below_buildings_pit_shallow = TRUE THEN 'pit_storage'
                WHEN ps.slurry_store = TRUE OR ps.outside_formed_concrete = TRUE THEN 'slurry_storage'
                ELSE 'other'
            END AS permit_wms_category
        FROM processed.permits_storage ps
    ),
    ranked_permits AS (
        SELECT
            p.permit_id,
            p.facility_id,
            f.geometry AS facility_geom,
            ROW_NUMBER() OVER (
                PARTITION BY p.permit_id
                ORDER BY
                    CASE WHEN p.is_empty THEN 1 ELSE 0 END,  -- non-empty first
                    p.rn  -- then by distance
            ) AS rank
        FROM processed.facilities_near_permits p
        JOIN processed.facilities f ON p.facility_id = f.facility_id
    )
    SELECT
        -- Facility information
        ranked.facility_id,
        ranked.facility_geom,

        -- Permit information
        p.id AS permit_id,
        ST_AsText(p.geometry) AS permit_geom,
        p.facilityna,
        p.address,
        p.animal_units,
        p.swine_animal_units,
        p.cattle_bee,
        p.cattle_b_1,
        p.immature_d,
        p.mature_dai,
        p.cattle_dai,
        p.cattle_vea,
        p.chicken_la,
        p.chicken_pu,
        p.cow_calf,
        p.ducks,
        p.fish___25,
        p.fish_____2,
        p.goats,
        p.horses,
        p.turkey_fin,
        p.turkey_pou,
        p.sheep_and,
        p.swine_gest,
        p.swine_gilt,
        p.swine_grow,
        p.swine_nurs,
        p.swine_sow,
        p.swine_wean,

        -- Waste management information
        wm.permit_wms_category,

        -- Aggregated barn information
        ab.barn_count,
        ab.barn_ids,
        ab.barn_sqm,
        ab.barn_geoms,
        ab.barn_cluster_ids,
        ab.barn_cluster_count,
        ab.barn_cluster_geometries,

        -- Aggregated parcel information
        ap.parcel_count,
        ap.parcel_ids,
        ap.parcel_owners,
        ap.parcel_geometries
    FROM ranked_permits ranked
    JOIN processed.permits p ON ranked.permit_id = p.id
    LEFT JOIN waste_management wm ON p.id = wm.permit_id
    LEFT JOIN aggregated_barns ab ON ranked.facility_id = ab.facility_id
    LEFT JOIN aggregated_parcels ap ON ranked.facility_id = ap.facility_id
    WHERE ranked.rank = 1;
    """

    permits_with_facilities = gpd.read_postgis(
        query, s.get_engine(), geom_col="facility_geom"
    )

    # Group by facility_id to get unique facilities
    facilities = (
        permits_with_facilities.groupby(["facility_id", "facility_geom"])
        .agg(
            {
                "permit_id": lambda x: list(x),
                "permit_geom": lambda x: list(x),
                "facilityna": lambda x: ", ".join(filter(None, x)),  # permit_names
                "address": lambda x: ", ".join(filter(None, x)),  # permit_addresses
                "animal_units": lambda x: sum(filter(None, x)),  # reported_animal_units
                "swine_animal_units": lambda x: sum(
                    filter(None, x)
                ),  # reported_swine_animal_units
                "cattle_bee": lambda x: sum(filter(None, x)),
                "cattle_b_1": lambda x: sum(filter(None, x)),
                "immature_d": lambda x: sum(filter(None, x)),
                "mature_dai": lambda x: sum(filter(None, x)),
                "cattle_dai": lambda x: sum(filter(None, x)),
                "cattle_vea": lambda x: sum(filter(None, x)),
                "chicken_la": lambda x: sum(filter(None, x)),
                "chicken_pu": lambda x: sum(filter(None, x)),
                "cow_calf": lambda x: sum(filter(None, x)),
                "ducks": lambda x: sum(filter(None, x)),
                "fish___25": lambda x: sum(filter(None, x)),
                "fish_____2": lambda x: sum(filter(None, x)),
                "goats": lambda x: sum(filter(None, x)),
                "horses": lambda x: sum(filter(None, x)),
                "turkey_fin": lambda x: sum(filter(None, x)),
                "turkey_pou": lambda x: sum(filter(None, x)),
                "sheep_and": lambda x: sum(filter(None, x)),
                "swine_gest": lambda x: sum(filter(None, x)),
                "swine_gilt": lambda x: sum(filter(None, x)),
                "swine_grow": lambda x: sum(filter(None, x)),
                "swine_nurs": lambda x: sum(filter(None, x)),
                "swine_sow": lambda x: sum(filter(None, x)),
                "swine_wean": lambda x: sum(filter(None, x)),
                "permit_wms_category": lambda x: list(x),
                "barn_count": "first",
                "barn_ids": "first",
                "barn_sqm": "first",
                "barn_geoms": "first",
                "barn_cluster_ids": "first",
                "barn_cluster_count": "first",
                "barn_cluster_geometries": "first",
                "parcel_count": "first",
                "parcel_ids": "first",
                "parcel_owners": "first",
                "parcel_geometries": "first",
            }
        )
        .reset_index()
    )

    # Rename columns that were aggregated
    facilities = facilities.rename(
        columns={
            "permit_id": "permit_ids",
            "permit_geom": "permit_geoms",
            "facilityna": "permit_names",
            "address": "permit_addresses",
            "animal_units": "reported_animal_units",
            "swine_animal_units": "reported_swine_animal_units",
        }
    )

    # Add permit count
    facilities["permit_count"] = facilities["permit_ids"].apply(len)

    # Determine permit_wms_type based on categories
    facilities["permit_wms_type"] = facilities["permit_wms_category"].apply(
        lambda x: (
            "anaerobic_storage"
            if "anaerobic_storage" in x
            else (
                "pit_storage"
                if "pit_storage" in x
                else "slurry_storage" if "slurry_storage" in x else "other/unknown"
            )
        )
    )

    # Convert to GeoDataFrame before estimating UTM CRS
    facilities = gpd.GeoDataFrame(facilities, geometry="facility_geom")

    # Pre-calculate the UTM CRS for the entire dataset
    utm_crs = facilities.estimate_utm_crs()

    # Convert WKT geometries back to shapely objects
    facilities.loc[:, "barn_geoms"] = facilities["barn_geoms"].apply(
        lambda wkt_list: [loads(wkt) for wkt in wkt_list] if wkt_list else []
    )

    # Calculate total annotation area for each facility
    facilities.loc[:, "barn_area_sqm"] = facilities["barn_geoms"].apply(
        lambda geoms: calculate_total_area(geoms, utm_crs)
    )

    # Get animal categories
    facilities.loc[:, "animal_cat"] = facilities.apply(classify_animals, axis=1)
    facilities.loc[:, "animal_cat_combined"] = facilities.apply(
        classify_animals_combined, axis=1
    )

    # Classify specific swine categories
    facilities.loc[:, "swine_cat"] = facilities.apply(classify_swines, axis=1)
    facilities.loc[:, "swine_cat_combined"] = facilities.apply(
        classify_swines_combined, axis=1
    )

    # Save animal units in dict
    facilities["reported_animal_units_dict"] = facilities.apply(
        gather_animal_units_dict, axis=1
    )

    # Print summary statistics
    total_facilities = len(facilities)
    empty_facilities = len(facilities[facilities["barn_count"] == 0])
    print(f"\nFacility Summary:")
    print(f"Total facilities: {total_facilities}")
    print(f"Empty facilities: {empty_facilities}")
    print(f"Facilities with barns: {total_facilities - empty_facilities}")

    return facilities


if __name__ == "__main__":
    # Example usage
    facilities = get_facilities()
    print(f"Retrieved {len(facilities)} facilities")
