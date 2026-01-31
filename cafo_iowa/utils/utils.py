import hashlib
import json
import logging
import os
import re
import zipfile
from ast import literal_eval
from builtins import input
from datetime import datetime
from typing import List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from shapely.geometry import Point
from shapely.wkt import loads

from cafo_iowa.estimate.constants import ANIMAL_TYPE_UNITS_CONVERSION


def is_remote():
    """
    Check if the code is running on a remote server.

    Returns:
        bool: True if the code is running on a remote server, False otherwise.

    """
    return "SSH_CONNECTION" in os.environ


def check_config_version(config_version):
    """
    Checks the server environment and configuration version and prompts for confirmation if necessary.

    Args:
        config_version (str): The configuration version to check.

    Raises:
        SystemExit: If the user does not confirm the configuration version.

    """
    # check whether you're on remote server. If you are and config_type is set to production, ask for confirmation
    if is_remote() and config_version == "dev":
        response = input(
            "Running on remote server. Are you sure you want to run pipeline in dev mode? (y/n): "
        )
        if response != "y":
            raise SystemExit(
                "Exiting get_data. Change config.config_version to `prod' to run in prod mode."
            )
    if not is_remote() and config_version == "prod":
        response = input(
            "Running on dev server. Are you sure you want to run pipeline in prod mode? (y/n): "
        )
        if response != "y":
            raise SystemExit(
                "Exiting get_data. Change config.config_version to `dev' to run in dev mode."
            )


def start_logger(
    file_path,
    file_name,
    print_to_console=True,
):
    """once experiment id exists, have config

    Args:
        config (dict): the whole config file
        experiment_id (int): relevant experiment id
        pipeline_start_time (str): start time for pipeline
        backlog (list[str]): strings we wanted to put in the config before it existed

    """
    if not os.path.exists(file_path):
        os.makedirs(file_path)

    start_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    logging.basicConfig(
        encoding="utf-8",
        format="%(asctime)s:%(levelname)s:%(message)s",
        level=logging.INFO,
        handlers=[
            logging.FileHandler(f"{file_path}/{file_name}-{start_time}.log"),
            (logging.StreamHandler() if print_to_console else None),
        ],
    )

    # ignore matplotlib output because it's overwhelming
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith("matplotlib"):
            logger.disabled = True

    logging.info(f"New {file_name} log file started at {start_time}")


def unzip_all_files(folder_path):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".zip"):
                zip_path = os.path.join(root, file)
                extract_to = os.path.join(root, os.path.splitext(file)[0])

                # Extract the zip file
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(extract_to)

                # Delete the zip file after extraction
                os.remove(zip_path)

                # Recursively unzip files in the extracted folder
                unzip_all_files(extract_to)


def find_json_files(root_folder):
    json_files = []
    for dirpath, dirnames, filenames in os.walk(root_folder):
        for filename in filenames:
            if filename.endswith(".json"):
                json_files.append(os.path.join(dirpath, filename))
    return json_files


