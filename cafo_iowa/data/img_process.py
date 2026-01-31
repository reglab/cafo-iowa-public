import logging
import os
from datetime import datetime

import yaml
from munch import munchify
from sqlalchemy import text

import cafo_iowa.db.session as s
from cafo_iowa.data.helpers.gcs import download_from_cloud, upload_to_cloud
from cafo_iowa.data.helpers.imgs import (
    convert_tifs_to_jpegs,
    crop_naip,
    mask_urban_areas,
)
from cafo_iowa.utils.utils import check_config_version, is_remote


def process_imgs(config_filepath="./cafo_iowa/data/cfg/config.yaml", session=None):
    """
    Process NAIP satellite imagery through a pipeline of operations including downloading, cropping, quartering,
    masking urban areas, and converting to different formats.

    This function handles the complete image processing pipeline:
    1. Downloads raw NAIP tiles from Google Cloud Storage
    2. Crops tiles to their exact boundaries
    3. Quarters tiles into smaller sections
    4. Applies buffers to quartered tiles
    5. Masks urban areas if configured
    6. Converts tiles to JPEG format
    7. Uploads processed tiles back to Google Cloud Storage

    Args:
        config_filepath (str, optional): Path to the configuration file. Defaults to "./cafo_iowa/data/cfg/config.yaml".
        session: Database session object. If None, a new session will be created.

    Returns:
        None
    """

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    with open(config_filepath, "r") as file:
        config = munchify(yaml.safe_load(file))

    if session is None:
        session = s.get_session()

    engine = session.bind

    # log start time
    logging.info(f"starting image processing pipeline")

    # check server and config version
    check_config_version(config.config_version)

    logging.info(
        f"Running process_imgs in {config.config_version} mode on {'remote' if is_remote() else 'local'} server."
    )

    # specify the path to the service account key
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = config.gcs.service_account_path

    # if in dev mode, select subset of tiles
    if config.config_version == "dev":
        logging.info("Subsetting images to 10 tiles for development")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT tile_id FROM processed.naip21 LIMIT 10"))
            tile_ids = result.fetchall()

    # download raw tiles from gcs
    download_from_cloud(
        client=config.gcs.client,
        gc_bucket=config.gcs.gc_bucket,
        gc_folder_prefix=config.gcs.gc_folder_prefix,
        local_folder=config.naip_imgs.paths.raw,
        tile_ids=tile_ids if config.config_version == "dev" else None,
        redownload=False,
    )

    # crop and quarter tiles
    for tile_path in ["cropped", "quartered", "quartered_buffer"]:

        # crop or quarter tiles
        crop_naip(
            in_path=config.naip_imgs.paths.raw,
            out_path=config.naip_imgs.paths[tile_path],
            quarter=True if "quarter" in tile_path else False,
            buffer=True if "buffer" in tile_path else False,
            n_cpu=config.n_cpu,
            session=session,
            regenerate=False or config.rerun,
        )

        # mask urban areas
        if config.naip_imgs.mask_urban_areas:

            mask_urban_areas(
                in_path=config.naip_imgs.paths[tile_path],
                n_cpu=config.n_cpu,
                regenerate=False or config.rerun,
            )

        # convert tifs to jpegs and save in jpegs subfolder
        convert_tifs_to_jpegs(
            input_path=config.naip_imgs.paths[tile_path],
            band_mode=config.naip_imgs.jpeg_bands,
            rerun=False or config.rerun,
        )

        # upload tile folders (both tifs and jpegs) to gcs
        for img_files in ["tifs", "jpegs"]:

            local_folder = config.naip_imgs.paths[tile_path].replace("tifs", img_files)

            upload_to_cloud(
                client=config.gcs.client,
                gc_bucket=config.gcs.gc_bucket,
                local_folder=local_folder,
                gc_folder_prefix=config.gcs.gc_folder_prefix,
                tile_ids=tile_ids if config.config_version == "dev" else None,
                file_suffix=".tif" if img_files == "tifs" else ".jpeg",
                reupload=False or config.rerun,
            )

    # log end time
    end_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logging.info(f"get_data completed at: {end_time}")


if __name__ == "__main__":
    process_imgs()
