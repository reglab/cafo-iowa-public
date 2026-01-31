import logging
import os
from typing import List

import click
import ee
import geopandas as gpd
import yaml
from google.cloud import storage

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s


def initializeEE() -> None:
    """
    Initializes Google Earth Engine.

    This function initializes the Google Earth Engine library. If the initialization fails, it runs the authentication process and prompts the user to rerun the program after authentication.

    Returns:
        None
    """
    logging.info("Initializing Google Earth Engine.")
    try:
        ee.Initialize()
    except ee.EEException:
        logging.warning(
            "Earth Engine initialization failed. Running authentication instead. After authentication, rerun program."
        )
        ee.Authenticate()
        return


def exportTilestoGCPfromId(
    tile_ids: List[str],
    client: str,
    gc_bucket: str,
    gc_folder: str,
    image_dataset: str,
    image_scale: int = 1,
    redownload: bool = False,
    max_pixels: int = 1e13,
    file_format: str = "GeoTIFF",
) -> None:
    """
    Export tiles to Google Cloud Platform (GCP) from their IDs.

    Args:
        tile_ids (List[str]): List of tile IDs to export.
        client (str): Google Cloud Storage client.
        gc_bucket (str): Google Cloud Storage bucket.
        gc_folder (str): Google Cloud Storage folder.
        image_dataset (str): Earth Engine image dataset.
        image_scale (int, optional): Scale of the exported image. Defaults to 1.
        redownload (bool, optional): Flag to indicate whether to redownload existing files. Defaults to False.
        max_pixels (int, optional): Maximum number of pixels in the exported image. Defaults to 1e13.
        file_format (str, optional): File format of the exported image. Defaults to "GeoTIFF".

    Returns:
        None
    """
    initializeEE()
    client = storage.Client(client)
    bucket = client.get_bucket(gc_bucket)
    existing_files = set(
        blob.name.split("/")[-1] for blob in bucket.list_blobs(prefix=gc_folder)
    )
    if not redownload:
        remaining_tiles = [
            tile_id for tile_id in tile_ids if tile_id + ".tif" not in existing_files
        ]
        logging.info(
            f"Found {len(existing_files)} existing files in {gc_folder}. {len(remaining_tiles)} remaining."
        )
    else:
        remaining_tiles = tile_ids
    if len(remaining_tiles) == 0:
        logging.info("All tiles have been downloaded. Exiting.")
        return
    already_downloading = []
    for tile in remaining_tiles:
        if (tile + ".tif") in existing_files and not redownload:
            logging.info(f"Tile {tile} already downloaded to {gc_folder}. Skipping.")
            continue
        if tile in already_downloading:
            logging.info(f"Tile {tile} is already being downloaded. Skipping.")
            continue
        image = ee.Image(f"{image_dataset}/{tile}")
        try:
            image.getInfo()
        except ee.EEException:
            logging.info(f"Image {tile} does not exist in {image_dataset}. Skipping.")
            continue
        file_path = os.path.join(gc_folder, tile)
        task_config = {
            "fileNamePrefix": file_path,
            "scale": image_scale,
            "bucket": gc_bucket,
            "fileFormat": file_format,
            "maxPixels": max_pixels,
        }
        logging.info(f"Exporting {tile} to {file_path}.")
        task = ee.batch.Export.image.toCloudStorage(image, **task_config)
        task.start()
        already_downloading.append(tile)
        logging.info(f"Exporting {tile} to {file_path}.")
        logging.info("Task Uploaded. Status Details: \n", task.status())


def main(config_path="cafo_iowa/data/cfg/config.yaml", session=None):
    """
    Main function for ingesting NAIP satellite imagery from Google Earth Engine to Google Cloud Storage.

    This function:
    1. Loads configuration from the specified config file
    2. Retrieves NAIP tile IDs from the database
    3. Exports tiles from Earth Engine to Google Cloud Storage
    4. Handles authentication and error cases

    Args:
        config_path (str, optional): Path to the configuration file. Defaults to "cafo_iowa/data/cfg/config.yaml".
        session: Database session object. If None, a new session will be created.

    Returns:
        None
    """

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    if session is None:
        session = s.get_session()

    engine = session.bind

    naip = gpd.read_postgis(
        f"SELECT * FROM processed.{m.Naip21.__tablename__}",
        engine,
        geom_col="geometry",
    )
    session.close()

    tile_ids = naip.id.tolist()

    exportTilestoGCPfromId(
        tile_ids,
        client=config["gcs"]["client"],
        gc_bucket=config["gcs"]["gc_bucket"],
        gc_folder=os.path.join(
            config["gcs"]["gc_folder_prefix"], config["naip_imgs"]["paths"]["raw"]
        ),
        image_dataset=config["ee"]["image_dataset"],
        image_scale=config["ee"]["image_scale"],
        redownload=config["ee"]["redownload"],
        max_pixels=config["ee"]["max_pixels"],
        file_format=config["ee"]["file_format"],
    )


@click.command()
@click.option(
    "--config_path",
    type=str,
    default="cafo_iowa/data/cfg/config.yaml",
    help="Path to the configuration file.",
)
@click.option("--session", type=str, required=False, help="SQLAlchemy session object.")
def main_cli(
    config_path,
    session,
):
    main(config_path, session)


if __name__ == "__main__":
    main_cli()
