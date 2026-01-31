import json
import logging
import os
import re

import click
import geopandas as gpd
import pandas as pd
import requests
from geoalchemy2 import WKTElement
from shapely.geometry import Polygon

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s
from cafo_iowa.db.funs import insert_and_update, select_columns
from cafo_iowa.utils.utils import find_json_files, stable_hash

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def ingest_data(
    data,
    id,
    model,
    is_geo=False,
    to_crs="EPSG:26915",
    geom_col="geometry",
):
    """
    Ingest data into the database with optional geographic processing.

    This function:
    1. Processes geographic data if is_geo is True:
       - Converts to specified CRS
       - Formats geometry column
    2. Standardizes column names to lowercase
    3. Creates unique IDs from specified columns
    4. Removes duplicate records
    5. Selects columns matching the database model
    6. Inserts new records and updates existing ones

    Args:
        data: DataFrame or GeoDataFrame containing the data to ingest
        id: Column name(s) to use as unique identifier(s)
        model: SQLAlchemy model class for the target table
        is_geo (bool, optional): Whether the data contains geographic information. Defaults to False.
        to_crs (str, optional): Target coordinate reference system. Defaults to "EPSG:26915".
        geom_col (str, optional): Name of the geometry column. Defaults to "geometry".

    Returns:
        None
    """

    # load raw data
    if is_geo:
        # convert to common crs and format geometry column
        if to_crs is not None:
            data = data.to_crs(to_crs)
            srid = int(data.crs.to_authority()[1])
            # Check if the geometry column exists and contains valid geometries
            if geom_col in data.columns and not data[geom_col].isna().all():
                data["geometry"] = data[geom_col].apply(
                    lambda x: (
                        WKTElement(x.wkt, srid=srid)
                        if x is not None and not x.is_empty
                        else None
                    )
                )
            else:
                logging.warning(
                    f"Geometry column '{geom_col}' is missing or empty. Skipping geometry conversion."
                )
                data["geometry"] = None
        else:
            if geom_col in data.columns and not data[geom_col].isna().all():
                data["geometry"] = data[geom_col].apply(
                    lambda x: (
                        WKTElement(x.wkt) if x is not None and not x.is_empty else None
                    )
                )
            else:
                logging.warning(
                    f"Geometry column '{geom_col}' is missing or empty. Skipping geometry conversion."
                )
                data["geometry"] = None

    data.columns = data.columns.str.lower()

    # set id. If multiple columns, concatenate them, and hash the result. Else, set id to id_col
    if isinstance(id, list):
        data["id"] = data[id].apply(
            lambda row: stable_hash("_".join(row.values.astype(str))), axis=1
        )
    else:
        data["id"] = data[id]

    # make sure ids are unique, and drop duplicates
    nrow_before = data.shape[0]
    data = data.drop_duplicates(subset="id")
    if nrow_before != data.shape[0]:
        logging.warning(
            f"Dropped {nrow_before - data.shape[0]} duplicate rows from the data (i.e. same {id} columns)."
        )

    # select columns that are present in the database model
    data = select_columns(data, model)

    session = s.get_session()

    # inserts new records and updates existing records
    try:
        # Perform database operations
        insert_and_update(session, data, model)
    except Exception as e:
        session.rollback()
        logging.error(f"An error occurred: {e}")
    finally:
        session.close()


def ingest_permits():
    """
    Ingest permit data from shapefiles into the database.

    This function:
    1. Loads permit data from shapefiles in the data/permits/raw/ directory
    2. Processes the data using ingest_data with geographic information
    3. Uses facilityid as the unique identifier
    4. Uploads to the PermitsRaw table

    Returns:
        None
    """
    data = gpd.read_file("data/permits/raw/")

    ingest_data(
        data,
        id="facilityid",
        model=m.PermitsRaw,
        is_geo=True,
    )


def ingest_permits_storage():
    """
    Ingest permit storage data from Excel files into the database.

    This function:
    1. Loads permit storage data from Excel files in the data/permits/storage-structure/ directory
    2. Combines data from multiple files
    3. Standardizes column names
    4. Uses facility_id as the unique identifier
    5. Uploads to the PermitsStorageRaw table

    Returns:
        None
    """
    data = pd.DataFrame()
    for file in os.listdir("data/permits/storage-structure/"):
        if not file.endswith(".xlsx"):
            continue
        temp = pd.read_excel(
            f"data/permits/storage-structure/{file}", skiprows=2, engine="openpyxl"
        )
        data = pd.concat([data, temp], ignore_index=True)

    # change names
    data.columns = data.columns.str.lower()
    data.columns = data.columns.str.replace(" |-|,|\(|\)", "_", regex=True)
    data.columns = data.columns.str.replace("_+", "_", regex=True)

    ingest_data(
        data,
        id="facility_id",
        model=m.PermitsStorageRaw,
        is_geo=False,
    )


