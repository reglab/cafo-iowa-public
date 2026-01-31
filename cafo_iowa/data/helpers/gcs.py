import logging
import os
import re

import click
import yaml
from google.cloud import storage
from google.cloud.storage.blob import Blob
from tqdm import tqdm


def copy_blob(
    source_bucket_name, source_blob_name, destination_bucket_name, destination_blob_name
):
    """Copies a blob from one bucket to another with a new name."""

    client = storage.Client()
    source_bucket = client.get_bucket(source_bucket_name)
    source_blob = source_bucket.blob(source_blob_name)
    destination_bucket = client.get_bucket(destination_bucket_name)
    source_bucket.copy_blob(source_blob, destination_bucket, destination_blob_name)


def create_subset(
    source_bucket: str,
    source_folder: str,
    destination_bucket: str,
    destination_folder: str,
    image_names: str,
):
    """
    Copies a subset of images from a source bucket to a destination bucket.

    Args:
        source_bucket (str): The name of the source bucket.
        source_folder (str): The folder path within the source bucket.
        destination_bucket (str): The name of the destination bucket.
        destination_folder (str): The folder path within the destination bucket.
        image_names (str): A list of image names to be copied.

    Returns:
        None
    """
    for image in tqdm(image_names):

        # remove trailing slash
        source_folder = source_folder.strip("/")
        destination_folder = destination_folder.strip("/")

        copy_blob(
            source_bucket,
            f"{source_folder}/{image}",
            destination_bucket,
            f"{destination_folder}/{image}",
        )


def list_files_in_cloud(gc_bucket, gc_folder, suffix=".tif"):
    """
    Lists files in a cloud storage bucket with a given folder and suffix.

    Parameters:
    - gc_bucket (google.cloud.storage.bucket.Bucket): The cloud storage bucket object.
    - gc_folder (str): The folder path within the bucket.
    - suffix (str, optional): The file suffix to filter the files. Defaults to ".tif".

    Returns:
    - list: A list of file names in the specified folder with the given suffix.
    """

    # get list of files
    files_list = gc_bucket.list_blobs(prefix=gc_folder)
    files_list = [
        file.name.split("/")[-1] for file in files_list if file.name.endswith(suffix)
    ]

    return files_list


def file_exists(gc_bucket, gc_folder, file_name):
    """
    Checks if a file with the given name exists in the specified Google Cloud Storage bucket and folder.

    Args:
        gc_bucket (str): The name of the Google Cloud Storage bucket.
        gc_folder (str): The name of the folder within the bucket.
        file_name (str): The name of the file to check for.

    Returns:
        bool: True if the file exists, False otherwise.
    """
    storage_client = storage.Client()
    bucket = storage_client.get_bucket(gc_bucket)
    blobs = bucket.list_blobs(prefix=gc_folder)
    for blob in blobs:
        if file_name in blob.name:
            return True
    return False


def upload_to_cloud(
    client,
    gc_bucket,
    local_folder,
    gc_folder_prefix,
    tile_ids=None,
    file_suffix=".tif",
    reupload=False,
):
    """
    Uploads all files from a local directory to a specified folder in a Google Cloud Storage bucket.

    Args:
        client (str): The client ID for the Google Cloud Storage.
        gc_bucket (google.cloud.storage.bucket.Bucket): The Google Cloud Storage bucket object.
        local_folder (str): The path to the local directory containing the files to be uploaded.
        gc_folder_prefix (str): The name of the folder in the Google Cloud Storage bucket where the files will be uploaded.
        tile_ids (list, optional): A list of tile IDs to upload. If None, all files in the folder will be uploaded. Defaults to None.
        reupload (bool, optional): If True, reuploads files that already exist in the cloud. Defaults to False.
    """

    # Set up Google Cloud Storage client
    client = storage.Client(client)
    gc_bucket = client.get_bucket(gc_bucket)
    gc_folder = os.path.join(gc_folder_prefix, local_folder)

    if reupload:
        logging.info("Reupload flag set. Uploading all files.")
        to_be_uploaded = os.listdir(local_folder)
    else:
        cloud_files = list_files_in_cloud(gc_bucket, gc_folder, file_suffix)
        local_files = os.listdir(local_folder)

        # If tile_ids is provided, only upload local files with names that match the tile_ids
        if tile_ids:
            local_files = [
                a_file
                for a_file in local_files
                if re.sub(r"(_TL|_BL|_TR|_BR).*", "", a_file) in tile_ids
            ]

        to_be_uploaded = [a_file for a_file in local_files if a_file not in cloud_files]

        logging.info(
            f"Uploading {len(to_be_uploaded)} leftover files from {local_folder} to {gc_folder}"
        )

    for a_file in tqdm(to_be_uploaded):
        blob_name = os.path.join(gc_folder, a_file)
        blob = Blob(blob_name, gc_bucket)
        blob.upload_from_filename(os.path.join(local_folder, a_file))

    logging.info("All files uploaded.")
    return


