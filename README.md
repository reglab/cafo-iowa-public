# Hidden Herds: Satellite Evidence of Threshold Gaming Under the Clean Water Act

This repository contains the code for *Hidden Herds: Satellite Evidence of Threshold Gaming Under the Clean Water Act* (Lyng-Olsen, Frey, Cook, Hollingshead, Eneva, and Ho, submitted 2026).

The paper investigates whether Iowa swine CAFO operators strategically report animal unit counts below the 1,000 AU threshold that triggers federal Clean Water Act permitting requirements. We estimate animal populations from satellite-detected barn footprints using NAIP 2021 imagery and manual annotation, then compare against counts self-reported to the Iowa DNR.

## Dataset

The public release dataset is available on HuggingFace and Figshare:

- **HuggingFace:** [huggingface.co/datasets/reglab/cafo-iowa](https://huggingface.co/datasets/reglab/cafo-iowa)
- **Figshare:** [doi.org/10.6084/m9.figshare.32810540.v1](https://doi.org/10.6084/m9.figshare.32810540.v1)

The release table (`cafo_iowa_facilities_v1.csv`) contains 6,525 Iowa wean-to-finish and grow-to-finish swine facilities with satellite-detected barns, including reported and estimated animal unit counts, underreporting estimates, and facility centroids. Full raw and processed supporting tables are also available. Facility addresses, parcel owner names, and parcel geometries are redacted; the complete unredacted dataset is available for research purposes upon request.

## Repository Structure

- `cafo_iowa/` — main Python package
  - `db/` — database models and session management
  - `estimate/` — facility construction, animal unit estimation, and pollutant estimation
  - `utils/` — utility functions
- `notebooks/` — analysis notebook that produces all paper figures
- `src/` — additional source code

## Setup

```bash
pip install -r requirements.txt
pip install -e .
```

The analysis requires access to a PostgreSQL database configured via a `.env` file:

```
PGUSER=...
PGPASSWORD=...
PGHOST=...
PGDATABASE=...
PGPORT=...
```

See `notebooks/README.md` for details on notebook dependencies and data access.

## Citation

```bibtex
@misc{lyngolsen2026hiddenherds,
  title        = {Hidden Herds: Satellite Evidence of Threshold Gaming Under the Clean Water Act},
  author       = {Lyng-Olsen, Helena and Frey, Arun and Cook, Evan and Hollingshead, Victoria and Eneva, Elena and Ho, Daniel E.},
  year         = {2026},
  doi          = {10.6084/m9.figshare.32810540.v1},
  url          = {https://doi.org/10.6084/m9.figshare.32810540.v1},
  note         = {Submitted for review. Lead authors Helena Lyng-Olsen and Arun Frey contributed equally.}
}
```

## License

Code in this repository is licensed under the terms of the included LICENSE file. The dataset is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
