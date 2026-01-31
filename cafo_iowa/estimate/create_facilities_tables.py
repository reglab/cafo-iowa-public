#create_facilities_table.py
"""
This file creates the facilities table in our database
"""
import time
from contextlib import contextmanager
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
import cafo_iowa.db.session as s

pd.set_option("display.max_columns", None)


@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    session = s.get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def drop_facility_foreign_key_constraints():
    """Drop foreign key constraints related to the facilities table."""
    with get_db_session() as session:
        try:
            execute_with_retry(
                session,
                """
                DO $$
                BEGIN
                    -- Drop foreign key constraints
                    ALTER TABLE IF EXISTS processed.barns DROP CONSTRAINT IF EXISTS fk_barns_facility;
                    ALTER TABLE IF EXISTS processed.permits DROP CONSTRAINT IF EXISTS fk_permits_facility;
                    ALTER TABLE IF EXISTS processed.parcels DROP CONSTRAINT IF EXISTS fk_parcels_facility;
                    ALTER TABLE IF EXISTS processed.barnclusters DROP CONSTRAINT IF EXISTS fk_barnclusters_facility;
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS fk_facilities_near_permits_facility;

                    -- Drop constraints with the actual names from the database
                    ALTER TABLE IF EXISTS processed.parcels DROP CONSTRAINT IF EXISTS parcels_facility_id_fkey;
                    ALTER TABLE IF EXISTS processed.permits DROP CONSTRAINT IF EXISTS permits_facility_id_fkey;
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS facilities_near_permits_facility_id_fkey;
                END $$;
                """,
            )
            print("Dropped facility foreign key constraints")
        except Exception as e:
            print(f"Error while dropping foreign key constraints: {e}")


def add_facility_foreign_key_constraints():
    """Add foreign key constraints related to the facilities table."""
    with get_db_session() as session:
        try:
            execute_with_retry(
                session,
                """
                DO $$
                BEGIN
                    -- Check if constraints exist before adding them
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'parcels_facility_id_fkey'
                    ) THEN
                        ALTER TABLE processed.parcels
                        ADD CONSTRAINT parcels_facility_id_fkey
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'permits_facility_id_fkey'
                    ) THEN
                        ALTER TABLE processed.permits
                        ADD CONSTRAINT permits_facility_id_fkey
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_barnclusters_facility'
                    ) THEN
                        ALTER TABLE processed.barnclusters
                        ADD CONSTRAINT fk_barnclusters_facility
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_barns_facility'
                    ) THEN
                        ALTER TABLE processed.barns
                        ADD CONSTRAINT fk_barns_facility
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'facilities_near_permits_facility_id_fkey'
                    ) THEN
                        ALTER TABLE processed.facilities_near_permits
                        ADD CONSTRAINT facilities_near_permits_facility_id_fkey
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;
                END $$;
                """,
            )
            print("Added facility foreign key constraints")
        except Exception as e:
            print(f"Error while adding foreign key constraints: {e}")


