import json
import logging
import os
import re

import click
import dtlpy as dl
import geopandas as gpd
import numpy as np
import pandas as pd
import seaborn as sns
import yaml
from google.cloud import storage
from sqlalchemy import func
from tqdm import tqdm

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s
from cafo_iowa.data.helpers.gcs import create_subset, upload_to_cloud

# Create annotated images for the batch
from cafo_iowa.data.helpers.imgs import prepare_tiles_for_relabeling
from cafo_iowa.utils.strata import stratified_sample


def create_unlabeled_batch(
    sample_size=1000, sampling_dict: dict = {"0": 0.01}, urban_area_cutoff: float = 1
):

    session = s.get_session()

    # load tiles that are not yet labelled
    data = gpd.read_postgis(
        f"""
        WITH
            permit_tiles AS (
                SELECT
                    naip_qt_id,
                    SUM(animal_units) as animal_units,
                    SUM(swine_animal_units) as swine_animal_units,
                    COUNT(*) as n_facilities,
                    ARRAY_AGG(facilityid) as facilityid_list
                FROM processed.{m.Permits.__tablename__}
                WHERE animal_units > 0
                GROUP BY naip_qt_id
            ),
            naip21_qt AS (
                SELECT
                    id as naip_qt_id,
                    geometry,
                    is_urban,
                    urban_area
                FROM processed.{m.Naip21QT.__tablename__}
            ),
            labelled_tiles AS (
                SELECT
                    batch_name,
                    naip_qt_id
                FROM processed.label_batches,
                jsonb_array_elements_text(naip_qt_ids) AS naip_qt_id
            )
        SELECT
            n.*,
            COALESCE(p.animal_units, 0) as animal_units,
            COALESCE(p.swine_animal_units, 0) as swine_animal_units,
            COALESCE(p.n_facilities, 0) as n_facilities,
            p.facilityid_list,
            CASE
                WHEN p.n_facilities > 0 THEN p.animal_units / p.n_facilities
                ELSE 0
            END as animal_units_per_permit,
            CASE
                WHEN p.n_facilities > 0 THEN p.swine_animal_units / p.n_facilities
                ELSE 0
            END as swine_animal_units_per_permit,
            CASE
                WHEN COALESCE(p.n_facilities, 0) = 0 THEN '0'
                WHEN p.animal_units / p.n_facilities BETWEEN 0 AND 399 THEN '1-399'
                WHEN p.animal_units / p.n_facilities BETWEEN 400 AND 499 THEN '400-499'
                WHEN p.animal_units / p.n_facilities BETWEEN 500 AND 699 THEN '500-699'
                WHEN p.animal_units / p.n_facilities BETWEEN 700 AND 899 THEN '700-899'
                WHEN p.animal_units / p.n_facilities BETWEEN 900 AND 999 THEN '900-999'
                WHEN p.animal_units / p.n_facilities BETWEEN 1000 AND 1199 THEN '1000-1199'
                WHEN p.animal_units / p.n_facilities BETWEEN 1200 AND 1499 THEN '1200-1499'
                WHEN p.animal_units / p.n_facilities BETWEEN 1500 AND 1899 THEN '1500-1899'
                WHEN p.animal_units / p.n_facilities BETWEEN 1900 AND 1999 THEN '1900-1999'
                WHEN p.animal_units / p.n_facilities BETWEEN 2000 AND 2499 THEN '2000-2499'
                WHEN p.animal_units / p.n_facilities >= 2500 THEN '2500+'
            END as animal_units_per_permit_q
        FROM naip21_qt n
        LEFT JOIN permit_tiles p USING (naip_qt_id)
        LEFT JOIN labelled_tiles l ON n.naip_qt_id = l.naip_qt_id
        WHERE l.naip_qt_id IS NULL AND n.urban_area <= {urban_area_cutoff};
        """,
        s.get_engine(),
        geom_col="geometry",
    )

    # generate new label batch
    max_batch_nr = session.query(func.max(m.LabelBatches.id)).scalar()
    new_batch_nr = max_batch_nr + 1 if max_batch_nr else 1
    batch_name = f"IA_data_labeling_batch{new_batch_nr}"

    batch_data = stratified_sample(
        data,
        strata_col="animal_units_per_permit_q",
        sample_size=sample_size,
        sampling_dict=sampling_dict,
        random_state=1,
    )

    # check that tiles are unique
    assert batch_data["naip_qt_id"].nunique() == len(batch_data)
    # check that batch data length matches sample size
    if len(batch_data) != sample_size:
        logging.warning(
            f"Sample size of batch (n = {batch_data}) does not match requested sample size (n = {sample_size})."
        )

    # check that no tiles in new batch are already labelled
    labelled_tiles = gpd.read_postgis(
        """
        SELECT naip_qt_ids
        FROM processed.label_batches
        WHERE naip_qt_ids IS NOT NULL
        """,
        s.get_engine(),
    )["naip_qt_ids"].tolist()
    labelled_tiles = [tile_id for sublist in labelled_tiles for tile_id in sublist[0]]

    assert len(set(labelled_tiles).intersection(set(batch_data["naip_qt_id"]))) == 0

    # add urban_area_cutoff to sampling_dict
    sampling_dict["urban_area_cutoff"] = urban_area_cutoff

    # add new batch to database
    new_batch = m.LabelBatches(
        id=new_batch_nr,
        batch_name=batch_name,
        batch_size=batch_data.shape[0],
        batch_date=pd.Timestamp.now().date(),
        batch_metadata=sampling_dict,
        naip_qt_ids=batch_data["naip_qt_id"].to_list(),
        n_facilities=int(batch_data["n_facilities"].sum()),
        facility_ids=batch_data["facilityid_list"].to_list(),
    )

    session.add(new_batch)
    session.commit()
    session.close()
    logging.info(f"Created new label batch {batch_name} with {sample_size} tiles.")


