import os
import warnings
from datetime import datetime

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def generate_stratified_sample(
    data, strata_column, sample_size, sampling_dict, random_state=None
):
    """
    Generate a stratified sample from a DataFrame based on specified sampling proportions.

    Parameters:
    - data: DataFrame containing the data with a column for stratification.
    - strata_column: The column name in 'data' used for stratification.
    - sample_size: Total number of samples desired.
    - sampling_dict: Dictionary specifying the sampling proportion for specific bins within the stratification column.
    - random_state: An integer seed for reproducibility or None for random sampling (default: None).

    Returns:
    - DataFrame containing the stratified sample of the specified size.

    Raises:
    - ValueError: If any key in the sampling_dict does not exist in the strata_column of the data.
    """
    # Check if all keys in sampling_dict are in the strata_column
    strata_values = data[strata_column].unique()
    missing_strata = [key for key in sampling_dict if key not in strata_values]
    if missing_strata:
        raise ValueError(
            f"The following strata are specified in sampling_dict but not found in {strata_column}: {missing_strata}"
        )

    # Calculate the specific numbers to sample from each bin
    samples_per_bin = {
        label: int(sample_size * proportion)
        for label, proportion in sampling_dict.items()
    }

    # Calculate the remainder of the sample
    sampled_so_far = sum(samples_per_bin.values())
    remainder = sample_size - sampled_so_far

    # Get counts of each bin to determine how to distribute the remainder
    bin_counts = data[strata_column].value_counts()

    # Remove bins that are already specified in the sampling_dict from the remainder distribution
    for label in sampling_dict.keys():
        bin_counts.pop(label)

    # Distribute the remainder proportionally based on the counts of the remaining bins
    remaining_samples_per_bin = (
        (bin_counts / bin_counts.sum() * remainder).round().astype(int)
    )

    # Update samples_per_bin with the calculated numbers for the remaining bins
    samples_per_bin.update(remaining_samples_per_bin.to_dict())

    # Sample from each bin according to the calculated numbers
    sampled_data = pd.DataFrame()
    for bin_label, n_samples in samples_per_bin.items():
        if n_samples > 0:  # Ensure there are samples to draw
            bin_sample = data[data[strata_column] == bin_label].sample(
                # Ensure the number of samples does not exceed the number of data points in the bin
                n=min(n_samples, len(data[data[strata_column] == bin_label])),
                random_state=random_state,
            )

            sampled_data = pd.concat([sampled_data, bin_sample])

    # Adjust the final sample to the desired size if necessary
    if len(sampled_data) > sample_size:
        sampled_data = sampled_data.sample(n=sample_size, random_state=random_state)

    sampled_data.reset_index(drop=True, inplace=True)

    return sampled_data


def stratified_sample(data, strata_col, sample_size, sampling_dict, random_state=None):
    """
    Generate a stratified sample from a dataframe based on specified sampling proportions.

    Parameters:
    - data: DataFrame containing the data
    - strata_col: Column name used for stratification
    - sample_size: Total number of samples desired
    - sampling_dict: Dict specifying sampling proportion for specific strata
    - random_state: Seed for reproducibility (default: None)

    Returns:
    - DataFrame containing the stratified sample
    """
    # Check for missing strata
    missing_strata = set(sampling_dict) - set(data[strata_col].unique())
    if missing_strata:
        raise ValueError(f"Strata not found in {strata_col}: {missing_strata}")

    # Calculate samples per bin based on sampling_dict
    samples_per_bin = {
        label: max(int(sample_size * prop), 0) for label, prop in sampling_dict.items()
    }

    # Distribute remaining samples to unspecified bins
    remainder = max(sample_size - sum(samples_per_bin.values()), 0)
    bin_counts = data[strata_col].value_counts()
    remaining_bins = bin_counts.index.difference(samples_per_bin.keys())
    if len(remaining_bins) > 0:
        remaining_samples = (
            (bin_counts[remaining_bins] / bin_counts[remaining_bins].sum() * remainder)
            .round()
            .astype(int)
        )
        samples_per_bin.update(remaining_samples.to_dict())

    # Sample from each bin
    sampled_data = pd.DataFrame()
    shortfall = 0
    for bin_label, n_samples in samples_per_bin.items():
        bin_data = data[data[strata_col] == bin_label]

        if n_samples <= 0:
            continue  # Skip bins with zero or negative sample sizes

        if len(bin_data) < n_samples:
            warnings.warn(
                f"Bin '{bin_label}' has fewer samples ({len(bin_data)}) than requested ({n_samples}). Using all available."
            )
            shortfall += n_samples - len(bin_data)

        bin_sample = bin_data.sample(
            n=min(max(n_samples, 0), len(bin_data)), random_state=random_state
        )
        sampled_data = pd.concat([sampled_data, bin_sample])

    # Compensate for shortfall if possible
    if shortfall > 0:
        unsampled_data = data[~data.index.isin(sampled_data.index)]
        extra_samples = unsampled_data.sample(
            n=min(shortfall, len(unsampled_data)), random_state=random_state
        )
        sampled_data = pd.concat([sampled_data, extra_samples])

    # Ensure final sample size matches request (or return all if not enough data)
    final_sample = sampled_data.sample(
        n=min(sample_size, len(sampled_data)), random_state=random_state
    )

    return final_sample.reset_index(drop=True)


