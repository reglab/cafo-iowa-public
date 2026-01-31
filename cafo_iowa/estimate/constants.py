#constants.py
"""
This file contains constants used throughout our library. Source is the EPA's
2023 US Greenhouse Gas Inventory unless otherwise specified.
"""

"""
Animal Unit Estimation Constants
"""

# Fraction of barn space that is unusable
DEAD_SPACE_FACTOR = 0.12

# Scaling factor in the density calculation
DENSITY_K = 0.03

ANIMAL_TYPES = [
    "cattle_bee",
    "cattle_b_1",
    "immature_d",
    "mature_dai",
    "cattle_dai",
    "cattle_vea",
    "chicken_la",
    "chicken_pu",
    "cow_calf",
    "ducks",
    "fish___25",
    "fish_____2",
    "goats",
    "horses",
    "turkey_fin",
    "turkey_pou",
    "sheep_and",
    "swine_gest",
    "swine_gilt",
    "swine_grow",
    "swine_nurs",
    "swine_sow",
    "swine_wean",
]

# Sources can be found in the Google Drive Folder tk
ANIMAL_DENSITY_CONSTANTS = {  
    "chicken_la": 7,
    "chicken_pu": 7,
    "ducks": 5,
    "goats": 1 / 1.5,
    "horses": 1 / 3.95,
    "turkey_fin": 5,
    "turkey_pou": 5,
}

# Source: Iowa Department of Natural Resources Animal Conversion Worksheet https://www.iowadnr.gov/Portals/idnr/uploads/forms/5420020.pdf
ANIMAL_TYPE_UNITS_CONVERSION = (
    {  
        "cattle_bee": 1,
        "cattle_b_1": 1,
        "immature_d": 1,
        "mature_dai": 1.4,
        "cattle_dai": 1,
        "cattle_vea": 1,
        "chicken_la": 0.01,
        "chicken_pu": 0.0025,
        "cow_calf": 1, 
        "ducks": 0.04,
        "fish___25": 0.001,
        "fish_____2": 0.00006,
        "goats": 0.1,
        "horses": 2,
        "turkey_fin": 0.018,
        "turkey_pou": 0.0085,
        "sheep_and": 0.1,
        "swine_gest": 0.4,
        "swine_gilt": 0.4,
        "swine_grow": 0.4,
        "swine_nurs": 0.1,
        "swine_sow": 0.4,
        "swine_wean": 0.4,
    }
)
"""
Pollutant Estimation Constants
"""
# Scalar for enteric fermentation emissions
ENTERIC_FERMENTATION_FACTOR = 1.5  

# Conversion factor from m^3 to kg
METHANE_DENSITY = 0.662  

# Maximum methane production capacity (per kg of VS excreted)
METHANE_POTENTIAL = 0.48  

 # MCF factors by system type, in Iowa. Source: Inventory for U.S. Greeenhouse Emissions and Sinks 2023
MCF_FACTORS = { 
    "anaerobic_storage": 0.70,
    "pit_storage": 0.26,
    "slurry_storage": 0.26,
    "other/unknown": 0.26,
}

# These are national constants based on the EPA Inventory for U.S. Greeenhouse Emissions and Sinks, 2023. 
# These values are from the "Midwest" region of the document specifically.
NITROGEN_FACTORS = {
    "N_volatilization_fraction": 0.34,
    "N_runoff_fraction": 0.0,
    "N_volatilization_ef": 0.01,
    "N_runoff_ef": 0.0075,
    "N_conversion_factor": 44 / 28,
}

# Source: CH4 and N2O Emissions from Manure, IPCC 2006, cited in 2023 US GHG Inventory, EPA, Table A-169
DIRECT_N2O_EF = { 
    "anaerobic_storage": 0.001,  
    "pit_storage": 0.002,
    "slurry_storage": 0.005,
    "other/unknown": 0.002  # If unknown or other, default to pit storage since its by far the most common
}


def convert_cattle_values(kg_per_animal_per_year):
    """
    Convert kg per animal per year to kg per 1000 total animal mass per day.
    Assumes that the average weight of a cow is 1000 kg.
    Assumes that one year is 365.25 days.
    """
    return (
        kg_per_animal_per_year / 365.25 if kg_per_animal_per_year is not None else None
    )


VS_FACTORS = {
    "cattle_bee": convert_cattle_values(1587),
    "cattle_b_1": convert_cattle_values(991),
    "immature_d": convert_cattle_values(1255),
    "mature_dai": convert_cattle_values(2929),
    "cattle_dai": convert_cattle_values(2929),
    "cattle_vea": 7.7,
    "chicken_la": 10.2,
    "chicken_pu": 10.2,
    "cow_calf": 7.7,
    "ducks": None,
    "fish___25": None,
    "fish_____2": None,
    "goats": 9.5,
    "horses": 6.1,
    "turkey_fin": 8.5,
    "turkey_pou": 8.5,
    "sheep_and": 8.3,
    "swine_gest": 2.7,
    "swine_gilt": 2.7,
    "swine_grow": 5.4,
    "swine_nurs": 8.8,
    "swine_sow": 5.4,
    "swine_wean": 5.4,
}

NEX_FACTORS = {
    "cattle_bee": convert_cattle_values(75),
    "cattle_b_1": convert_cattle_values(48),
    "immature_d": convert_cattle_values(69),
    "mature_dai": convert_cattle_values(162),
    "cattle_dai": convert_cattle_values(162),
    "cattle_vea": 0.45,
    "chicken_la": 0.79,
    "chicken_pu": 0.79,
    "cow_calf": 0.45,
    "ducks": None,
    "fish___25": None,
    "fish_____2": None,
    "goats": 0.45,
    "horses": 0.25,
    "turkey_fin": 0.63,
    "turkey_pou": 0.63,
    "sheep_and": 0.45,
    "swine_gest": 0.20,
    "swine_gilt": 0.20,
    "swine_grow": 0.54,
    "swine_nurs": 0.92,
    "swine_sow": 0.54,
    "swine_wean": 0.54,
}