def create_custom_label_batch(tile_ids, batch_name=None, batch_metadata=None):
    """
    Creates a custom labeling batch with the specified tile IDs, regardless of whether they've been labeled before.

    Args:
        tile_ids (list): List of tile IDs to include in the batch.
        batch_name (str, optional): Custom name for the batch. If None, a default name will be generated.
        batch_metadata (dict, optional): Additional metadata to store with the batch.

    Returns:
        str: The name of the created batch.
    """
    session = s.get_session()

    # Validate that all tile IDs exist in the database
    existing_tiles = pd.read_sql(
        f"""
        SELECT id as naip_qt_id
        FROM processed.{m.Naip21QT.__tablename__}
        WHERE id IN %(tile_ids)s
        """,
        s.get_engine(),
        params={"tile_ids": tuple(tile_ids)},
    )

    if len(existing_tiles) != len(tile_ids):
        missing_tiles = set(tile_ids) - set(existing_tiles["naip_qt_id"])
        raise ValueError(f"Some tile IDs do not exist in the database: {missing_tiles}")

    # Get additional information about the tiles
    tile_data = pd.read_sql(
        f"""
        WITH
            permit_tiles AS (
                SELECT
                    naip_qt_id,
                    SUM(animal_units) as animal_units,
                    SUM(swine_animal_units) as swine_animal_units,
                    COUNT(*) as n_facilities,
                    ARRAY_AGG(facilityid) as facilityid_list
                FROM processed.{m.Permits.__tablename__}
                WHERE animal_units > 0
                GROUP BY naip_qt_id
            )
        SELECT
            n.id as naip_qt_id,
            COALESCE(p.animal_units, 0) as animal_units,
            COALESCE(p.swine_animal_units, 0) as swine_animal_units,
            COALESCE(p.n_facilities, 0) as n_facilities,
            p.facilityid_list
        FROM processed.{m.Naip21QT.__tablename__} n
        LEFT JOIN permit_tiles p ON n.id = p.naip_qt_id
        WHERE n.id IN %(tile_ids)s
        """,
        s.get_engine(),
        params={"tile_ids": tuple(tile_ids)},
    )

    # Generate batch name if not provided
    if batch_name is None:
        max_batch_nr = session.query(func.max(m.LabelBatches.id)).scalar()
        new_batch_nr = max_batch_nr + 1 if max_batch_nr else 1
        batch_name = f"IA_custom_labeling_batch{new_batch_nr}"

    # Set default metadata if not provided
    if batch_metadata is None:
        batch_metadata = {"custom_batch": True}
    else:
        batch_metadata["custom_batch"] = True

    # Add new batch to database
    new_batch = m.LabelBatches(
        batch_name=batch_name,
        batch_size=len(tile_ids),
        batch_date=pd.Timestamp.now().date(),
        batch_metadata=batch_metadata,
        naip_qt_ids=tile_ids,
        n_facilities=int(tile_data["n_facilities"].sum()),
        facility_ids=tile_data["facilityid_list"].to_list(),
    )

    session.add(new_batch)
    session.commit()
    session.close()

    logging.info(f"Created custom label batch {batch_name} with {len(tile_ids)} tiles.")
    return batch_name


