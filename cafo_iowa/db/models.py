from typing import List

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Double,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy_serializer import SerializerMixin


# Base class for all SQLAlchemy models
class Base(DeclarativeBase, SerializerMixin):
    """Base class for all SQLAlchemy models."""

    __abstract__ = True

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.__dict__}>"

    def __str__(self):
        return self.__repr__()


class RawBase(Base):
    """Base class for all raw SQLAlchemy models."""

    __abstract__ = True
    __table_args__ = {"schema": "raw", "quote": False, "quote_schema": False}


class ProcessedBase(Base):
    """Base class for all processed SQLAlchemy models."""

    __abstract__ = True
    __table_args__ = {
        "schema": "processed",
        "quote": False,
        "quote_schema": False,
    }


class UrbanAreasRaw(RawBase):
    __tablename__ = "urban_areas"

    id: Mapped[str] = mapped_column(primary_key=True)
    geoid20: Mapped[str]
    name20: Mapped[str]
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    other_cols: Mapped[dict] = mapped_column(JSONB())

    def __repr__(self):
        return f"<UrbanAreasRaw(id = '{self.id}', name='{self.name20}')>"


class CensusTractsRaw(RawBase):
    __tablename__ = "census_tracts"

    id: Mapped[str] = mapped_column(primary_key=True)
    statefp: Mapped[str] = mapped_column(nullable=False)
    county_name: Mapped[str] = mapped_column(nullable=True)
    countyfp: Mapped[str] = mapped_column(nullable=False)
    tractce: Mapped[str] = mapped_column(nullable=False)
    geoid: Mapped[str] = mapped_column(unique=True, nullable=False)
    namelsad: Mapped[str] = mapped_column(nullable=False)
    population: Mapped[int] = mapped_column(nullable=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    other_cols: Mapped[dict] = mapped_column(JSONB())

    def __repr__(self):
        return f"<CensusTractsRaw(id = '{self.id}', name='{self.name}')>"


class Naip21Raw(RawBase):
    __tablename__ = "naip21"

    id: Mapped[str] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    other_cols: Mapped[dict] = mapped_column(JSONB())

    def __repr__(self):
        return f"<Naip21Raw(id = '{self.id}', filename='{self.filename}')>"


class ParcelsRaw(RawBase):
    __tablename__ = "parcels"

    id: Mapped[str] = mapped_column(primary_key=True)
    parcelnumb: Mapped[str] = mapped_column(nullable=True)
    owner: Mapped[str] = mapped_column(nullable=True)
    address: Mapped[str] = mapped_column(nullable=True)
    scity: Mapped[str] = mapped_column(nullable=True)
    szip: Mapped[str] = mapped_column(nullable=True)
    lat: Mapped[float] = mapped_column(nullable=True)
    lon: Mapped[float] = mapped_column(nullable=True)
    county: Mapped[str] = mapped_column(nullable=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    other_cols: Mapped[dict] = mapped_column(JSONB())


class PermitsRaw(RawBase):
    __tablename__ = "permits"

    id: Mapped[int] = mapped_column(primary_key=True)
    facilityid: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    facilityna: Mapped[str] = mapped_column(nullable=True)
    address: Mapped[str] = mapped_column(nullable=True)
    city: Mapped[str] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(nullable=True)
    zip: Mapped[int] = mapped_column(nullable=True)
    latitude: Mapped[float] = mapped_column(nullable=True)
    longitude: Mapped[float] = mapped_column(nullable=True)
    county: Mapped[str] = mapped_column(nullable=True)
    fieldoffic: Mapped[str] = mapped_column(nullable=True)
    totalanima: Mapped[int] = mapped_column(nullable=True)
    opeartiont: Mapped[str] = mapped_column(nullable=True)
    cattle_bee: Mapped[int] = mapped_column(nullable=True)
    cattle_b_1: Mapped[int] = mapped_column(nullable=True)
    immature_d: Mapped[int] = mapped_column(nullable=True)
    mature_dai: Mapped[int] = mapped_column(nullable=True)
    cattle_dai: Mapped[int] = mapped_column(nullable=True)
    cattle_vea: Mapped[int] = mapped_column(nullable=True)
    chicken_la: Mapped[int] = mapped_column(nullable=True)
    chicken_pu: Mapped[int] = mapped_column(nullable=True)
    cow_calf: Mapped[int] = mapped_column(nullable=True)
    ducks: Mapped[int] = mapped_column(nullable=True)
    fish___25: Mapped[int] = mapped_column(nullable=True)
    fish_____2: Mapped[int] = mapped_column(nullable=True)
    goats: Mapped[int] = mapped_column(nullable=True)
    horses: Mapped[int] = mapped_column(nullable=True)
    sheep_and: Mapped[int] = mapped_column(nullable=True)
    swine_gest: Mapped[int] = mapped_column(nullable=True)
    swine_gilt: Mapped[int] = mapped_column(nullable=True)
    swine_grow: Mapped[int] = mapped_column(nullable=True)
    swine_nurs: Mapped[int] = mapped_column(nullable=True)
    swine_sow: Mapped[int] = mapped_column(nullable=True)
    swine_wean: Mapped[int] = mapped_column(nullable=True)
    turkey_fin: Mapped[int] = mapped_column(nullable=True)
    turkey_pou: Mapped[int] = mapped_column(nullable=True)
    collection: Mapped[str] = mapped_column(nullable=True)
    collectedb: Mapped[str] = mapped_column(nullable=True)
    locationco: Mapped[str] = mapped_column(nullable=True)
    geometry: Mapped[Geometry] = mapped_column(
        Geometry("POINT", srid=26915), nullable=False
    )
    other_cols: Mapped[dict] = mapped_column(JSONB())


class PermitsStorageRaw(RawBase):
    __tablename__ = "permits_storage"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id = Column(Integer, unique=True)
    facility_name = Column(String, nullable=False)
    confinement = Column(String)
    open_feedlot = Column(String)
    management_plan = Column(String)
    construction_permit = Column(String)
    npdes_permit = Column(String)
    swine = Column(Float)
    dairy_cattle = Column(Float)
    beef_cattle = Column(Float)
    chickens = Column(Float)
    turkeys = Column(Float)
    horses = Column(Float)
    sheep_lambs_goats = Column(Float)
    earthen_basin = Column(String)
    at_system = Column(String)
    below_buildings_pits = Column(String)
    below_buildings_pits_deep = Column(String)
    below_buildings_pit_shallow = Column(String)
    other = Column(String)
    outside_formed_concrete = Column(String)
    outside_concrete_uncovered = Column(String)
    runoff_control = Column(String)
    wetland = Column(String)
    slurry_store = Column(String)
    solids_settling = Column(String)
    lagoon_aerobic = Column(String)
    lagoon_anaerobic = Column(String)
    sand_settling_lanes = Column(String)
    settled_open_feedlot_effluent_basin = Column(String)
    stockpiling_structure_covered = Column(String)
    stockpiling_structure_uncovered = Column(String)
    vegetative_inflitration_basin_vib_ = Column(String)
    other_cols: Mapped[dict] = mapped_column(JSONB())

    def __repr__(self):
        return f"<Facility(facilityid={self.facilityid}, facilityname='{self.facilityname}')>"


class LabelBatchesRaw(RawBase):
    __tablename__ = "label_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_name: Mapped[str] = mapped_column(String)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_date: Mapped[Date] = mapped_column(Date, nullable=False)
    batch_metadata: Mapped[dict] = mapped_column(JSONB())
    naip_qt_ids: Mapped[list[str]] = mapped_column(JSONB())
    n_facilities: Mapped[int] = mapped_column(Integer)
    facility_ids: Mapped[list[int]] = mapped_column(JSONB())


class CFAnnotationsRaw(RawBase):
    __tablename__ = "cf_annotations"

    id: Mapped[str] = mapped_column(primary_key=True)
    naip_qt_id: Mapped[str]
    naip_id: Mapped[str]
    n_annotations: Mapped[int]
    batch_name: Mapped[str]
    datasetid: Mapped[str]
    itemid: Mapped[str]
    type: Mapped[str]
    label: Mapped[str]
    creator: Mapped[str]
    geometry: Mapped[Geometry] = mapped_column(Geometry, nullable=True)
    other_cols: Mapped[dict] = mapped_column(JSONB())


# --------------------
# Processed tables
# --------------------


class AnimalWeights(ProcessedBase):
    __tablename__ = "animal_weights"

    id: Mapped[int] = mapped_column(primary_key=True)
    animal_type: Mapped[str] = mapped_column(primary_key=True)
    avg_max_weight_lbs: Mapped[float] = mapped_column(nullable=True)
    avg_max_weight_sd_lbs: Mapped[float] = mapped_column(nullable=True)
    TAM_lbs: Mapped[float] = mapped_column(nullable=True)


class UrbanAreas(ProcessedBase):
    __tablename__ = "urban_areas"

    id: Mapped[str] = mapped_column(primary_key=True)
    geoid20: Mapped[str]
    name20: Mapped[str]
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    def __repr__(self):
        return f"<UrbanAreas(id = '{self.id}', name='{self.name20}')>"


class CensusTracts(ProcessedBase):
    __tablename__ = "census_tracts"

    id: Mapped[str] = mapped_column(primary_key=True)
    statefp: Mapped[str] = mapped_column(nullable=False)
    county_name: Mapped[str] = mapped_column(nullable=True)
    countyfp: Mapped[str] = mapped_column(nullable=False)
    tractce: Mapped[str] = mapped_column(nullable=False)
    geoid: Mapped[str] = mapped_column(unique=True, nullable=False)
    namelsad: Mapped[str] = mapped_column(nullable=False)
    population: Mapped[int] = mapped_column(nullable=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    def __repr__(self):
        return f"<CensusTracts(id = '{self.id}', name='{self.name}')>"


class Naip21(ProcessedBase):
    __tablename__ = "naip21"

    id: Mapped[str] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    naip21_qt: Mapped[List["Naip21QT"]] = relationship(
        "Naip21QT", back_populates="naip"
    )

    @declared_attr
    def permits(cls):
        return relationship("Permits", back_populates="naip")

    def __repr__(self):
        return f"<Naip21(id = '{self.id}')>"


class Naip21QT(ProcessedBase):
    __tablename__ = "naip21_qt"

    id: Mapped[str] = mapped_column(primary_key=True)
    is_urban: Mapped[bool] = mapped_column(Boolean, nullable=False)
    urban_area: Mapped[float] = mapped_column(Double, nullable=False)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    geometry_buffer: Mapped[Geometry] = mapped_column(
        Geometry(srid=26915), nullable=False
    )

    # Foreign keys
    naip_id: Mapped[str] = mapped_column(ForeignKey(Naip21.id), nullable=False)
    naip: Mapped[Naip21] = relationship("Naip21", back_populates="naip21_qt")

    @declared_attr
    def permits(cls):
        return relationship("Permits", back_populates="naip_qt")

    @declared_attr
    def cf_annotations(cls):
        return relationship("CFAnnotations", back_populates="naip_qt")

    def __repr__(self):
        return f"<Naip21QT(id = '{self.id}')>"


class Facilities(ProcessedBase):
    """Facilities model representing merged parcels with associated permits and barns."""

    __tablename__ = "facilities"

    facility_id: Mapped[str] = mapped_column(
        String, primary_key=True, unique=True, index=True
    )
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    # Relationships
    parcels: Mapped[List["Parcels"]] = relationship(
        "Parcels", back_populates="facility"
    )
    permits: Mapped[List["Permits"]] = relationship(
        "Permits", back_populates="facility"
    )
    barns: Mapped[List["Barns"]] = relationship("Barns", back_populates="facility")
    barn_clusters: Mapped[List["BarnClusters"]] = relationship(
        "BarnClusters", back_populates="facility"
    )
    facilities_near_permits: Mapped[List["FacilitiesNearPermits"]] = relationship(
        "FacilitiesNearPermits", back_populates="facility"
    )

    def __repr__(self):
        return f"<Facilities(id={self.facility_id})>"


class BarnClusterParcels(ProcessedBase):
    """
    Mapping table that links barn clusters to parcels.
    Replaces BarnsParcels to associate parcels with barn clusters instead of individual barns.
    """

    __tablename__ = "barnclusterparcels"

    id: Mapped[int] = mapped_column(primary_key=True)
    barn_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("processed.barnclusters.id"), index=True
    )
    parcel_id: Mapped[str] = mapped_column(
        ForeignKey("processed.parcels.id"), index=True
    )

    def __repr__(self):
        return f"<BarnClusterParcels(id={self.id})>"


class BarnClusters(ProcessedBase):
    __tablename__ = "barnclusters"

    id: Mapped[str] = mapped_column(primary_key=True)
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)
    facility_id: Mapped[str] = mapped_column(
        ForeignKey(Facilities.facility_id), nullable=True, index=True
    )

    barns: Mapped[List["Barns"]] = relationship("Barns", back_populates="barn_cluster")
    parcels: Mapped[List["Parcels"]] = relationship(
        "Parcels",
        secondary="processed.barnclusterparcels",
        back_populates="barn_clusters",
    )
    facility = relationship("Facilities", back_populates="barn_clusters")

    def __repr__(self):
        return f"<BarnClusters(id={self.id})>"


class Barns(ProcessedBase):
    __tablename__ = "barns"

    id: Mapped[str] = mapped_column(primary_key=True)
    barn_cluster_id: Mapped[str] = mapped_column(
        ForeignKey(BarnClusters.id), nullable=False, index=True
    )
    facility_id: Mapped[str] = mapped_column(
        ForeignKey(Facilities.facility_id), nullable=True, index=True
    )
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    # Relationships
    barn_cluster = relationship("BarnClusters", back_populates="barns")
    facility = relationship("Facilities", back_populates="barns")
    cf_annotations = relationship("CFAnnotations", back_populates="barn")

    def __repr__(self):
        return f"<Barns(id={self.id})>"


class Parcels(ProcessedBase):
    __tablename__ = "parcels"

    id: Mapped[str] = mapped_column(primary_key=True)
    parcelnumb: Mapped[str] = mapped_column(nullable=True)
    owner: Mapped[str] = mapped_column(nullable=True)
    address: Mapped[str] = mapped_column(nullable=True)
    county: Mapped[str] = mapped_column(nullable=True)
    scity: Mapped[str] = mapped_column(nullable=True)
    szip: Mapped[str] = mapped_column(nullable=True)
    lat: Mapped[float] = mapped_column(nullable=True)
    lon: Mapped[float] = mapped_column(nullable=True)
    features_merged: Mapped[int] = mapped_column(nullable=True)
    original_ids: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=True)
    facility_id: Mapped[str] = mapped_column(
        ForeignKey(Facilities.facility_id), nullable=True, index=True
    )
    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=False)

    # Relationships
    permit_parcels: Mapped[List["PermitParcels"]] = relationship(
        "PermitParcels", back_populates="parcel"
    )
    barn_clusters: Mapped[List["BarnClusters"]] = relationship(
        "BarnClusters",
        secondary="processed.barnclusterparcels",
        back_populates="parcels",
    )
    facility = relationship("Facilities", back_populates="parcels")

    def __repr__(self):
        return f"<Parcels(id={self.id}, parcelnumb='{self.parcelnumb}')>"


