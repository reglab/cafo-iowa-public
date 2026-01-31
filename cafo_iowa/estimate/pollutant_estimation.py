#pollutant_estimation.py
"""
This file contains the function used to estimate pollutants including enteric methane,
manure-related methane, volatile solides, nex, and indirect nitrous oxide.
"""
import numpy as np
import cafo_iowa.estimate.constants as c
from cafo_iowa.utils.utils import convert_animal_units_to_counts


def estimate_pollutants(
    facility_row,
    weights,
    animal_unit_col="reported_animal_units_dict",
    enteric_fermentation_factor=c.ENTERIC_FERMENTATION_FACTOR,
    vs_factors=c.VS_FACTORS,
    nex_factors=c.NEX_FACTORS,
    mcf_factors=c.MCF_FACTORS,
    methane_potential=c.METHANE_POTENTIAL,
    methane_density=c.METHANE_DENSITY,
    nitrogen_factors=c.NITROGEN_FACTORS,
    direct_n2o_ef=c.DIRECT_N2O_EF,
):
    """
    Estimate pollutants including CH4 enteric, CH4 manure, VS, NEX, and indirect N2O.
    
    :param facility_row: Row of facility table selected
    :param weights: Table of aninal weights
    :param animal_unit_col: Dictionary of permit animal numbers by animal type.
    :param enteric_fermentation_factor: Scalar for enteric fermentation emissions.
    :param vs_factors: Dictionary of volatile solids factors by animal type.
    :param nex_factors: Dictionary of nitrogen excretion factors by animal type.
    :param mcf_factors: Dictionary of methane conversion factors by system type.
    :param methane_potential: Maximum methane production capacity (per kg of VS excreted)
    :param methane_density: Conversion factor from m^3 to kg
    :param nitrogen_factors: Dictionary of nitrogen-related constants.
    :param direct_n2o_ef: Dictionary of emissions factors for nitrous oxide, by type of manure storage
    :return: Dictionary with polluant estimations for enteric methane, manure methane, excrete volatile solids, nex, direct nitrous oxide, and indirect nitrous oxide for the facility row.
    """

    if not isinstance(facility_row.get(animal_unit_col), dict):
        raise ValueError(
            f"Missing or invalid animal units for facility: {facility_row['facility_id']}"
        )

    pollutants = {
        "ch4_enteric": {},
        "ch4_manure": {},
        "vs_excreted": {},
        "nex": {},
        "dir_n2o": {},
        "ind_n2o": {},
    }

    for animal, animal_units in facility_row[animal_unit_col].items():
        animal_count = convert_animal_units_to_counts(facility_row[animal_unit_col])

        # convert lbs to kgs
        weight_row = weights.loc[weights["animal_type"] == animal, "TAM_lbs"] / 2.20462
        if weight_row.empty:
            raise ValueError(f"Missing weight data for animal type: {animal}")
        avg_weight = weight_row.iloc[0]

        wms_type = facility_row.get(
            "permit_wms_type", "other/unknown"
        )  # default to "other" if no wms type is provided
        mcf_factor = mcf_factors.get(
            wms_type, mcf_factors["other/unknown"]
        )  # default to "other" if no MCF factor is found

        # CH4 Enteric Emissions
        pollutants["ch4_enteric"][animal] = (
            animal_count[animal]
            * np.power(avg_weight / 72, 0.75)
            * enteric_fermentation_factor
            if enteric_fermentation_factor is not None
            else None
        )

        # Volatile Solids
        vs_factor = vs_factors.get(animal)
        pollutants["vs_excreted"][animal] = (
            animal_count[animal] * (avg_weight / 1000) * vs_factor * 365.25
            if vs_factor is not None
            else None
        )

        # CH4 Manure Emissions
        pollutants["ch4_manure"][animal] = (
            pollutants["vs_excreted"][animal]
            * methane_potential
            * mcf_factor
            * methane_density
            if (
                pollutants["vs_excreted"][animal] is not None
                and methane_potential is not None
                and mcf_factor is not None
                and methane_density is not None
            )
            else None
        )

        # Nitrogen Excretion
        nex_factor = nex_factors.get(animal)
        pollutants["nex"][animal] = (
            animal_count[animal] * (avg_weight / 1000) * nex_factor * 365.25
            if nex_factor is not None
            else None
        )

        # Direct N2O
        direct_n2o_ef_value = direct_n2o_ef.get(
            wms_type, direct_n2o_ef["other/unknown"]
        )
        pollutants["dir_n2o"][animal] = (
            pollutants["nex"][animal]
            * nitrogen_factors["N_conversion_factor"]
            * direct_n2o_ef_value
            if (
                pollutants["nex"][animal] is not None
                and direct_n2o_ef_value is not None
                and nitrogen_factors["N_conversion_factor"] is not None
            )
            else None
        )

        # Indirect N2O
        pollutants["ind_n2o"][animal] = (
            pollutants["nex"][animal]
            * nitrogen_factors["N_conversion_factor"]
            * (
                nitrogen_factors["N_runoff_ef"] * nitrogen_factors["N_runoff_fraction"]
                + nitrogen_factors["N_volatilization_ef"]
                * nitrogen_factors["N_volatilization_fraction"]
            )
            if (
                pollutants["nex"][animal] is not None
                and nitrogen_factors["N_conversion_factor"] is not None
                and nitrogen_factors["N_runoff_ef"] is not None
                and nitrogen_factors["N_runoff_fraction"] is not None
                and nitrogen_factors["N_volatilization_ef"] is not None
                and nitrogen_factors["N_volatilization_fraction"] is not None
            )
            else None
        )

    return pollutants