def dl_auth():
    """
    Authenticates the user with the dataloop service.

    This function checks if the user's token has expired and logs in if necessary.
    """
    if dl.token_expired():
        dl.login()


def extract_metadata_from_batch(batch_name: str, session=None):
    """
    Extracts metadata from a batch file.

    Args:
        batch_name (str): The name of the batch we are sending to dataloop for labelling.

    Returns:
        pandas.DataFrame: A DataFrame containing the extracted metadata, including the filename, latitude, longitude, and a Google Maps link.

    """

    if session is None:
        session = s.get_session()

    batch = gpd.read_postgis(
        f"""
        SELECT
            n.id as naip_qt_id,
            n.geometry
        FROM processed.{m.Naip21QT.__tablename__} n
        JOIN processed.{m.LabelBatches.__tablename__} l
        ON n.id = ANY(ARRAY(SELECT jsonb_array_elements_text(l.naip_qt_ids)::text))
        WHERE l.batch_name = '{batch_name}';
        """,
        session.connection(),
        geom_col="geometry",
    )
    if batch.empty:
        raise ValueError(f"No batch found with name {batch_name}.")

    # Add metadata to batch for labeling
    batch["fn"] = batch["naip_qt_id"] + ".jpeg"
    batch["centroid"] = batch.geometry.centroid
    centroids = batch.set_geometry("centroid").to_crs("EPSG:4326")
    batch["latitude"] = centroids.geometry.y
    batch["longitude"] = centroids.geometry.x

    # Create Google Maps link
    batch["gmaps_link"] = batch.apply(
        lambda row: f"http://maps.google.com/maps?t=k&q=loc:{row.latitude}+{row.longitude}",
        axis=1,
    )

    batch = batch[["fn", "latitude", "longitude", "gmaps_link"]]

    session.close()

    return batch