class Permits(ProcessedBase):
    __tablename__ = "permits"

    id: Mapped[int] = mapped_column(primary_key=True)
    facilityid: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    facilityna: Mapped[str] = mapped_column(nullable=True)
    address: Mapped[str] = mapped_column(nullable=True)
    city: Mapped[str] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(nullable=True)
    zip: Mapped[int] = mapped_column(nullable=True)
    latitude: Mapped[float] = mapped_column(nullable=True)
    longitude: Mapped[float] = mapped_column(nullable=True)
    county: Mapped[str] = mapped_column(nullable=True)
    fieldoffic: Mapped[str] = mapped_column(nullable=True)
    animal_units: Mapped[int] = mapped_column(nullable=True)
    animal_type: Mapped[str] = mapped_column(nullable=True)
    swine_animal_units: Mapped[int] = mapped_column(nullable=True)
    swine_type: Mapped[str] = mapped_column(nullable=True)
    opeartiont: Mapped[str] = mapped_column(nullable=True)
    cattle_bee: Mapped[int] = mapped_column(nullable=True)
    cattle_b_1: Mapped[int] = mapped_column(nullable=True)
    immature_d: Mapped[int] = mapped_column(nullable=True)
    mature_dai: Mapped[int] = mapped_column(nullable=True)
    cattle_dai: Mapped[int] = mapped_column(nullable=True)
    cattle_vea: Mapped[int] = mapped_column(nullable=True)
    chicken_la: Mapped[int] = mapped_column(nullable=True)
    chicken_pu: Mapped[int] = mapped_column(nullable=True)
    cow_calf: Mapped[int] = mapped_column(nullable=True)
    ducks: Mapped[int] = mapped_column(nullable=True)
    fish___25: Mapped[int] = mapped_column(nullable=True)
    fish_____2: Mapped[int] = mapped_column(nullable=True)
    goats: Mapped[int] = mapped_column(nullable=True)
    horses: Mapped[int] = mapped_column(nullable=True)
    sheep_and: Mapped[int] = mapped_column(nullable=True)
    swine_gest: Mapped[int] = mapped_column(nullable=True)
    swine_gilt: Mapped[int] = mapped_column(nullable=True)
    swine_grow: Mapped[int] = mapped_column(nullable=True)
    swine_nurs: Mapped[int] = mapped_column(nullable=True)
    swine_sow: Mapped[int] = mapped_column(nullable=True)
    swine_wean: Mapped[int] = mapped_column(nullable=True)
    turkey_fin: Mapped[int] = mapped_column(nullable=True)
    turkey_pou: Mapped[int] = mapped_column(nullable=True)
    collection: Mapped[str] = mapped_column(nullable=True)
    collectedb: Mapped[str] = mapped_column(nullable=True)
    locationco: Mapped[str] = mapped_column(nullable=True)
    address_geo: Mapped[str] = mapped_column(nullable=True)
    lat_geo: Mapped[float] = mapped_column(nullable=True)
    lng_geo: Mapped[float] = mapped_column(nullable=True)
    distance_km: Mapped[float] = mapped_column(nullable=True)
    facility_id: Mapped[str] = mapped_column(
        ForeignKey(Facilities.facility_id), nullable=True, index=True
    )
    geometry: Mapped[Geometry] = mapped_column(
        Geometry("POINT", srid=26915), nullable=False
    )

    # Foreign keys
    naip_id: Mapped[str] = mapped_column(ForeignKey(Naip21.id), nullable=False)
    naip_qt_id: Mapped[str] = mapped_column(ForeignKey(Naip21QT.id), nullable=False)

    # Relationships
    naip: Mapped[Naip21] = relationship("Naip21", back_populates="permits")
    naip_qt: Mapped[Naip21QT] = relationship("Naip21QT", back_populates="permits")
    permit_parcels: Mapped[List["PermitParcels"]] = relationship(
        "PermitParcels", back_populates="permit"
    )
    facility = relationship("Facilities", back_populates="permits")
    facilities_near_permits: Mapped[List["FacilitiesNearPermits"]] = relationship(
        "FacilitiesNearPermits", back_populates="permit"
    )

    @declared_attr
    def permits_storage(cls):
        return relationship("PermitsStorage", back_populates="permits")

    def __repr__(self):
        return f"<Permits(id = '{self.id}')>"