def ingest_naip21():
    """
    Ingest NAIP 2021 satellite imagery data into the database.

    This function:
    1. Loads NAIP tile data from shapefiles in the data/NAIP21QQ_shp/raw/ directory
    2. Creates tile IDs from filenames
    3. Processes the data using ingest_data with geographic information
    4. Uses tile_id as the unique identifier
    5. Uploads to the Naip21Raw table

    Returns:
        None
    """
    data = gpd.read_file("data/NAIP21QQ_shp/raw/")

    # make sure id is filename without extension
    data["tile_id"] = data.FileName.apply(lambda x: re.sub(r"_\d{8}.tif", "", x))

    ingest_data(
        data,
        id="tile_id",
        model=m.Naip21Raw,
        is_geo=True,
    )


def ingest_urban_areas():
    """
    Ingest urban area data into the database.

    This function:
    1. Loads urban area data from shapefiles in the data/urban_areas/raw/ directory
    2. Processes the data using ingest_data with geographic information
    3. Uses uace20 as the unique identifier
    4. Uploads to the UrbanAreasRaw table

    Returns:
        None
    """
    data = gpd.read_file("data/urban_areas/raw/")

    ingest_data(
        data,
        id="uace20",
        model=m.UrbanAreasRaw,
        is_geo=True,
    )


def ingest_census_tracts():
    """
    Ingest census tract data and population information into the database.

    This function:
    1. Loads census tract data from shapefiles in the data/census/ directory
    2. Fetches population data from the Census API
    3. Merges population data with census tracts
    4. Processes the data using ingest_data with geographic information
    5. Uses GEOID as the unique identifier
    6. Uploads to the CensusTractsRaw table

    Returns:
        None
    """
    # load census data
    data = gpd.read_file("data/census/")
    data["id"] = data["GEOID"]

    # Load population data at tract level
    BASE_URL = "https://api.census.gov/data/2020/dec/pl"

    params = {
        "get": "P1_001N,NAME",
        "for": "tract:*",
        "in": "state:19",  # FIPS code for Iowa
        "key": os.getenv("CENSUS_API_KEY"),
    }

    response = requests.get(BASE_URL, params=params)
    data_pop = response.json()
    data_pop = pd.DataFrame(data_pop[1:], columns=data_pop[0])
    data_pop.rename(
        columns={
            "P1_001N": "population",
        },
        inplace=True,
    )
    data_pop["county_name"] = data_pop["NAME"].apply(lambda x: x.split(", ")[1])
    data_pop["population"] = data_pop["population"].astype(int)
    data_pop["GEOID"] = data_pop["state"] + data_pop["county"] + data_pop["tract"]
    data_pop = data_pop[["GEOID", "population", "county_name"]]

    # Merge population data with census tracts, by tract
    data = data.merge(data_pop)

    # Ingest data
    ingest_data(
        data,
        id="id",
        model=m.CensusTractsRaw,  # Ensure model name matches your DB schema
        is_geo=True,
    )


def ingest_parcels():
    """
    Ingest parcel data from multiple county shapefiles into the database.

    This function:
    1. Loads parcel data from shapefiles in the data/parcels/raw/ directory
    2. Combines data from multiple county files
    3. Standardizes column names
    4. Adds county information
    5. Processes the data using ingest_data with geographic information
    6. Uses a combination of parcelnumb, owner, and geometry as the unique identifier
    7. Uploads to the ParcelsRaw table

    Returns:
        None
    """
    data = gpd.GeoDataFrame()
    for root, _, files in os.walk("data/parcels/raw/"):
        for file in files:
            if not file.endswith(".shp"):
                continue
            county = file.split(".")[0]
            county_data = gpd.read_file(os.path.join(root, file))

            # Skip empty DataFrames
            if county_data.empty:
                logging.info(f"Skipping empty file: {os.path.join(root, file)}")
                continue

            county_data.columns = county_data.columns.str.lower()
            county_data["county"] = county

            # If data is empty, initialize it with county_data
            if data.empty:
                data = county_data
            else:
                # Ensure both DataFrames have the same columns before concatenation
                common_columns = list(
                    set(data.columns) & set(county_data.columns)
                )  # Ensure no duplicate columns
                common_columns = list(
                    dict.fromkeys(common_columns)
                )  # preserves order, removes duplicates

                data = pd.concat(
                    [data[common_columns], county_data[common_columns]],
                    ignore_index=True,
                )

    ingest_data(
        data,
        id=["parcelnumb", "owner", "geometry"],
        model=m.ParcelsRaw,
        is_geo=True,
    )


