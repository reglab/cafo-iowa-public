"""update barn tables

Revision ID: 9ac150104f80
Revises: 54ac033165e7
Create Date: 2025-04-22 15:08:52.413478

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "9ac150104f80"
down_revision: Union[str, None] = "54ac033165e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert types BEFORE creating foreign keys
    op.alter_column(
        "barnclusters",
        "id",
        existing_type=sa.INTEGER(),
        type_=sa.String(),
        existing_nullable=False,
        schema="processed",
    )

    op.alter_column(
        "barnclusterparcels",
        "barn_cluster_id",
        existing_type=sa.INTEGER(),
        type_=sa.String(),
        existing_nullable=False,
        schema="processed",
    )

    op.alter_column(
        "barns",
        "id",
        existing_type=sa.INTEGER(),
        type_=sa.String(),
        existing_nullable=False,
        schema="processed",
    )

    op.alter_column(
        "barns",
        "barn_cluster_id",
        existing_type=sa.INTEGER(),
        type_=sa.String(),
        existing_nullable=False,
        schema="processed",
    )

    op.alter_column(
        "cf_annotations",
        "barn_id",
        existing_type=sa.INTEGER(),
        type_=sa.String(),
        existing_nullable=True,
        schema="processed",
    )

    # Clean orphaned foreign key values before constraints
    op.execute(
        """
        DELETE FROM processed.barnclusterparcels
        WHERE barn_cluster_id NOT IN (SELECT id FROM processed.barnclusters)
    """
    )
    op.execute(
        """
        DELETE FROM processed.barnclusterparcels
        WHERE parcel_id NOT IN (SELECT id FROM processed.parcels)
    """
    )
    op.execute(
        """
        DELETE FROM processed.barns
        WHERE barn_cluster_id NOT IN (SELECT id FROM processed.barnclusters)
    """
    )
    op.execute(
        """
        DELETE FROM processed.barns
        WHERE facility_id IS NOT NULL AND facility_id NOT IN (SELECT facility_id FROM processed.facilities)
    """
    )
    op.execute(
        """
        DELETE FROM processed.cf_annotations
        WHERE barn_id IS NOT NULL AND barn_id NOT IN (SELECT id FROM processed.barns)
    """
    )
    op.execute(
        """
        DELETE FROM processed.cf_annotations
        WHERE batch_name IS NOT NULL AND batch_name NOT IN (SELECT batch_name FROM processed.label_batches)
    """
    )
    op.execute(
        """
        DELETE FROM processed.cf_annotations
        WHERE naip_qt_id NOT IN (SELECT id FROM processed.naip21_qt)
    """
    )
    op.execute(
        """
        DELETE FROM processed.permit_parcels
        WHERE parcel_id NOT IN (SELECT id FROM processed.parcels)
    """
    )
    op.execute(
        """
        DELETE FROM processed.permit_parcels
        WHERE permit_id NOT IN (SELECT id FROM processed.permits)
    """
    )

    # Create foreign keys (safe to do after type conversion)
    op.create_foreign_key(
        None,
        "barnclusterparcels",
        "barnclusters",
        ["barn_cluster_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "barnclusterparcels",
        "parcels",
        ["parcel_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "barns",
        "barnclusters",
        ["barn_cluster_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "barns",
        "facilities",
        ["facility_id"],
        ["facility_id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "cf_annotations",
        "barns",
        ["barn_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "cf_annotations",
        "label_batches",
        ["batch_name"],
        ["batch_name"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "cf_annotations",
        "naip21_qt",
        ["naip_qt_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )

    # Indices and geometry changes
    op.drop_index(
        "barnclusterparcels_staging_barn_cluster_id_idx",
        table_name="barnclusterparcels",
        schema="processed",
    )
    op.drop_index(
        "barnclusterparcels_staging_parcel_id_idx",
        table_name="barnclusterparcels",
        schema="processed",
    )
    op.create_index(
        op.f("ix_processed_barnclusterparcels_barn_cluster_id"),
        "barnclusterparcels",
        ["barn_cluster_id"],
        unique=False,
        schema="processed",
    )
    op.create_index(
        op.f("ix_processed_barnclusterparcels_parcel_id"),
        "barnclusterparcels",
        ["parcel_id"],
        unique=False,
        schema="processed",
    )

    op.drop_index(
        "barnclusters_staging_facility_id_idx",
        table_name="barnclusters",
        schema="processed",
    )
    op.drop_geospatial_index(
        "barnclusters_staging_geometry_idx",
        table_name="barnclusters",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.create_geospatial_index(
        "idx_barnclusters_geometry",
        "barnclusters",
        ["geometry"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_processed_barnclusters_facility_id"),
        "barnclusters",
        ["facility_id"],
        unique=False,
        schema="processed",
    )

    op.drop_index(
        "barns_staging_barn_cluster_id_idx1", table_name="barns", schema="processed"
    )
    op.drop_index(
        "barns_staging_facility_id_idx1", table_name="barns", schema="processed"
    )
    op.drop_geospatial_index(
        "barns_staging_geometry_idx1",
        table_name="barns",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.create_geospatial_index(
        "idx_barns_geometry",
        "barns",
        ["geometry"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_processed_barns_barn_cluster_id"),
        "barns",
        ["barn_cluster_id"],
        unique=False,
        schema="processed",
    )
    op.create_index(
        op.f("ix_processed_barns_facility_id"),
        "barns",
        ["facility_id"],
        unique=False,
        schema="processed",
    )

    op.drop_geospatial_index(
        "cf_annotations_staging_geometry_buffer_idx1",
        table_name="cf_annotations",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry_buffer",
    )
    op.drop_geospatial_index(
        "cf_annotations_staging_geometry_idx1",
        table_name="cf_annotations",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.drop_geospatial_index(
        "cf_annotations_staging_raw_coordinates_idx1",
        table_name="cf_annotations",
        schema="processed",
        postgresql_using="gist",
        column_name="raw_coordinates",
    )
    op.create_geospatial_index(
        "idx_cf_annotations_geometry",
        "cf_annotations",
        ["geometry"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_geospatial_index(
        "idx_cf_annotations_geometry_buffer",
        "cf_annotations",
        ["geometry_buffer"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_geospatial_index(
        "idx_cf_annotations_raw_coordinates",
        "cf_annotations",
        ["raw_coordinates"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )

    op.alter_column(
        "facilities",
        "facility_id",
        existing_type=sa.TEXT(),
        type_=sa.String(),
        existing_nullable=False,
        schema="processed",
    )

    op.alter_column(
        "facilities",
        "geometry",
        existing_type=Geometry(
            from_text="ST_GeomFromEWKT", name="geometry", _spatial_index_reflected=True
        ),
        type_=Geometry(
            srid=26915, from_text="ST_GeomFromEWKT", name="geometry", nullable=False
        ),
        nullable=False,
        schema="processed",
    )

    op.create_index(
        op.f("ix_processed_facilities_facility_id"),
        "facilities",
        ["facility_id"],
        unique=True,
        schema="processed",
    )

    # Fix for NOT NULL violation: add as nullable, fill, then make NOT NULL
    op.add_column(
        "facilities_near_permits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=True),
        schema="processed",
    )
    op.execute(
        """
        UPDATE processed.facilities_near_permits AS f
        SET id = sub.rn
        FROM (
            SELECT ctid, ROW_NUMBER() OVER () AS rn
            FROM processed.facilities_near_permits
        ) AS sub
        WHERE f.ctid = sub.ctid
    """
    )
    op.alter_column("facilities_near_permits", "id", nullable=False, schema="processed")
    op.create_primary_key(
        "pk_facilities_near_permits",
        "facilities_near_permits",
        ["id"],
        schema="processed",
    )

    op.execute(
        "DELETE FROM processed.facilities_near_permits WHERE facility_id IS NULL"
    )
    op.alter_column(
        "facilities_near_permits",
        "facility_id",
        existing_type=sa.TEXT(),
        type_=sa.String(),
        nullable=False,
        schema="processed",
    )

    op.alter_column(
        "facilities_near_permits",
        "permit_id",
        existing_type=sa.INTEGER(),
        nullable=False,
        schema="processed",
    )
    op.alter_column(
        "facilities_near_permits",
        "rn",
        existing_type=sa.BIGINT(),
        type_=sa.Integer(),
        existing_nullable=True,
        schema="processed",
    )
    op.alter_column(
        "facilities_near_permits",
        "buffer_size",
        existing_type=sa.INTEGER(),
        type_=sa.Float(),
        existing_nullable=True,
        schema="processed",
    )

    op.drop_index(
        "parcels_staging_facility_id_idx", table_name="parcels", schema="processed"
    )
    op.drop_geospatial_index(
        "parcels_staging_geometry_idx",
        table_name="parcels",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.create_geospatial_index(
        "idx_parcels_geometry",
        "parcels",
        ["geometry"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_processed_parcels_facility_id"),
        "parcels",
        ["facility_id"],
        unique=False,
        schema="processed",
    )

    op.create_foreign_key(
        None,
        "permit_parcels",
        "permits",
        ["permit_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "permit_parcels",
        "parcels",
        ["parcel_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )

    op.drop_index(
        "permits_staging_facility_id_idx1", table_name="permits", schema="processed"
    )
    op.drop_index(
        "permits_staging_facilityid_idx1", table_name="permits", schema="processed"
    )
    op.drop_geospatial_index(
        "permits_staging_geometry_idx1",
        table_name="permits",
        schema="processed",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.create_geospatial_index(
        "idx_permits_geometry",
        "permits",
        ["geometry"],
        unique=False,
        schema="processed",
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_processed_permits_facility_id"),
        "permits",
        ["facility_id"],
        unique=False,
        schema="processed",
    )
    op.create_index(
        op.f("ix_processed_permits_facilityid"),
        "permits",
        ["facilityid"],
        unique=True,
        schema="processed",
    )
    op.create_foreign_key(
        None,
        "permits",
        "naip21_qt",
        ["naip_qt_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "permits",
        "naip21",
        ["naip_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )
    op.create_foreign_key(
        None,
        "permits_storage",
        "permits",
        ["permit_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )


def downgrade():
    raise NotImplementedError(
        "Manual downgrade required due to irreversible column type changes (String → Integer) on foreign key columns."
    )
