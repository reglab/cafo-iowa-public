To set up the SQL database and ingest and process all images, do the following:

1. Make sure you have a database set up (ideally in LCR).
2. Specify your database connection in .env file
3. Create "raw" and "processed" schemas in database.
4. run `ssh -NT -L 55551:localhost:5432 lcr` to connect to LCR, where `55551` is the local port, and `5432` is the lcr port
5. Run `alembic revision --autogenerate "init db setup"` to set up all DB tables specified in `cafo_iowa/db/models.py`
6. Alembic doesnt work with geoalchemy2, so you have to add `import geoalchemy2` to the migration file prior to running the next line.
7. Run `alembic upgrade head` to generate all empty tables
8. Populate raw DB tables by running `cafo_iowa/data/ingest_data.py`
9. Populate processed DB tables by running `cafo_iowa/data/process_data.py`
10. Ingest raw NAIP images to GCP by running `cafo_iowa/data/ingest_imgs.py`
11. Process NAIP images by running `cafo_iowa/data/process_imgs.py`. Note, you want to be in LCR to run this, otherwise all images get downloaded locally. By default, only 10 images get downloaded when running script locally.