def ingest_label_batches():
    """
    Ingest label batch data from CSV into the database.

    This function:
    1. Loads label batch data from data/labeling/batches.csv
    2. Converts string representations of lists to actual lists
    3. Processes the data using ingest_data
    4. Uses batch_nr as the unique identifier
    5. Uploads to the LabelBatchesRaw table

    Returns:
        None
    """
    data = pd.read_csv("data/labeling/batches.csv")

    # Ensure qt_tile_ids and facility_ids are lists
    data["naip_qt_ids"] = data["qt_tile_ids"].apply(
        lambda x: json.loads(x.replace("'", '"'))
    )
    data["facility_ids"] = data["facility_ids"].apply(
        lambda x: json.loads(x.replace("'", '"'))
    )
    data["batch_metadata"] = data["batch_metadata"].apply(
        lambda x: json.loads(x.replace("'", '"'))
    )

    # conver back to list
    ingest_data(
        data,
        id="batch_nr",
        is_geo=False,
        model=m.LabelBatchesRaw,
    )


def ingest_cf_annotations():
    """
    Ingest crowdflower annotations from JSON files into the database.

    This function:
    1. Loads annotation data from JSON files in the data/annotations directory
    2. Extracts metadata and annotation details
    3. Converts coordinates to polygon geometries
    4. Processes the data using ingest_data with geographic information
    5. Uses id as the unique identifier
    6. Uploads to the CFAnnotationsRaw table

    Returns:
        None
    """
    data = []
    for file in find_json_files("data/annotations"):
        with open(file, "r") as f:
            temp_json = json.load(f)

        # extract metadata
        batch_name = file.split("/")[2]
        temp = pd.json_normalize(temp_json)
        qt_tile_id = temp.name.str.split(".jpeg").str[0][0]
        n_annotations = temp.annotationsCount.values[0]
        data_annotations = pd.json_normalize(temp_json["annotations"])

        if data_annotations.shape[0] != n_annotations:
            raise ValueError(
                f"Expected {n_annotations} annotations, but found {len(data_annotations)}"
            )
        # add metadata to each annotation
        data_annotations["naip_qt_id"] = qt_tile_id
        data_annotations["naip_id"] = re.sub(r"_(TL|TR|BL|BR)$", "", qt_tile_id)
        data_annotations["n_annotations"] = n_annotations
        data_annotations["batch_name"] = batch_name

        data.append(data_annotations)

    data = pd.concat(data, ignore_index=True)

    # convert coordinates into polygon
    data["geometry"] = None
    for i, annotation in data.iterrows():
        if annotation["label"] != "Blank" and annotation["type"] == "segment":
            data.at[i, "geometry"] = Polygon(
                [(coord["x"], coord["y"]) for coord in annotation["coordinates"][0]]
            )

    ingest_data(
        data,
        id="id",
        is_geo=True,
        to_crs=None,
        model=m.CFAnnotationsRaw,
    )


# Define the mapping of sources to their respective functions
SOURCE_FUNCTIONS = {
    "parcels": ingest_parcels,
    "permits": ingest_permits,
    "permits_storage": ingest_permits_storage,
    "naip21": ingest_naip21,
    "urban_areas": ingest_urban_areas,
    "census_tracts": ingest_census_tracts,
    "label_batches": ingest_label_batches,
    "cf_annotations": ingest_cf_annotations,
}


@click.command()
@click.option(
    "--data_sources",
    prompt="Data sources to ingest (comma-separated): parcels, permits, permits_storage, naip21, urban_areas, census_tracts, label_batches, cf_annotations, all",
    help="Data sources to ingest, choose from parcels, permits, permits_storage, naip21, urban_areas, census_tracts, label_batches, cf_annotations, or all.",
    type=str,
    required=True,
)
def ingest_data_cli(data_sources):

    sources = [source.strip() for source in data_sources.lower().split(",")]

    if "all" in sources:
        sources = list(SOURCE_FUNCTIONS.keys())

    for source in sources:
        if source not in SOURCE_FUNCTIONS:
            click.echo(f"Invalid data source: {source}")
            continue

        click.echo(f"Ingesting {source}...")
        SOURCE_FUNCTIONS[source]()
        click.echo(f"Finished ingesting {source}")


if __name__ == "__main__":
    ingest_data_cli()