def create_labeling_dataset(
    batch_name: str,
    gc_bucket: str = "image-hub",
    gc_folder_prefix: str = "IA",
    gc_source_folder: str = "data/NAIP21QQ/04_quartered_buffer_tiles/jpegs/",
    destination_folder: str = None,
    dl_project: str = "RegLab_Prod",
):
    """
    Creates a labeling dataset in Dataloop based on the provided batch name.

    Args:
        batch_name (str): The name of the batch that's to be labelled.
        gc_bucket (str, optional): The Google Cloud Storage bucket name. Defaults to "image-hub".
        gc_folder_prefix (str, optional): The prefix for the Google Cloud folder. Defaults to "IA".
        gc_source_folder (str, optional): The source folder path within the Google Cloud Storage bucket. Defaults to "data/NAIP21QQ/04_quartered_buffer_tiles/jpegs/".
        destination_folder (str, optional): The destination folder path within the Google Cloud Storage bucket. If not specified, it will be derived from the batch file name. Defaults to None.
        dl_project (str, optional): The name of the Dataloop project. Defaults to "RegLab_Prod".

    Returns:
        None
    """
    # add source and destination folders
    gc_source_folder = os.path.join(gc_folder_prefix, gc_source_folder)
    # if destination folder is not specified, use the batch file name as the destination folder name
    if not destination_folder:
        destination_folder = os.path.join(batch_name.replace("_", "/"))
        logging.info(
            f"Destination folder not specified. Using {destination_folder} instead."
        )

    # check if this batch exists
    session = s.get_session()
    batch = (
        session.query(m.LabelBatches)
        .filter(m.LabelBatches.batch_name == batch_name)
        .first()
    )
    session.close()

    if not batch:
        raise ValueError(f"Batch {batch_name} not found in database.")

    # Extract metadata from batch file
    batch_metadata = extract_metadata_from_batch(batch_name)

    # Copy images specified in the batch file to the destination folder
    create_subset(
        source_bucket=gc_bucket,
        source_folder=gc_source_folder,
        destination_bucket=gc_bucket,
        destination_folder=destination_folder,
        image_names=batch_metadata["fn"],
    )

    # Create or update driver in Dataloop
    dl_auth()
    project = dl.projects.get(dl_project)
    drivers = project.drivers.list()
    driver = None
    for existing_driver in drivers[::-1]:
        # check if driver already exists
        if existing_driver.name == batch_name:
            if existing_driver.path == destination_folder:
                driver = existing_driver
                break
            else:
                raise ValueError(
                    f"Driver with name {batch_name} already exists but has different path {existing_driver.path}."
                )
    if not driver:
        driver = project.drivers.create(
            name=batch_name,
            driver_type=dl.ExternalStorage.GCS,
            # for law-cafo, gotten through net request spy
            integration_id="41b5b0c8-bf3f-4054-ab44-edd7718768a8",
            integration_type=dl.IntegrationType.GCS,
            bucket_name=gc_bucket,
            path=destination_folder,
        )

    # Create label dictionary
    labels = ["Blank", "flag", "cafo"]
    colors = sns.color_palette("hls", len(labels))
    labels_dict = {}
    for i, label in enumerate(labels):
        color = colors[i]
        color = [int(c * 255) for c in color]
        labels_dict[label] = tuple(color)

    # Create or update dataset in Dataloop
    datasets = project.datasets.list()
    dataset = None
    # check if dataset already exists
    for existing_dataset in datasets:
        if existing_dataset.name == batch_name and existing_dataset.driver != driver.id:
            raise ValueError(
                f"Dataset with name {batch_name} already exists but has different driver {dataset.driver.id}."
            )
        if existing_dataset.name == batch_name and existing_dataset.driver == driver.id:
            dataset = existing_dataset
    # create dataset if it doesn't exist
    if not dataset:
        dataset = project.datasets.create(
            driver=driver,
            dataset_name=batch_name,
            labels=labels_dict,
        )
        dataset.sync()

    # Update metadata in Dataloop
    for _, row in tqdm(batch_metadata.iterrows(), total=len(batch_metadata)):
        filename = row["fn"]
        item = dataset.items.get("/" + filename)
        item.metadata["user"] = {idx: row[idx] for idx in row.index if idx != "fn"}
        _ = item.update()

    progress_bar = tqdm(total=len(batch_metadata), desc="Updating metadata")

    # Update metadata in Dataloop
    for _, row in batch_metadata.iterrows():
        filename = row["fn"]
        item = dataset.items.get("/" + filename)
        item.metadata["user"] = {idx: row[idx] for idx in row.index if idx != "fn"}
        _ = item.update()

        progress_bar.update(1)

    progress_bar.close()