def check_and_save_batch(batch, batch_name, directory="data/labeling/"):
    """
    Check if a batch already exists, compare it with the current batch,
    and save the current batch if it's different or doesn't exist.

    Args:
    batch (gpd.GeoDataFrame): The current batch to check and potentially save
    batch_name (str): The name of the batch (e.g., "batch1")
    directory (str): The directory to check for existing files and save new files

    Returns:
    str: The filename of the newly saved batch, or None if no new file was saved
    """
    batch = gpd.GeoDataFrame(batch)
    existing_files = [f for f in os.listdir(directory) if batch_name in f]

    if existing_files:
        latest_file = max(existing_files)
        existing_batch = gpd.read_feather(f"{directory}/{latest_file}")

        if not batch.qt_tile_id.equals(existing_batch.qt_tile_id):
            print(
                f"The tile ids in {batch_name} are not the same as the existing {batch_name}."
            )

            overwrite = input(
                f"Do you want to save {batch_name} to a new file? (y/n): "
            )
            if overwrite.lower() == "y":
                return save_batch(batch, batch_name, directory)
            else:
                print(f"The current {batch_name} has not been saved")
                return None
        else:
            print(
                f"The current {batch_name} is the same as the existing {batch_name}. Skipping saving"
            )
            return None
    else:
        return save_batch(batch, batch_name, directory)


def save_batch(batch, batch_name, directory):
    """Helper function to save the batch"""
    today = datetime.now().strftime("%Y-%m-%d")
    fn = f"{directory}/{batch_name}_{today}.feather"
    batch.to_feather(fn)
    print(f"The new {batch_name} has been saved at {fn}")
    return fn


def plot_histograms(full_data, batch_data, batch_name):
    plt.figure(figsize=(20, 6))

    # extract permit data from full_data
    permit_data = (
        full_data[["facilityid_list", "animal_units", "batch_name"]]
        .dropna()
        .explode("facilityid_list")
    )

    # First subplot
    plt.subplot(1, 3, 1)
    sns.histplot(
        data=full_data,
        x="animal_units_per_permit",
        hue="batch_name",
        multiple="stack",
        bins=50,
    )
    plt.xlabel("Animal units per permit")
    plt.ylabel("Frequency")
    plt.title("Animal units per permit per tile")

    # Second subplot
    plt.subplot(1, 3, 2)
    sns.histplot(
        data=batch_data,
        x="animal_units_per_permit",
        hue="animal_units_per_permit_q",
        multiple="stack",
        bins=50,
    )
    plt.xlabel("Animal units per permit per tile")
    plt.ylabel("Frequency")
    plt.title(f"{batch_name}: Animal units per permit per tile")

    # Third subplot
    plt.subplot(1, 3, 3)
    sns.histplot(
        data=permit_data,
        x="animal_units",
        hue="batch_name",
        multiple="stack",
        bins=100,
    )
    plt.xlabel("Animal units")
    plt.ylabel("Frequency")
    plt.title("Histogram of animal units per permit")

    # Adjust spacing between subplots
    plt.tight_layout()

    plt.show()