class FacilitiesNearPermits(ProcessedBase):
    """Model representing the relationship between facilities and permits, including distance and empty status."""

    __tablename__ = "facilities_near_permits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    permit_id: Mapped[int] = mapped_column(ForeignKey(Permits.id), nullable=False)
    facility_id: Mapped[str] = mapped_column(
        ForeignKey(Facilities.facility_id), nullable=False
    )
    distance: Mapped[float] = mapped_column(Float, nullable=True)
    rn: Mapped[int] = mapped_column(Integer, nullable=True)
    is_empty: Mapped[bool] = mapped_column(Boolean, nullable=True)
    buffer_size: Mapped[float] = mapped_column(Float, nullable=True)

    # Relationships
    permit: Mapped["Permits"] = relationship(
        "Permits", back_populates="facilities_near_permits"
    )
    facility: Mapped[Facilities] = relationship(
        "Facilities", back_populates="facilities_near_permits"
    )

    def __repr__(self):
        return f"<FacilitiesNearPermits(permit_id={self.permit_id}, facility_id={self.facility_id}, distance={self.distance})>"


class PermitsStorage(ProcessedBase):
    __tablename__ = "permits_storage"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id = Column(Integer, unique=True)
    facility_name = Column(String, nullable=False)
    confinement = Column(Boolean)
    open_feedlot = Column(Boolean)
    management_plan = Column(Boolean)
    construction_permit = Column(Boolean)
    npdes_permit = Column(Boolean)
    lagoon_aerobic = Column(Boolean)
    lagoon_anaerobic = Column(Boolean)
    earthen_basin = Column(Boolean)
    at_system = Column(Boolean)
    below_buildings_pits = Column(Boolean)
    below_buildings_pits_deep = Column(Boolean)
    below_buildings_pit_shallow = Column(Boolean)
    outside_formed_concrete = Column(Boolean)
    outside_concrete_uncovered = Column(Boolean)
    runoff_control = Column(Boolean)
    wetland = Column(Boolean)
    slurry_store = Column(Boolean)
    solids_settling = Column(Boolean)
    sand_settling_lanes = Column(Boolean)
    settled_open_feedlot_effluent_basin = Column(Boolean)
    stockpiling_structure_covered = Column(Boolean)
    stockpiling_structure_uncovered = Column(Boolean)
    vegetative_inflitration_basin_vib_ = Column(Boolean)

    # Foreign keys
    permit_id: Mapped[int] = mapped_column(ForeignKey(Permits.id), nullable=True)

    # Relationships
    permits: Mapped[Permits] = relationship("Permits", back_populates="permits_storage")

    def __repr__(self):
        return f"<PermitsStorage(id = '{self.id}')>"


