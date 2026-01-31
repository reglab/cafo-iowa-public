# Barns, Bunching, and Bias: Satellite Evidence of Strategic Under-Reporting in Iowa Swine CAFOs

This repository contains the code and data processing pipeline for analyzing Concentrated Animal Feeding Operations (CAFOs) in Iowa, with a focus on identifying potential under-reporting of animal capacity near regulatory thresholds.

## Project Overview

This project investigates strategic under-reporting in Iowa's swine CAFOs by:
1. Integrating multiple data sources (permits, parcel records, satellite imagery)
2. Creating an independent measure of animal capacity based on industry stocking densities and barn footprints
3. Analyzing patterns of under-reporting near regulatory thresholds
4. Estimating the impact on methane emissions accounting

## Data Sources

While this repository contains a `data/` directory, most data is stored and managed in a PostgreSQL database. The database must be set up before running the data processing pipeline. See the Setup section for database configuration instructions.

- **Permit Data**: [Iowa DNR CAFO Permits](https://www.arcgis.com/home/item.html?id=abfbd972640d4e87b6c48dc669775767)
- **NAIP Tiles**: High-resolution satellite imagery from USDA (obtained from Google Earth Engine)
- **Urban Areas**: Tiger Data, 2020 Census Urban Areas
- **Parcel Data**: County-level parcel records from Iowa counties (obtained from ReGrid)

## Project Structure

- `cafo_iowa/`: Main package containing data processing and analysis code
  - `data/`: Data ingestion and processing scripts
  - `db/`: Database models and session management
  - `utils/`: Utility functions
  - `estimate/`: CAFO facility clustering, animal capacity estimation, and pollution estimation code
- `notebooks/`: Jupyter notebooks for analysis and visualization
- `data/`: Raw and processed data storage
  - `permits/`: CAFO permit data
  - `parcels/`: Parcel records
  - `NAIP21QQ/`: NAIP satellite imagery
  - `annotations/`: Hand-labeled barn annotations
  - `urban_areas/`: Urban area boundaries
  - `census/`: Census tract data

## Setup

1. Database Configuration:
   Create a `.env` file in the root directory with:
   ```
   PGUSER="your user name"
   PGPASSWORD="your password"
   PGHOST="your host"
   PGDATABASE="your database"
   PGPORT="your port"
   ```

2. Google Cloud Setup:
   - Download the Google service account JSON file
   - Update the path in `config.yaml` (default is root directory)

3. Install Dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Data Processing Pipeline

1. **Image Ingestion** (`cafo_iowa/data/img_ingest.py`):
   - Initializes Google Earth Engine connection
   - Exports NAIP tiles to Google Cloud Platform
   - Manages satellite imagery downloads
   - Handles image export and storage

2. **Image Processing** (`cafo_iowa/data/img_process.py`):
   - Downloads NAIP satellite imagery (0.6m resolution, 4-band)
   - Divides Iowa's 4,239 NAIP tiles into 16,956 quartered tiles
   - Processes and tiles images
   - Masks urban areas
   - Converts to appropriate formats

3. **Data Ingestion** (`cafo_iowa/data/ingest.py`):
   - Imports raw data from various sources
   - Standardizes formats and coordinates
   - Stores in raw database tables

4. **Data Processing** (`cafo_iowa/data/process.py`):
   - Cleans and standardizes data
   - Creates relationships between permits, parcels, and facilities
   - Processes annotations and creates barn clusters
   - Generates final processed tables

5. **Animal Capacity Estimation** (`cafo_iowa/estimate/estimate.py`):
   - Calculates animal capacity based on barn footprints
   - Estimates animal units with uncertainty bounds
   - Computes pollutant emissions (methane, nitrogen)
   - Generates facility-level statistics
   - Supports analysis of under-reporting patterns

## Database Structure

The database is organized into two main schemas:
- `raw`: Contains unprocessed data from various sources
- `processed`: Contains cleaned and processed data with established relationships

Database migrations are managed using Alembic, with migration scripts located in `cafo_iowa/db/migrations/`. To apply migrations:

```bash
alembic upgrade head
```

Key tables include:
- `permits`: CAFO permit information from Iowa DNR
- `parcels`: Land parcel records from ReGrid
- `cf_annotations`: Hand-labeled barn annotations from satellite imagery
- `barns`: `cf_annotations` that are combined into single barn structures
- `barn_clusters`: Groups of nearby barns
- `facilities`:
  - permitted CAFO facilities created by:
    1. Assigning barns to containing parcels
    2. Linking parcels to DNR permits through:
       - Spatial matching (permit point within parcel)
       - Ownership matching (fuzzy match within 1km radius)
      3. Assigning remaining barns to nearest permit within 500m
  - unpermitted CAFO facilities are parcels that contain barns, but that are not within close proximity to a DNR permit

## Usage

1. Ingest raw data:
   ```bash
   python -m cafo_iowa.data.ingest --data_sources all
   ```

2. Process images:
   ```bash
   python -m cafo_iowa.data.img_process
   ```

3. Process data:
   ```bash
   python -m cafo_iowa.data.process --data_sources all
   ```

## Citation

If you use this code in your research, please cite:
```
@article{frey2024barns,
  title={Barns, Bunching, and Bias: Satellite Evidence of Strategic Under-Reporting in Iowa Swine CAFOs},
  author={Frey, Arun and Lyng-Olsen, Helena and Ho, Daniel E},
  journal={Working Paper},
  year={2024}
}
```

## License

This project is licensed under the terms of the included LICENSE file.