def download_single_img(tile_id, config_filepath="cafo_iowa/data/cfg/config.yaml"):
    """
    Downloads an image from Google Cloud Storage (GCP) based on the provided tile ID.

    Args:
        tile_id (str): The ID of the tile to download.
        config_filepath (str, optional): The filepath to the configuration file. Defaults to "cafo_iowa/data/cfg/config.yaml".

    Returns:
        str: The filepath of the downloaded image.
    """

    with open(config_filepath, "r") as f:
        config = yaml.safe_load(f)

    client = config["gcs"]["client"]
    gc_bucket = config["gcs"]["gc_bucket"]
    gc_folder_prefix = config["gcs"]["gc_folder_prefix"]
    if any(suffix in tile_id for suffix in ["BL", "BR", "TL", "TR"]):
        img_path = config["naip_imgs"]["paths"]["quartered_buffer"]
    else:
        img_path = config["naip_imgs"]["paths"]["raw"]

    image_path = os.path.join(img_path, f"{tile_id}.tif")
    if os.path.exists(image_path):
        print(f"Image {tile_id}.tif found locally.")
        return image_path
    else:
        print(f"Image {tile_id}.tif not found locally.")
        print("Loading image from GCP...")

        storage_client = storage.Client(client)
        bucket = storage_client.bucket(gc_bucket)
        blob = bucket.blob(os.path.join(gc_folder_prefix, img_path, f"{tile_id}.tif"))

        filepath = os.path.join(img_path, f"{tile_id}.tif")
        blob.download_to_filename(filepath)

    return image_path


