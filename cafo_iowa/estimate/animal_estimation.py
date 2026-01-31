#animal_estimation.py
"""
This file defines the functions related to animal count estimtaion.
"""
import numpy as np
import pandas as pd
from scipy.stats import truncnorm
from cafo_iowa.estimate.constants import (
    DEAD_SPACE_FACTOR,
    DENSITY_K,
)
from cafo_iowa.utils.utils import convert_counts_to_animal_units


def truncnorm_rvs(min_val, max_val, mean, std, size):
    """Truncated normal random variable generator. Code courtesy of CAFO WI.
    Args:
        min_val: float, minimum value of the distribution
        max_val: float, maximum value of the distribution
        mean: float, mean of the distribution
        std: float, standard deviation of the distribution
        size: int, number of samples to generate
    Returns:
        np.array, samples from the truncated normal distribution
    """
    a, b = (min_val - mean) / std, (max_val - mean) / std
    return truncnorm.rvs(a, b, loc=mean, scale=std, size=size)

def prepare_weight_stats(weights):
    """
    Prepares weight statistics for sampling by converting from lbs to kgs.

    Args:
        weights (pd.DataFrame): A DataFrame containing weight columns and 'animal_type' column.
                              Required columns: avg_max_weight_lbs, avg_max_weight_sd_lbs

    Returns:
        pd.DataFrame: A DataFrame with weight statistics for each animal type:
                     - avg_max_weight_kgs: mean weight in kg
                     - avg_max_weight_sd_kgs: standard deviation of weight in kg
    """
    weights = weights.copy()

    # convert lbs to kgs
    weights["avg_max_weight_kgs"] = weights["avg_max_weight_lbs"] / 2.20462
    weights["avg_max_weight_sd_kgs"] = weights["avg_max_weight_sd_lbs"] / 2.20462

    return weights[["avg_max_weight_kgs", "avg_max_weight_sd_kgs"]]


def get_permit_animal_proportions(facility_row, animal_cols):
    """
    Computes the raw proportion of each animal type in a single permit/facility
    row based on reported counts.

    For example, if a row has 100 pigs and 100 piglets, the
    raw proportions will be {'pig': 0.5, 'piglet': 0.5}.

    Args:
        facility_row (pd.Series): A row from the facilities DataFrame,
                                  containing one facility's data.
        animal_cols (list): List of animal column names to consider.

    Returns:
        dict: A dictionary {animal_type: raw_proportion, ...}.
              If no animals are reported (all zero or NaN), returns an empty dict.
    """
    # Filter animals with positive (non-zero) counts
    reported_counts = {
        animal: facility_row[animal]
        for animal in animal_cols
        if pd.notna(facility_row[animal]) and facility_row[animal] > 0
    }
    if not reported_counts:
        return {}
    total_count = sum(reported_counts.values())
    raw_proportions = {
        animal: count / total_count for animal, count in reported_counts.items()
    }

    return raw_proportions

def sample_density_parameters(
    raw_proportions,
    weights,
    sample_size=1000,
    seed=40,
    density_scaling_factor=DENSITY_K,
):
    """
    Samples densities for animal types by first sampling weights and then calculating densities.

    Returns:
        dict[str, np.ndarray] of sampled densities
    """
    densities = weights.set_index("animal_type")
    missing_animals = [a for a in raw_proportions if a not in densities.index]
    if missing_animals:
        raise ValueError(
            f"Missing density values for animals: {', '.join(missing_animals)}."
        )

    np.random.seed(seed)

    # First sample weights for each animal type
    weight_samples = {
        a: np.random.normal(
            densities.loc[a, "avg_max_weight_kgs"],
            densities.loc[a, "avg_max_weight_sd_kgs"],
            sample_size,
        )
        for a in raw_proportions
    }

    # Then calculate densities from sampled weights
    return {
        a: 1 / (density_scaling_factor * weight_samples[a] ** 0.667)
        for a in raw_proportions
    }


def estimate_animal_units(
    facility_row,
    animal_cols,
    weights,
    dead_space_factor=DEAD_SPACE_FACTOR,
    seed=40,
    sample_size=1000
):
    """
    Estimates how many animals (of each type) can fit into a facility's barn.
    Always includes uncertainty calculations.

    Returns:
        (mean_estimates, animal_units_samples)
    """
    barn_area_sqm = facility_row["barn_area_sqm"]
    raw_proportions = get_permit_animal_proportions(facility_row, animal_cols)
    if not raw_proportions:
        return {}

    np.random.seed(seed)

    # Sample density parameters
    density_samples = sample_density_parameters(
        raw_proportions,
        weights,
        sample_size=sample_size,
        seed=seed,
    )
    animal_types = list(raw_proportions.keys())
    animal_counts_samples = {a: np.zeros(sample_size) for a in animal_types}

    # Sample dead space factor
    np.random.seed(seed)
    dead_space_std = 0.05 * dead_space_factor  # 5% of the mean
    dead_space_samples = np.random.normal(
        dead_space_factor, dead_space_std, sample_size
    )
    # Ensure dead space samples are between 0 and 1
    dead_space_samples = np.clip(dead_space_samples, 0, 1)

    # Calculate animal counts for each sample
    for i in range(sample_size):
        space_alloc_i = {
            a: raw_proportions[a] / density_samples[a][i] for a in animal_types
        }
        total_space_i = sum(space_alloc_i.values())

        for a in animal_types:
            fraction_of_barn = space_alloc_i[a] / total_space_i
            allocated_area = barn_area_sqm * fraction_of_barn
            animal_counts_samples[a][i] = (
                allocated_area * density_samples[a][i] * (1 - dead_space_samples[i])
            )

    # Convert counts to animal units
    animal_units_samples = {
        a: convert_counts_to_animal_units({a: animal_counts_samples[a]})[a]
        for a in animal_types
    }

    # Calculate mean estimates
    mean_estimates = {a: np.mean(animal_units_samples[a]) for a in animal_types}

    return mean_estimates, animal_units_samples