def download_dataset_annotations(
    batch_name: str = "IA*",
    dl_project: str = "RegLab_Prod",
    annotations_format="dataloop",
    filter_unannotated=False,
    local_folder: str = "data/annotations",
):
    """
    Downloads a labeling dataset from a Dataloop project. Defaults to downloading all datasets with the specified batch name.

    Args:
        batch_name (str): The name of the batch to download.
        dl_project (str, optional): The name of the Dataloop project. Defaults to "RegLab_Prod".
        annotations_format (str, optional): The format of the downloaded annotations. Defaults to "dataloop".
        filter_unannotated (bool, optional): Whether to filter out unannotated items. Defaults to False.
        local_folder (str, optional): The local folder to save the downloaded dataset. Defaults to "data/labeling".

    Returns:
        None
    """
    dl_auth()

    try:
        project = dl.projects.get(dl_project)
    except:
        print(f"Project {dl_project} not found")
        return

    datasets = project.datasets.list(batch_name)

    if len(datasets) == 0:
        print(f"Dataset {batch_name} not found in project {dl_project}")
        return

    if len(datasets) == 1:
        print(f"Downloading dataset {datasets[0].name}")
        pass

    if len(datasets) > 1:
        response = input(
            f"Multiple datasets found for batch name {batch_name}: {[d.name for d in datasets]}. Which ones would you like to download? (all, none, or specify the names separated by commas): "
        )

        if response.lower() == "all":
            print("Downloading all datasets.")
            pass
        elif response.lower() == "none":
            print("No datasets downloaded.")
            return
        elif response:
            response = re.sub(r"\s+", "", response)
            datasets = [
                d
                for d in datasets
                if any(part in d.name for part in response.split(","))
            ]
            print(f"Downloading datasets: {[d.name for d in datasets]}")
        else:
            print("No valid response provided. No datasets downloaded.")
            return

    for dataset in datasets:

        dataset = project.datasets.get(dataset.name)

        if filter_unannotated:
            filters = dl.Filters(field="annotated", values=True)
        else:
            filters = None

        converter = dl.Converter()

        output_path = os.path.join(local_folder, dataset.name)

        converter.convert_dataset(
            dataset=dataset,
            to_format=annotations_format,
            local_path=output_path,
            filters=filters,
        )

        print(f"{dataset.name} annotations downloaded to {output_path}")
    return None


def add_annotations_to_tiles(tile_ids: list, batch_name: str):
    """
    Add annotations to tiles based on permits and barns data.

    Args:
        tile_ids (list): List of tile IDs to annotate
        batch_name (str): Name of the batch to create annotations for

    Returns:
        dict: Dictionary containing annotations for each tile
    """
    session = s.get_session()
    engine = session.bind

    # Query permits and barns for the given tiles using geopandas
    permits = gpd.read_postgis(
        f"""
        SELECT * FROM processed.permits
        WHERE naip_qt_id IN ('{"','".join(tile_ids)}')
        """,
        engine,
        geom_col="geometry",
    )

    barns = gpd.read_postgis(
        f"""
        SELECT b.*, bc.naip_qt_id
        FROM processed.barns b
        JOIN processed.barn_clusters bc ON b.barn_cluster_id = bc.id
        WHERE bc.naip_qt_id IN ('{"','".join(tile_ids)}')
        """,
        engine,
        geom_col="geometry",
    )

    annotations = {}

    # Process permits
    for _, permit in permits.iterrows():
        tile_id = permit.naip_qt_id
        if tile_id not in annotations:
            annotations[tile_id] = []

        # Create bounding box annotation for permit
        permit_annotation = {
            "type": "box",
            "label": "permit",
            "coordinates": {
                "x": permit.longitude,
                "y": permit.latitude,
                "width": 0.0001,  # Approximate size in degrees
                "height": 0.0001,
            },
            "metadata": {
                "facility_id": permit.facility_id,
                "animal_units": permit.animal_units,
                "animal_type": permit.animal_type,
            },
        }
        annotations[tile_id].append(permit_annotation)

    # Process barns
    for _, barn in barns.iterrows():
        tile_id = barn.naip_qt_id
        if tile_id not in annotations:
            annotations[tile_id] = []

        # Convert geometry to bounding box
        bounds = barn.geometry.bounds
        barn_annotation = {
            "type": "box",
            "label": "barn",
            "coordinates": {
                "x": bounds[0],
                "y": bounds[1],
                "width": bounds[2] - bounds[0],
                "height": bounds[3] - bounds[1],
            },
            "metadata": {
                "facility_id": barn.facility_id,
                "barn_cluster_id": barn.barn_cluster_id,
            },
        }
        annotations[tile_id].append(barn_annotation)

    # Save annotations to file
    output_dir = os.path.join("data", "annotations", batch_name)
    os.makedirs(output_dir, exist_ok=True)

    for tile_id, tile_annotations in annotations.items():
        output_file = os.path.join(output_dir, f"{tile_id}.json")
        with open(output_file, "w") as f:
            json.dump(tile_annotations, f, indent=2)

    return annotations