def download_from_cloud(
    client,
    gc_bucket,
    gc_folder_prefix,
    local_folder,
    tile_ids=None,
    redownload=False,
):
    """
    Downloads files from a Google Cloud Storage bucket to a local directory.

    Args:
        client (str): The client ID for the Google Cloud Storage.
        gc_bucket (str): The name of the Google Cloud Storage bucket.
        gc_folder_prefix (str): The folder path within the bucket where the files are located.
        local_folder (str): The local directory where the files will be downloaded to.
        tile_ids (list, optional): A list of tile IDs to download. If None, all files in the folder will be downloaded. Defaults to None.
        redownload (bool, optional): Flag indicating whether to redownload all files, even if they already exist locally. Defaults to False.
    """

    # Set up Google Cloud Storage client
    client = storage.Client(client)
    gc_bucket = client.get_bucket(gc_bucket)
    gc_folder = os.path.join(gc_folder_prefix, local_folder)

    # get list of files to download
    if tile_ids:
        files_list = gc_bucket.list_blobs(prefix=gc_folder)
        files_list = [
            file
            for file in files_list
            if file.name.split("/")[-1].split(".")[0] in tile_ids
        ]
    else:
        files_list = gc_bucket.list_blobs(prefix=gc_folder)
        files_list = [file for file in files_list if file.name.endswith(".tif")]

    # create destination directory if it doesn't exist
    if not os.path.exists(local_folder):
        logging.info(f"{local_folder} does not exist. Creating it now.")
        os.makedirs(local_folder)

        # download files
        for file in tqdm(files_list, desc=f"Downloading all files from {gc_folder}."):
            file_name = file.name.split("/")[-1]
            file_path = os.path.join(local_folder, file_name)
            file.download_to_filename(file_path)

    # directory exists but is empty
    elif len(os.listdir(local_folder)) == 0:
        logging.info(f"{local_folder} is empty.")

        # download files
        for file in tqdm(files_list, desc=f"Downloading all files from {gc_folder}"):
            file_name = file.name.split("/")[-1]
            file_path = os.path.join(local_folder, file_name)
            file.download_to_filename(file_path)

    else:
        if redownload:
            logging.info(
                f"Redownload flag set. Downloading all files from {gc_folder}."
            )
            to_download = files_list

        else:
            logging.info(
                f"Some files already exist locally in {local_folder}. Checking for missing files."
            )

            # Get list of files that already exist locally
            local_files = [a_file for a_file in os.listdir(local_folder)]

            # Find files in the cloud whose names don't appear locally
            to_download = [
                a_blob
                for a_blob in files_list
                if a_blob.name.split("/")[-1] not in local_files
            ]

            # For already downloaded files, check if they are the same size
            already_downloaded = [
                a_blob
                for a_blob in files_list
                if a_blob.name.split("/")[-1] in local_files
            ]

            # Find files in the cloud that have corresponding local files, but the two files are different sizes
            different_sizes = [
                a_blob
                for a_blob in already_downloaded
                if a_blob.size
                != os.path.getsize(
                    os.path.join(local_folder, a_blob.name.split("/")[-1])
                )
            ]
            to_download += different_sizes

            if len(to_download) == 0:
                logging.info("All files are up to date. Exiting.")
                return
            else:
                logging.info(
                    f"Downloading remaining {len(to_download)} files from {gc_folder}."
                )

        if len(to_download) >= 1:

            # Download
            for a_file in tqdm(
                to_download,
                desc=f"Downloading {len(to_download)} files to {local_folder}",
            ):
                file_name = a_file.name.split("/")[-1]
                file_path = os.path.join(local_folder, file_name)
                a_file.download_to_filename(file_path)

    logging.info("All files downloaded.")
    return


@click.command()
@click.option(
    "--config_filepath",
    default="cafo_iowa/config.yaml",
    help="Path to the configuration file.",
)
@click.option(
    "--operation",
    type=click.Choice(["upload", "download"]),
    help="Operation to perform: upload or download.",
)
@click.option(
    "--tile_ids",
    type=str,
    default=None,
    help="Comma-separated list of tile IDs to upload or download.",
)
def main(config_filepath, operation, tile_ids=None):
    """
    Main function to handle upload or download operations based on command line arguments.
    """
    # Load config yaml
    with open(config_filepath, "r") as file:
        config = yaml.safe_load(file)

    if operation == "upload":
        for folder in ["raw", "cropped", "quartered", "quartered_buffer"]:
            upload_to_cloud(
                service_account_path=config["gcs"]["service_account_path"],
                client=config["gcs"]["client"],
                gc_bucket=config["gcs"]["gc_bucket"],
                local_folder=config["naip"]["paths"][folder],
                tile_ids=tile_ids,
                gc_folder_prefix=config["gcs"]["gc_folder_prefix"],
                reupload=config["rerun"],
            )
    elif operation == "download":
        for folder in ["raw", "cropped", "quartered", "quartered_buffer"]:
            download_from_cloud(
                service_account_path=config["gcs"]["service_account_path"],
                client=config["gcs"]["client"],
                gc_bucket=config["gcs"]["gc_bucket"],
                local_folder=config["naip"]["paths"][folder],
                tile_ids=tile_ids,
                gc_folder_prefix=config["gcs"]["gc_folder_prefix"],
                redownload=config["rerun"],
            )
    else:
        raise ValueError("Invalid operation. Choose 'upload' or 'download'.")


if __name__ == "__main__":
    main()