def stable_hash(value):
    """
    Generate a stable hash of a string value using SHA-256.
    This function is deterministic and does not depend on any random seed -
    it will always produce the same hash for the same input string.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def safe_eval(x):
    if pd.isna(x):
        return []
    try:
        return literal_eval(x)
    except (ValueError, SyntaxError):
        return []


def clean_text_for_matching(
    text: str,
    words_to_remove: Optional[List[str]] = None,
    preserve_special_chars: bool = False,
    handle_initials: bool = True,
    standardize_separators: bool = False,
) -> str:
    """
    Comprehensive text cleaning function for matching with configurable behavior.

    Args:
        text: The text to clean
        words_to_remove: List of words to remove
        preserve_special_chars: Whether to preserve special characters like &, ., -, ,
        handle_initials: Whether to handle single-letter initials
        standardize_separators: Whether to standardize separators (AND -> &, etc.)

    Returns:
        Cleaned text, or a special value for None/NaN inputs to prevent matching
    """
    # Special handling for None/NaN values to prevent matching
    if pd.isna(text) or text is None:
        return "MISSING_NAME_PLACEHOLDER"

    if not isinstance(text, str):
        text = str(text)

    # Convert to uppercase for consistency and strip whitespace
    text = text.upper().strip()

    # Handle empty strings after stripping
    if not text:
        return "MISSING_NAME_PLACEHOLDER"

    # Standardize separators if requested
    if standardize_separators:
        text = text.replace(" AND ", " & ")
        text = text.replace("/", " & ")
        text = text.replace(" + ", " & ")

    # Replace common separators with spaces if not preserving special chars
    if not preserve_special_chars:
        # Note: We're keeping the ampersand (&) as a special character to preserve
        text = text.replace(",", " ")
        text = text.replace(".", " ")
        text = text.replace("-", " ")

    # Remove non-alphabetic characters if not preserving special chars
    if not preserve_special_chars:
        # Keep ampersand (&) as a special character
        text = re.sub(r"[^A-Z\s&]", "", text)
    else:
        # Keep alphanumerics and some special chars
        text = re.sub(r"[^\w\s&,.-]", "", text)

    # Normalize spaces
    text = " ".join(text.split())

    # Handle empty strings after normalization
    if not text:
        return "MISSING_NAME_PLACEHOLDER"

    # Split into words
    words = text.split()

    # Remove specified words
    if words_to_remove:
        words = [w for w in words if w not in words_to_remove]

    # Handle initials if requested
    if handle_initials:
        # Special case: if the entire name is just a single letter, keep it
        if len(words) == 1 and len(words[0]) == 1:
            return words[0]

        # For multiple words, remove single letters unless text is very short
        if len(words) > 1:
            # Keep single letters only if they're the only word or if text is very short
            if len(text) <= 4:
                pass
            else:
                words = [w for w in words if len(w) > 1]

    # Remove duplicated words
    words = list(dict.fromkeys(words))

    # Join back together
    result = " ".join(words)

    # Final check for empty result
    return result if result else "MISSING_NAME_PLACEHOLDER"


def extract_geoms_from_list(data, column_name, crs):
    """
    Extracts, cleans, and converts a column of geometries from a GeoDataFrame
    into a valid GeoSeries.

    Parameters:
    - data (GeoDataFrame): The input GeoDataFrame.
    - column_name (str): The name of the column containing geometries.
    - crs (str): The coordinate reference system to use for the GeoSeries.

    Returns:
    - GeoSeries: A cleaned and converted GeoSeries.
    """
    if column_name not in data.columns:
        raise ValueError(f"Column '{column_name}' not found in DataFrame.")

    # Explode lists of geometries, drop NaNs, and parse WKT strings if necessary
    geometries = data[column_name].explode().dropna()

    # Convert WKT strings to Shapely geometries
    geometries = geometries.apply(lambda g: loads(g) if isinstance(g, str) else g)

    # Convert to GeoSeries
    return gpd.GeoSeries(geometries, crs=crs)


def save_geojson_with_lists(gdf, filename):
    """
    Saves a GeoDataFrame to a GeoJSON file, automatically converting list-type columns to JSON strings.

    Parameters:
    gdf (GeoDataFrame): The GeoDataFrame to be saved.
    filename (str): The output GeoJSON file path.

    Returns:
    None
    """
    gdf_copy = gdf.copy()

    # Identify columns that contain lists
    list_columns = [
        col
        for col in gdf_copy.columns
        if gdf_copy[col].apply(lambda x: isinstance(x, list)).any()
    ]

    # Convert list columns to JSON strings
    for col in list_columns:
        gdf_copy[col] = gdf_copy[col].apply(
            lambda x: (
                json.dumps([str(i) for i in x if i is not None])
                if isinstance(x, list)
                else "[]"
            )
        )

    # remove columns that end with  _samples
    gdf_copy = gdf_copy.loc[:, ~gdf_copy.columns.str.endswith("_samples")]

    # Save to GeoJSON
    gdf_copy.to_file(filename, driver="GeoJSON", geometry="facility_geom")

    print(f"GeoJSON saved successfully: {filename}")


def convert_animal_units_to_counts(animal_units):
    # Converting from animal counts to animal units based on conversion factors for each animal
    unit_conversion = ANIMAL_TYPE_UNITS_CONVERSION
    estimated_count_animal_units = {
        key: animal_units[key] / unit_conversion[key]
        for key in unit_conversion
        if key in animal_units
    }
    return estimated_count_animal_units


def convert_counts_to_animal_units(animal_counts):
    # Converting from animal counts to animal units based on conversion factors for each animal
    unit_conversion = ANIMAL_TYPE_UNITS_CONVERSION
    estimated_count_animal_units = {
        key: unit_conversion[key] * animal_counts[key]
        for key in unit_conversion
        if key in animal_counts
    }
    return estimated_count_animal_units


# Function to generate new locations within a 20m radius
def generate_random_points(id, geometry, num_points=10, radius=50):
    lon, lat = geometry.x, geometry.y
    new_points = []
    for _ in range(num_points):
        angle = np.random.uniform(0, 2 * np.pi)
        distance = np.random.uniform(0, radius)  # Random distance within radius
        dx = distance * np.cos(angle)
        dy = distance * np.sin(angle)
        new_points.append({"id": id, "geometry": Point(lon + dx, lat + dy)})
    return new_points


def best_fuzzy_match(candidate_owners, facility_name, threshold=80):
    """
    Given a list of owner names (candidate_owners) and a single permit facility_name,
    return (best_owner, best_score) if the best fuzzy match >= threshold,
    otherwise (None, None).
    """
    if not facility_name or pd.isna(facility_name):
        return None, None

    best_score = 0
    best_owner = None
    for owner_str in candidate_owners:
        if pd.notna(owner_str):
            score = fuzz.ratio(facility_name, owner_str)
            if score > best_score:
                best_score = score
                best_owner = owner_str

    if best_score >= threshold:
        return best_owner, best_score
    return None, None
