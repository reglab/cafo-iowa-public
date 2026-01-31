import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

import cafo_iowa.db.models as m
import cafo_iowa.db.session as s


def select_columns(
    data: gpd.GeoDataFrame, model: m.Base, other_cols=True
) -> pd.DataFrame:
    """Select columns that are present in the database model and prepare data for upload."""
    table_cols = inspect(model).columns.keys()
    data_cols = [col for col in table_cols if col in data.columns]
    data_table = data[data_cols].copy()

    if other_cols:
        other_cols = (
            data.drop(columns=data_cols)
            .replace({np.nan: None})
            .to_dict(orient="records")
        )
        data_table["other_cols"] = other_cols

    return data_table


def insert_and_update(session, data, model, chunk_size=10000):
    """
    Efficiently insert or update records in the database using PostgreSQL's ON CONFLICT clause.
    This function handles large datasets efficiently by processing data in chunks.

    Parameters:
    - session: SQLAlchemy session object.
    - data: Pandas DataFrame containing the data to insert or update.
    - model: SQLAlchemy ORM model representing the target table.
    - chunk_size: Number of records to process in each batch (default is 10,000).
    """
    if "id" not in data.columns:
        raise ValueError("Data must contain an 'id' column.")

    try:
        total_records = len(data)
        num_chunks = (total_records // chunk_size) + 1

        for i in range(num_chunks):
            chunk = data.iloc[i * chunk_size : (i + 1) * chunk_size]
            if chunk.empty:
                continue

            records = chunk.to_dict(orient="records")

            insert_stmt = insert(model.__table__).values(records)

            # Exclude 'id' from the update set to prevent overwriting primary key
            update_columns = {c.name: c for c in insert_stmt.excluded if c.name != "id"}

            on_conflict_stmt = insert_stmt.on_conflict_do_update(
                index_elements=["id"], set_=update_columns
            )

            session.execute(on_conflict_stmt)

        session.commit()
        logging.info(f"Upserted {total_records} entries into {model.__tablename__}.")

    except Exception as e:
        session.rollback()
        logging.error(f"An error occurred during insert/update: {e}")
        raise


def refresh_table(session: Session, data, model, chunk_size=10000):
    """
    Fully refreshes a table using a staging-and-swap approach

    Steps:
    1. Create a staging table identical to the original table (including schema).
    2. Insert all rows from `data` into the staging table in chunks.
    3. In a single transaction, drop the original table and rename the staging table.

    Parameters:
    - session: SQLAlchemy Session object.
    - data: Pandas DataFrame containing the new data.
    - model: SQLAlchemy ORM model representing the original table.
    - chunk_size: Number of records to process in each batch (default is 10,000).
    """
    processed_table_name = model.__tablename__
    staging_table_name = f"{processed_table_name}_staging"

    # Determine the schema of the table.
    processed_schema = model.__table__.schema

    if processed_schema is None:
        logging.warning(
            f"Schema not specified for table {processed_table_name}. Using 'public' schema."
        )

    if "id" not in data.columns:
        raise ValueError("Data must contain an 'id' column.")

    try:
        total_records = len(data)
        num_chunks = (total_records // chunk_size) + 1

        # Begin a transaction
        session.begin()

        # 1. Create the staging table with the same structure as the original table
        session.execute(
            text(
                f"DROP TABLE IF EXISTS {processed_schema}.{staging_table_name} CASCADE;"
            )
        )
        session.execute(
            text(
                f"CREATE TABLE {processed_schema}.{staging_table_name} "
                f"(LIKE {processed_schema}.{processed_table_name} INCLUDING ALL);"
            )
        )

        # Flush ensures the CREATE TABLE is executed and visible in the current transaction
        session.flush()

        # Reflect the staging table to get a proper SQLAlchemy Table object
        connection = session.connection()
        metadata = MetaData()
        metadata = MetaData()
        staging_table = Table(
            staging_table_name,
            metadata,
            schema=processed_schema,
            autoload_with=connection,
        )

        # 2. Insert data into the staging table in chunks.
        for i in range(num_chunks):
            chunk = data.iloc[i * chunk_size : (i + 1) * chunk_size]
            if chunk.empty:
                continue
            records = chunk.to_dict(orient="records")
            insert_stmt = insert(staging_table).values(records)
            session.execute(insert_stmt)

        # ANALYZE the staging table for performance
        session.execute(text(f"ANALYZE {processed_schema}.{staging_table_name};"))

        # 3. Swap the tables
        session.execute(
            text(f"DROP TABLE {processed_schema}.{processed_table_name} CASCADE;")
        )
        session.execute(
            text(
                f"ALTER TABLE {processed_schema}.{staging_table_name} RENAME TO {processed_table_name};"
            )
        )

        # Commit the transaction so all changes happen atomically
        session.commit()

        logging.info(
            f"Full refresh completed. Inserted {total_records} entries into {processed_schema}.{processed_table_name}."
        )

    except Exception as e:
        session.rollback()
        logging.error(f"An error occurred during full refresh: {e}")
        raise


def delete_all_rows_from_table(table_class, session=None):
    """
    Deletes all rows from the specified table using the provided session.

    Parameters:
    session (Session): The SQLAlchemy session.
    table_class (DeclarativeMeta): The SQLAlchemy ORM table class.
    """

    if session is None:
        session = s.get_session()

    try:
        # Delete all rows from the table
        session.query(table_class).delete()

        # Commit the changes
        session.commit()
        print(
            f"All rows from the table '{table_class.__tablename__}' have been deleted."
        )
    except Exception as e:
        session.rollback()
        print(f"An error occurred: {e}")


def check_if_table_exists(schema_name: str, table_name: str, session=None, engine=None):

    if engine is None:
        engine = s.get_engine()

    if session is None:
        session = s.get_session()

    # CHECK IF TABLE EXISTS
    inspector = Inspector.from_engine(engine)
    if inspector.has_table(table_name, schema=schema_name):
        return True
    else:
        return False


def drop_table_if_exists(schema_name: str, table_name: str, session=None):

    if session is None:
        session = s.get_session()

    if check_if_table_exists(schema_name, table_name, session):
        session.execute(text(f"DROP TABLE IF EXISTS {schema_name}.{table_name}"))
        logging.info(f"Dropped table {schema_name}.{table_name}")
    else:
        logging.info(f"Table {schema_name}.{table_name} does not exist.")
    session.commit()
