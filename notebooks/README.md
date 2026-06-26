# Notebooks

This directory contains the Jupyter notebook used to produce all figures and analyses in the paper.

## Contents

**`Paper_Figures_Analysis.ipynb`** — primary analysis notebook. Loads facility-level data via functions in the `cafo_iowa` package, applies filters (e.g. wean-to-finish and grow-to-finish swine facilities), and generates all figures appearing in the paper.

## Dependencies

The notebook requires access to the full underlying dataset, which is stored in a private PostgreSQL database and includes fields (facility addresses, parcel ownership, parcel geometry) that are redacted in the public release. The public release table (`cafo_iowa_facilities_v1.csv`) and supporting tables are available on [HuggingFace](https://huggingface.co/datasets/reglab/cafo-iowa) and [Figshare](https://doi.org/10.6084/m9.figshare.32810540.v1).

For full replicability or additional research purposes, the complete unredacted dataset is available upon request.