class PermitParcels(ProcessedBase):
    """
    Association table that links permits to parcels with metadata about the match.
    """

    __tablename__ = "permit_parcels"

    id: Mapped[int] = mapped_column(primary_key=True)
    permit_id: Mapped[int] = mapped_column(ForeignKey(Permits.id), nullable=False)
    parcel_id: Mapped[str] = mapped_column(ForeignKey(Parcels.id), nullable=False)
    match_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'geometry' or 'fuzzy_name'
    fuzzy_match_score: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # Only for fuzzy name matches
    distance_meters: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # Distance between permit and parcel
    is_primary_match: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )  # Whether this is the primary match

    # Relationships
    permit: Mapped[Permits] = relationship("Permits", back_populates="permit_parcels")
    parcel: Mapped[Parcels] = relationship("Parcels", back_populates="permit_parcels")

    def __repr__(self):
        return f"<PermitParcels(id={self.id}, permit_id={self.permit_id}, parcel_id={self.parcel_id}, match_type='{self.match_type}')>"


class LabelBatches(ProcessedBase):
    __tablename__ = "label_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_date: Mapped[Date] = mapped_column(Date, nullable=False)
    batch_metadata: Mapped[dict] = mapped_column(JSONB(), nullable=True)
    naip_qt_ids: Mapped[list[str]] = mapped_column(JSONB(), nullable=True)
    n_facilities: Mapped[int] = mapped_column(Integer, nullable=True)
    facility_ids: Mapped[list[int]] = mapped_column(JSONB(), nullable=True)

    @declared_attr
    def cf_annotations(cls):
        return relationship("CFAnnotations", back_populates="label_batches")


