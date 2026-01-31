# estimate.py
"""
This file defines the "load_and_process_facilities" function, which drives the animal count and methane estimation.
"""
import logging

import click
import geopandas as gpd
import numpy as np
import pandas as pd

import cafo_iowa.db.session as s
import cafo_iowa.estimate.constants as c
from cafo_iowa.estimate.animal_estimation import (
    estimate_animal_units,
    prepare_weight_stats,
)
from cafo_iowa.estimate.get_facilities_data import get_facilities
from cafo_iowa.estimate.pollutant_estimation import estimate_pollutants

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def load_and_process_facilities(
    dead_space_factor=c.DEAD_SPACE_FACTOR,
    density_scaling_factor=c.DENSITY_K,
    enteric_fermentation_factor=c.ENTERIC_FERMENTATION_FACTOR,
    vs_factors=c.VS_FACTORS,
    nex_factors=c.NEX_FACTORS,
    mcf_factors=c.MCF_FACTORS,
    methane_potential=c.METHANE_POTENTIAL,
    methane_density=c.METHANE_DENSITY,
    nitrogen_factors=c.NITROGEN_FACTORS,
) -> pd.DataFrame:
    """
    Loads facility data, calculates animal density, animal units,
    and pollutant estimates, and returns the updated DataFrame.

    :param density_scaling_factor: Factor used for stocking density calculation.
    :param dead_space_factor: Fraction of barn space that is unusable.
    :param enteric_fermentation_factor: Scalar for enteric fermentation emissions.
    :param vs_factors: Dictionary of volatile solids factors by animal type.
    :param nex_factors: Dictionary of nitrogen excretion factors by animal type.
    :param mcf_factors: Dictionary of methane conversion factors by system type.
    :param nitrogen_factors: Dictionary of nitrogen-related constants.
    :return: A pandas DataFrame (or GeoDataFrame) with processed facility information.
    """

    # Load data
    facilities: gpd.GeoDataFrame = get_facilities()
    if facilities.empty:
        logger.warning("No facilities were loaded. Check your data source.")
    else:
        logger.info(f"Number of facilities loaded: {len(facilities)}")

    # Load weights
    weights: pd.DataFrame = pd.read_sql(
        "SELECT * FROM processed.animal_weights", con=s.get_engine()
    )
    if weights.empty:
        logger.warning("No animal weights were loaded. Check your database table.")

    # Prepare weight statistics for sampling
    weight_stats = prepare_weight_stats(weights)
    weights["avg_max_weight_kgs"] = weight_stats["avg_max_weight_kgs"]
    weights["avg_max_weight_sd_kgs"] = weight_stats["avg_max_weight_sd_kgs"]

    # Estimate animal units with uncertainty
    facilities[
        [
            "estimated_animal_units_dict",
            "estimated_animal_units_samples",
        ]
    ] = facilities.apply(
        lambda row: estimate_animal_units(
            row,
            animal_cols=weights["animal_type"],
            weights=weights,
            dead_space_factor=dead_space_factor,
        ),
        axis=1,
        result_type="expand",
    )

    # Calculate total animal units
    facilities["estimated_animal_units"] = facilities[
        "estimated_animal_units_dict"
    ].apply(lambda x: sum(x.values()) if isinstance(x, dict) else 0)

    #Preserves dictionary characteristic of the samples
    facilities["estimated_animal_units_samples_dict"] = facilities["estimated_animal_units_samples"]

    # Calculate bounds for each key in the dictionary
    def calculate_bounds(sample_dict, percentile=2.5):
        """Calculate percentiles for each sample in the dictionary."""
        if isinstance(sample_dict, dict):
            return {
                key: np.percentile(values, percentile) if len(values) > 0 else 0
                for key, values in sample_dict.items()
            }
        else:
            return {}

    facilities["estimated_animal_units_lower_dict"] = facilities[
        "estimated_animal_units_samples_dict"
    ].apply(lambda x: calculate_bounds(x, 2.5))

    facilities["estimated_animal_units_upper_dict"] = facilities[
        "estimated_animal_units_samples_dict"
    ].apply(lambda x: calculate_bounds(x, 97.5))


    # Calculate total samples
    facilities["estimated_animal_units_samples"] = facilities[
        "estimated_animal_units_samples"
    ].apply(
        lambda x: (
            np.sum([np.array(v) for v in x.values()], axis=0)
            if isinstance(x, dict)
            else np.array([])
        )
    )

    # Calculate bounds from the total samples
    facilities["estimated_animal_units_lower"] = facilities[
        "estimated_animal_units_samples"
    ].apply(lambda x: np.percentile(x, 2.5) if len(x) > 0 else 0)
    facilities["estimated_animal_units_upper"] = facilities[
        "estimated_animal_units_samples"
    ].apply(lambda x: np.percentile(x, 97.5) if len(x) > 0 else 0)

    # Estimate pollutants
    facilities["reported_pollutants_dict"] = facilities.apply(
        lambda row: estimate_pollutants(
            row,
            animal_unit_col="reported_animal_units_dict",
            weights=weights,
            enteric_fermentation_factor=enteric_fermentation_factor,
            vs_factors=vs_factors,
            nex_factors=nex_factors,
            mcf_factors=mcf_factors,
            methane_potential=methane_potential,
            methane_density=methane_density,
            nitrogen_factors=nitrogen_factors,
        ),
        axis=1,
    )
    facilities["estimated_pollutants_dict"] = facilities.apply(
        lambda row: estimate_pollutants(
            row,
            animal_unit_col="estimated_animal_units_dict",
            weights=weights,
            enteric_fermentation_factor=enteric_fermentation_factor,
            vs_factors=vs_factors,
            nex_factors=nex_factors,
            mcf_factors=mcf_factors,
            nitrogen_factors=nitrogen_factors,
        ),
        axis=1,
    )

    facilities["estimated_pollutants_lower"] = facilities.apply(
        lambda row: estimate_pollutants(
            row,
            animal_unit_col="estimated_animal_units_lower_dict",
            weights=weights,
            enteric_fermentation_factor=enteric_fermentation_factor,
            vs_factors=vs_factors,
            nex_factors=nex_factors,
            mcf_factors=mcf_factors,
            nitrogen_factors=nitrogen_factors,
        ),
        axis=1,
    )

    facilities["estimated_pollutants_upper"] = facilities.apply(
        lambda row: estimate_pollutants(
            row,
            animal_unit_col="estimated_animal_units_upper_dict",
            weights=weights,
            enteric_fermentation_factor=enteric_fermentation_factor,
            vs_factors=vs_factors,
            nex_factors=nex_factors,
            mcf_factors=mcf_factors,
            nitrogen_factors=nitrogen_factors,
        ),
        axis=1,
    )

    # Summarize pollutant estimates
    pollutant_cols = [
        "ch4_enteric",
        "ch4_manure",
        "vs_excreted",
        "nex",
        "dir_n2o",
        "ind_n2o",
    ]

    for col in pollutant_cols:
        facilities[f"reported_{col}"] = facilities["reported_pollutants_dict"].apply(
            lambda p: (
                sum((v for v in (p.get(col) or {}).values() if v is not None))
                if isinstance(p, dict)
                else 0
            )
        )
        facilities[f"estimated_{col}"] = facilities["estimated_pollutants_dict"].apply(
            lambda p: (
                sum((v for v in (p.get(col) or {}).values() if v is not None))
                if isinstance(p, dict)
                else 0
            )
        )
        facilities[f"estimated_lower_{col}"] = facilities["estimated_pollutants_lower"].apply(
            lambda p: (
                sum((v for v in (p.get(col) or {}).values() if v is not None))
                if isinstance(p, dict)
                else 0
            )
        )
        facilities[f"estimated_upper_{col}"] = facilities["estimated_pollutants_upper"].apply(
            lambda p: (
                sum((v for v in (p.get(col) or {}).values() if v is not None))
                if isinstance(p, dict)
                else 0
            )
        )

    facilities["reported_ch4_total"] = (
        facilities["reported_ch4_enteric"] + facilities["reported_ch4_manure"]
    )
    facilities["estimated_ch4_total"] = (
        facilities["estimated_ch4_enteric"] + facilities["estimated_ch4_manure"]
    )
    facilities["estimated_ch4_total_lower"] = (
        facilities["estimated_lower_ch4_enteric"] + facilities["estimated_lower_ch4_manure"]
    )
    facilities["estimated_ch4_total_upper"] = (
        facilities["estimated_upper_ch4_enteric"] + facilities["estimated_upper_ch4_manure"]
    )
    facilities["reported_n2o_total"] = (
        facilities["reported_dir_n2o"] + facilities["reported_ind_n2o"]
    )
    facilities["estimated_n2o_total"] = (
        facilities["estimated_dir_n2o"] + facilities["estimated_ind_n2o"]
    )

    return facilities


@click.command()
@click.option(
    "--output",
    "-o",
    default="output/data/facilities_processed.csv",
    type=click.Path(writable=True, dir_okay=False),
    help="Path to save the processed CSV file (default: output/data/facilities_processed.csv).",
)
@click.option(
    "--uncertainty",
    "-u",
    is_flag=True,
    help="Include uncertainty calculations in the output.",
)
def main(output: str, uncertainty: bool):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Starting facility data processing...")

    results = load_and_process_facilities()
    results.to_csv(output, index=False)
    logger.info(f"Processed data saved to {output}")


if __name__ == "__main__":
    # Delegate to the Click command
    main()