def execute_with_retry(session, query, params=None, max_retries=3):
    """Execute a query with retry logic for connection issues."""
    for attempt in range(max_retries):
        try:
            result = session.execute(
                text(query) if isinstance(query, str) else query, params
            )
            session.commit()
            return result
        except OperationalError as e:
            if (
                "SSL connection has been closed unexpectedly" in str(e)
                and attempt < max_retries - 1
            ):
                print(
                    f"Connection lost, retrying... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(1 * (attempt + 1))  # Exponential backoff
                continue
            raise
        except Exception as e:
            session.rollback()
            raise


def create_facilities_table():
    """Create the facilities table with basic structure."""
    with get_db_session() as session:
        try:
            # First, remove foreign key constraints if they exist
            drop_facility_foreign_key_constraints()

            # Drop the existing facilities table if it exists
            execute_with_retry(session, "DROP TABLE IF EXISTS processed.facilities;")

            # Create the facilities table
            query = """
                CREATE TABLE processed.facilities AS
                WITH RECURSIVE parcel_connections AS (
                    -- All direct connections via barn_cluster or permit
                    SELECT DISTINCT bcp1.parcel_id AS parcel_1, bcp2.parcel_id AS parcel_2
                    FROM processed.barnclusterparcels bcp1
                    JOIN processed.barnclusterparcels bcp2 ON bcp1.barn_cluster_id = bcp2.barn_cluster_id
                    WHERE bcp1.parcel_id < bcp2.parcel_id

                    UNION

                    SELECT DISTINCT pp1.parcel_id AS parcel_1, pp2.parcel_id AS parcel_2
                    FROM processed.permit_parcels pp1
                    JOIN processed.permit_parcels pp2 ON pp1.permit_id = pp2.permit_id
                    WHERE pp1.parcel_id < pp2.parcel_id
                ),

                connected_groups AS (
                    -- Seed with all parcels involved in permits or barnclusters
                    SELECT parcel_id, ARRAY[parcel_id] AS group_parcels
                    FROM (
                        SELECT parcel_id FROM processed.permit_parcels
                        UNION
                        SELECT parcel_id FROM processed.barnclusterparcels
                    ) AS base_parcels

                    UNION ALL

                    SELECT cg.parcel_id, array_append(cg.group_parcels,
                        CASE
                            WHEN pc.parcel_1 = ANY(cg.group_parcels) THEN pc.parcel_2
                            ELSE pc.parcel_1
                        END)
                    FROM connected_groups cg
                    JOIN parcel_connections pc
                    ON (pc.parcel_1 = ANY(cg.group_parcels) AND NOT pc.parcel_2 = ANY(cg.group_parcels))
                    OR (pc.parcel_2 = ANY(cg.group_parcels) AND NOT pc.parcel_1 = ANY(cg.group_parcels))
                ),

                final_groups AS (
                    SELECT DISTINCT ON (parcel_id)
                        parcel_id,
                        group_parcels,
                        (
                            SELECT string_agg(id::text, ',' ORDER BY id)
                            FROM unnest(group_parcels) AS id
                        ) AS group_key
                    FROM connected_groups
                    ORDER BY parcel_id, array_length(group_parcels, 1) DESC
                ),

                facilities AS (
                    SELECT
                        md5(group_key) AS facility_id,
                        ST_Union(p.geometry) AS geometry
                    FROM final_groups fg
                    JOIN processed.parcels p ON p.id = ANY(fg.group_parcels)
                    GROUP BY group_key
                )

                SELECT * FROM facilities;
            """

            start_time = time.time()
            execute_with_retry(session, query)
            print(f"Facilities table created in {time.time() - start_time:.2f} seconds")

            try:
                # Add primary key constraint directly in SQL
                execute_with_retry(
                    session,
                    """
                    ALTER TABLE processed.facilities ADD PRIMARY KEY (facility_id);
                    """,
                )

                # Add spatial index on geometry column
                execute_with_retry(
                    session,
                    """
                    CREATE INDEX idx_facilities_geometry ON processed.facilities USING GIST (geometry);
                    """,
                )
                print("Added spatial index on facilities geometry column")
            except Exception as e:
                print(
                    f"Error adding primary key or spatial index to facilities table: {e}"
                )
                return

        except Exception as e:
            print(f"Error creating facilities table: {e}")
            return


def drop_facilities_near_permits_foreign_key_constraints():
    """Drop foreign key constraints related to the facilities_near_permits table."""
    with get_db_session() as session:
        try:
            execute_with_retry(
                session,
                """
                DO $$
                BEGIN
                    -- Drop foreign key constraints
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS fk_facilities_near_permits_facility;
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS fk_facilities_near_permits_permit;
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS facilities_near_permits_facility_id_fkey;
                    ALTER TABLE IF EXISTS processed.facilities_near_permits DROP CONSTRAINT IF EXISTS facilities_near_permits_permit_id_fkey;
                END $$;
                """,
            )
            print("Dropped facilities_near_permits foreign key constraints")
        except Exception as e:
            print(
                f"Error while dropping facilities_near_permits foreign key constraints: {e}"
            )


def add_facilities_near_permits_foreign_key_constraints():
    """Add foreign key constraints related to the facilities_near_permits table."""
    with get_db_session() as session:
        try:
            execute_with_retry(
                session,
                """
                DO $$
                BEGIN
                    -- Check if constraints exist before adding them
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'facilities_near_permits_facility_id_fkey'
                    ) THEN
                        ALTER TABLE processed.facilities_near_permits
                        ADD CONSTRAINT facilities_near_permits_facility_id_fkey
                        FOREIGN KEY (facility_id)
                        REFERENCES processed.facilities(facility_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_facilities_near_permits_permit'
                    ) THEN
                        ALTER TABLE processed.facilities_near_permits
                        ADD CONSTRAINT fk_facilities_near_permits_permit
                        FOREIGN KEY (permit_id)
                        REFERENCES processed.permits(id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'facilities_near_permits_permit_id_fkey'
                    ) THEN
                        ALTER TABLE processed.facilities_near_permits
                        ADD CONSTRAINT facilities_near_permits_permit_id_fkey
                        FOREIGN KEY (permit_id)
                        REFERENCES processed.permits(id);
                    END IF;
                END $$;
                """,
            )
            print("Added facilities_near_permits foreign key constraints")
        except Exception as e:
            print(
                f"Error while adding facilities_near_permits foreign key constraints: {e}"
            )


def create_facilities_permits_table(buffer_size=500):
    """Create the facilities_near_permits table."""
    with get_db_session() as session:
        try:
            # First, drop foreign key constraints if they exist
            drop_facilities_near_permits_foreign_key_constraints()

            query = f"""
            DROP TABLE IF EXISTS processed.facilities_near_permits;
            CREATE TABLE processed.facilities_near_permits AS (
            WITH facility_barn_flags AS (
                SELECT
                    f.facility_id,
                    CASE
                        WHEN COUNT(b.facility_id) = 0 THEN TRUE
                        ELSE FALSE
                    END AS is_empty
                FROM processed.facilities f
                LEFT JOIN processed.barns b ON f.facility_id = b.facility_id
                GROUP BY f.facility_id
            )

            SELECT
                p.id AS permit_id,
                f.facility_id,
                ST_Distance(p.geometry, f.geometry) AS distance,
                ROW_NUMBER() OVER (PARTITION BY p.id ORDER BY ST_Distance(p.geometry, f.geometry)) AS rn,
                fb.is_empty,
                :buffer_size AS buffer_size
            FROM processed.permits p
            LEFT JOIN processed.facilities f
                ON ST_DWithin(p.geometry, f.geometry, :buffer_size)
            LEFT JOIN facility_barn_flags fb
                ON f.facility_id = fb.facility_id
            ORDER BY p.id, distance
            );
            """

            start_time = time.time()
            execute_with_retry(session, query, {"buffer_size": buffer_size})
            print(
                f"Facilities_near_permits table created in {time.time() - start_time:.2f} seconds"
            )

            # Add foreign key constraints
            add_facilities_near_permits_foreign_key_constraints()
        except Exception as e:
            print(f"Error creating facilities_near_permits table: {e}")


def update_related_tables():
    """Update the facility_id in related tables and add foreign key constraints."""
    with get_db_session() as session:
        try:
            # Count initial state
            counts = execute_with_retry(
                session,
                """
                SELECT
                    (SELECT COUNT(*) FROM processed.barns) as total_barns,
                    (SELECT COUNT(*) FROM processed.parcels) as total_parcels,
                    (SELECT COUNT(*) FROM processed.permits) as total_permits,
                    (SELECT COUNT(*) FROM processed.facilities) as total_facilities
                """,
            ).fetchone()

            print(f"\nInitial counts:")
            print(f"Total barns: {counts[0]}")
            print(f"Total parcels: {counts[1]}")
            print(f"Total permits: {counts[2]}")
            print(f"Total facilities: {counts[3]}\n")

            # Drop foreign key constraints if they exist
            drop_facility_foreign_key_constraints()

            # Define update queries for each table
            update_queries = {
                "parcels": """
                    -- First, clear existing facility_ids from parcels
                    UPDATE processed.parcels SET facility_id = NULL;

                    -- Update parcels with facility_id
                    UPDATE processed.parcels p
                    SET facility_id = f.facility_id
                    FROM processed.facilities f
                    WHERE ST_Intersects(p.geometry, f.geometry);
                """,
                "permits": """
                    -- First, clear existing facility_ids from permits
                    UPDATE processed.permits SET facility_id = NULL;

                    -- Update permits with facility_id
                    UPDATE processed.permits p
                    SET facility_id = pr.facility_id
                    FROM processed.permit_parcels pp
                    JOIN processed.parcels pr ON pr.id = pp.parcel_id
                    WHERE p.id = pp.permit_id;
                """,
                "barnclusters": """
                    -- First, add facility_id column if it doesn't exist
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'processed'
                            AND table_name = 'barnclusters'
                            AND column_name = 'facility_id'
                        ) THEN
                            ALTER TABLE processed.barnclusters ADD COLUMN facility_id TEXT;
                        END IF;
                    END $$;

                    -- Clear existing facility_ids from barn_clusters
                    UPDATE processed.barnclusters SET facility_id = NULL;

                    -- Update barn_clusters with facility_id based on associated parcels
                    UPDATE processed.barnclusters bc
                    SET facility_id = p.facility_id
                    FROM processed.barnclusterparcels bcp
                    JOIN processed.parcels p ON p.id = bcp.parcel_id
                    WHERE bc.id = bcp.barn_cluster_id
                    AND p.facility_id IS NOT NULL;
                """,
                "barns": """
                    -- First, clear existing facility_ids from barns
                    UPDATE processed.barns SET facility_id = NULL;

                    -- Update barns with facility_id from barn_clusters
                    UPDATE processed.barns b
                    SET facility_id = bc.facility_id
                    FROM processed.barnclusters bc
                    WHERE b.barn_cluster_id = bc.id
                    AND bc.facility_id IS NOT NULL;
                """,
            }

            start_time = time.time()

            # Process each table
            for table_name, query in update_queries.items():
                print(f"Updating {table_name}...")
                execute_with_retry(session, query)

                # Count results after update
                count_query = f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(facility_id) as assigned,
                    COUNT(*) - COUNT(facility_id) as unassigned,
                    COUNT(DISTINCT facility_id) as unique_facilities
                FROM processed.{table_name}
                """

                counts = execute_with_retry(session, count_query).fetchone()
                print(
                    f"{table_name.capitalize()} - Total: {counts[0]}, Assigned: {counts[1]}, Unassigned: {counts[2]}"
                )

                if counts[3] > 0:
                    print(
                        f"{table_name.capitalize()} are assigned to {counts[3]} unique facilities"
                    )

            # Add foreign key constraints
            add_facility_foreign_key_constraints()

            # Count empty facilities (facilities without any barns)
            empty_facilities_query = """
            SELECT COUNT(*) as empty_facilities_count
            FROM processed.facilities f
            WHERE NOT EXISTS (
                SELECT 1 FROM processed.barns b
                WHERE b.facility_id = f.facility_id
            );
            """
            empty_facilities_count = execute_with_retry(
                session, empty_facilities_query
            ).fetchone()[0]
            print(f"Empty facilities (without any barns): {empty_facilities_count}")

            print(
                f"\nRelated tables updated and constraints added in {time.time() - start_time:.2f} seconds"
            )
        except Exception as e:
            print(f"Error updating tables and adding constraints: {e}")
            raise


def create_all_facilities_tables(buffer_size=500):
    """Create all facilities-related tables and update related tables."""
    print("Creating facilities tables...")
    create_facilities_table()
    update_related_tables()
    create_facilities_permits_table(buffer_size)
    print("All facilities tables created successfully.")


if __name__ == "__main__":
    create_all_facilities_tables()