class CFAnnotations(ProcessedBase):
    __tablename__ = "cf_annotations"

    id: Mapped[str] = mapped_column(primary_key=True)
    n_annotations: Mapped[int]
    clipped_annotation: Mapped[bool] = mapped_column(Boolean)
    clipped_annotation_empty: Mapped[bool] = mapped_column(Boolean)
    datasetid: Mapped[str]
    itemid: Mapped[str]
    type: Mapped[str]
    label: Mapped[str]
    creator: Mapped[str]

    geometry: Mapped[Geometry] = mapped_column(Geometry(srid=26915), nullable=True)
    geometry_buffer: Mapped[Geometry] = mapped_column(
        Geometry(srid=26915), nullable=True
    )
    raw_coordinates: Mapped[Geometry] = mapped_column(Geometry, nullable=True)

    # Foreign keys
    naip_qt_id: Mapped[str] = mapped_column(ForeignKey(Naip21QT.id), nullable=False)
    # Foreign keys
    barn_id: Mapped[str] = mapped_column(ForeignKey(Barns.id), nullable=True)
    batch_name: Mapped[str] = mapped_column(
        ForeignKey(LabelBatches.batch_name), nullable=True
    )

    # Relationships
    naip_qt = relationship("Naip21QT", back_populates="cf_annotations")
    barn = relationship("Barns", back_populates="cf_annotations")
    label_batches = relationship("LabelBatches", back_populates="cf_annotations")