@click.command()
@click.option(
    "--operation",
    prompt="Operation to perform: create_batch, create_custom_batch, create_annotated_batch, upload, or download",
    type=click.Choice(
        [
            "create_batch",
            "create_custom_batch",
            "create_annotated_batch",
            "upload",
            "download",
        ]
    ),
    help="Operation to perform: create_batch, create_custom_batch, create_annotated_batch, upload, or download",
    required=True,
)
@click.option(
    "--config_filepath", type=str, help="Path to config file.", required=False
)
def manage_labeling_dataset(
    operation: str = "upload",
    config_filepath: str = "cafo_iowa/labels/cfg/config.yaml",
):
    """
    Manage a labeling dataset using the provided configuration file and optional parameters.
    """
    # set up logging
    logging.basicConfig(
        format="%(asctime)s - %(message)s",
        level=logging.INFO,
    )

    if not config_filepath:
        config_filepath = "cafo_iowa/data/cfg/config.yaml"

    # load config
    with open(config_filepath, "r") as f:
        config = yaml.safe_load(f)

    if operation == "create_batch":

        create_unlabeled_batch(
            sample_size=config["batches"]["batch_size"],
            sampling_dict=config["batches"]["sampling_dict"],
            urban_area_cutoff=config["batches"]["urban_area_cutoff"],
        )

    elif operation == "create_custom_batch":
        # Get all available tile IDs
        session = s.get_session()
        tile_ids = session.query(m.Naip21QT.id).all()
        tile_ids = [id[0] for id in tile_ids]
        session.close()

        # Ask user how they want to provide tile IDs
        print("\nHow would you like to provide tile IDs?")
        print("1. Manually enter tile IDs")
        print("2. Read from a text file (one ID per line or comma-separated)")
        print("3. Read from a CSV file")

        input_method = input("Enter your choice (1-3): ")

        selected_tile_ids = []

        if input_method == "1":
            # Manual input
            print("Enter tile IDs separated by commas (e.g., 'tile1,tile2,tile3')")
            tile_ids_input = input("Tile IDs: ")

            if not tile_ids_input:
                logging.error("Error: No tile IDs provided.")
                return

            # Parse tile IDs
            selected_tile_ids = [
                tile_id.strip() for tile_id in tile_ids_input.split(",")
            ]

        elif input_method == "2":
            # Read from text file
            file_path = input("Enter the path to the text file: ")
            try:
                with open(file_path, "r") as f:
                    content = f.read().strip()
                    # Check if IDs are comma-separated or one per line
                    if "," in content:
                        selected_tile_ids = [
                            tile_id.strip() for tile_id in content.split(",")
                        ]
                    else:
                        selected_tile_ids = [
                            line.strip()
                            for line in content.splitlines()
                            if line.strip()
                        ]
            except Exception as e:
                logging.error(f"Error reading file: {str(e)}")
                return

        elif input_method == "3":
            # Read from CSV file
            file_path = input("Enter the path to the CSV file: ")
            try:
                import pandas as pd

                df = pd.read_csv(file_path)

                # Check if there's only one column
                if len(df.columns) == 1:
                    selected_tile_ids = df.iloc[:, 0].astype(str).tolist()
                else:
                    # Ask user which column contains the tile IDs
                    print("\nAvailable columns:", ", ".join(df.columns))
                    column_name = input("Enter the column name containing tile IDs: ")
                    if column_name not in df.columns:
                        logging.error(
                            f"Error: Column '{column_name}' not found in CSV file."
                        )
                        return
                    selected_tile_ids = df[column_name].astype(str).tolist()

                # Remove any empty strings or NaN values
                selected_tile_ids = [
                    tile_id
                    for tile_id in selected_tile_ids
                    if tile_id and tile_id.lower() != "nan"
                ]

            except Exception as e:
                logging.error(f"Error reading CSV file: {str(e)}")
                return
        else:
            logging.error("Invalid choice.")
            return

        if not selected_tile_ids:
            logging.error("Error: No tile IDs selected.")
            return

        # Validate tile IDs
        invalid_tile_ids = [
            tile_id for tile_id in selected_tile_ids if tile_id not in tile_ids
        ]
        if invalid_tile_ids:
            logging.error(f"Error: Invalid tile IDs: {invalid_tile_ids}")
            return

        # Prompt for custom batch name
        batch_name = input(
            "Enter a custom batch name (optional, press Enter for default): "
        )
        batch_name = batch_name if batch_name else None

        # Create custom batch
        create_custom_label_batch(
            tile_ids=selected_tile_ids,
            batch_name=batch_name,
            batch_metadata={"source": "manual_selection"},
        )

    elif operation == "create_annotated_batch":
        # Get all available tile IDs
        session = s.get_session()
        tile_ids = session.query(m.Naip21QT.id).all()
        tile_ids = [id[0] for id in tile_ids]
        session.close()

        # Ask user how they want to provide tile IDs
        print("\nHow would you like to provide tile IDs?")
        print("1. Manually enter tile IDs")
        print("2. Read from a text file (one ID per line or comma-separated)")
        print("3. Read from a CSV file")

        input_method = input("Enter your choice (1-3): ")

        selected_tile_ids = []

        if input_method == "1":
            # Manual input
            print("Enter tile IDs separated by commas (e.g., 'tile1,tile2,tile3')")
            tile_ids_input = input("Tile IDs: ")

            if not tile_ids_input:
                logging.error("Error: No tile IDs provided.")
                return

            # Parse tile IDs
            selected_tile_ids = [
                tile_id.strip() for tile_id in tile_ids_input.split(",")
            ]

        elif input_method == "2":
            # Read from text file
            file_path = input("Enter the path to the text file: ")
            try:
                with open(file_path, "r") as f:
                    content = f.read().strip()
                    # Check if IDs are comma-separated or one per line
                    if "," in content:
                        selected_tile_ids = [
                            tile_id.strip() for tile_id in content.split(",")
                        ]
                    else:
                        selected_tile_ids = [
                            line.strip()
                            for line in content.splitlines()
                            if line.strip()
                        ]
            except Exception as e:
                logging.error(f"Error reading file: {str(e)}")
                return

        elif input_method == "3":
            # Read from CSV file
            file_path = input("Enter the path to the CSV file: ")
            try:
                import pandas as pd

                df = pd.read_csv(file_path)

                # Check if there's only one column
                if len(df.columns) == 1:
                    selected_tile_ids = df.iloc[:, 0].astype(str).tolist()
                else:
                    # Ask user which column contains the tile IDs
                    print("\nAvailable columns:", ", ".join(df.columns))
                    column_name = input("Enter the column name containing tile IDs: ")
                    if column_name not in df.columns:
                        logging.error(
                            f"Error: Column '{column_name}' not found in CSV file."
                        )
                        return
                    selected_tile_ids = df[column_name].astype(str).tolist()

                # Remove any empty strings or NaN values
                selected_tile_ids = [
                    tile_id
                    for tile_id in selected_tile_ids
                    if tile_id and tile_id.lower() != "nan"
                ]

            except Exception as e:
                logging.error(f"Error reading CSV file: {str(e)}")
                return
        else:
            logging.error("Invalid choice.")
            return

        if not selected_tile_ids:
            logging.error("Error: No tile IDs selected.")
            return

        # Validate tile IDs
        invalid_tile_ids = [
            tile_id for tile_id in selected_tile_ids if tile_id not in tile_ids
        ]
        if invalid_tile_ids:
            logging.error(f"Error: Invalid tile IDs: {invalid_tile_ids}")
            return

        # Prompt for custom batch name
        batch_name = input(
            "Enter a custom batch name (optional, press Enter for default): "
        )
        batch_name = batch_name if batch_name else None

        # Ask if user wants to highlight specific permit IDs
        highlight_permits = input(
            "Do you want to highlight specific permit IDs? (y/n): "
        )
        highlight_permit_ids = None
        if highlight_permits.lower() == "y":
            permit_ids_input = input("Enter permit IDs separated by commas: ")
            if permit_ids_input:
                highlight_permit_ids = [
                    int(pid.strip()) for pid in permit_ids_input.split(",")
                ]

        # Create custom batch
        batch_name = create_custom_label_batch(
            tile_ids=selected_tile_ids,
            batch_name=batch_name,
            batch_metadata={
                "source": "annotated_tiles",
                "highlight_permit_ids": highlight_permit_ids,
            },
        )

        # Create output directory for annotated images
        output_dir = os.path.join("data", "annotated_tiles", batch_name)
        os.makedirs(output_dir, exist_ok=True)

        # Prepare annotated images
        annotated_paths = prepare_tiles_for_relabeling(
            tile_ids=selected_tile_ids,
            output_dir=output_dir,
            highlight_permit_ids=highlight_permit_ids,
        )

        logging.info(f"Created {len(annotated_paths)} annotated images in {output_dir}")

        # Determine destination folder in GCS
        destination_folder = os.path.join(batch_name.replace("_", "/"))

        # Upload annotated images to GCS
        upload_to_cloud(
            client=config["gcs"]["client"],
            gc_bucket=config["gcs"]["gc_bucket"],
            local_folder=output_dir,
            gc_folder_prefix=config["gcs"]["gc_folder_prefix"],
            tile_ids=selected_tile_ids,
            file_suffix=".jpeg",
            reupload=True,
        )

        logging.info(f"Uploaded annotated images to GCS in folder {destination_folder}")

        # Check if the dataset already exists and prompt the user
        dl_auth()
        project = dl.projects.get(config["dataloop"]["dl_project"])
        datasets = project.datasets.list()
        for existing_dataset in datasets:
            if existing_dataset.name == batch_name:
                click.confirm(
                    f"Dataset with name {batch_name} already exists in Dataloop. Do you want to proceed with updating it?",
                    abort=True,
                )
                break

        # Create labeling dataset using the annotated images
        create_labeling_dataset(
            batch_name,
            gc_bucket=config["gcs"]["gc_bucket"],
            gc_folder_prefix=config["gcs"]["gc_folder_prefix"],
            gc_source_folder=output_dir,
            destination_folder=destination_folder,
            dl_project=config["dataloop"]["dl_project"],
        )

        logging.info(
            f"Batch {batch_name} has been uploaded to Dataloop with annotated images"
        )

    elif operation == "upload":

        # get all batch names
        session = s.get_session()
        batch_names = session.query(m.LabelBatches.batch_name).all()
        batch_names = [name[0] for name in batch_names]
        session.close()

        # prompt user to select a batch
        batch_name = click.prompt(
            "Enter the name of the batch to upload", type=click.Choice(batch_names)
        )

        if not batch_name:
            logging.error(
                "Error: Batch name must be specified to create a labeling dataset."
            )
            return

        # Check if the dataset already exists and prompt the user
        dl_auth()
        project = dl.projects.get(config["dataloop"]["dl_project"])
        datasets = project.datasets.list()
        for existing_dataset in datasets:
            if existing_dataset.name == batch_name:
                click.confirm(
                    f"Dataset with name {batch_name} already exists in Dataloop. Do you want to proceed with updating it?",
                    abort=True,
                )
                break

        create_labeling_dataset(
            batch_name,
            gc_bucket=config["gcs"]["gc_bucket"],
            gc_folder_prefix=config["gcs"]["gc_folder_prefix"],
            gc_source_folder=config["dataloop"]["gc_source_folder"],
            destination_folder=config["dataloop"]["destination_folder"],
            dl_project=config["dataloop"]["dl_project"],
        )
    elif operation == "download":

        # get all batch names
        session = s.get_session()
        batch_names = session.query(m.LabelBatches.batch_name).all()
        batch_names = [name[0] for name in batch_names]
        session.close()

        # prompt user to select a batch
        batch_name = click.prompt(
            "Enter the name of the batch to download (default: IA*",
            type=click.Choice(batch_names),
        )

        download_dataset_annotations(
            batch_name if batch_name else "IA*",
            dl_project=config["dataloop"]["dl_project"],
            annotations_format=config["annotations"]["annotations_format"],
            filter_unannotated=config["annotations"]["filter_unannotated"],
            local_folder=config["annotations"]["local_folder"],
        )


if __name__ == "__main__":
    manage_labeling_dataset()
