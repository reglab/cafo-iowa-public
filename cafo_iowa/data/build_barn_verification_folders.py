import json
import os
from pathlib import Path

import sqlalchemy
from google.cloud import storage

import cafo_iowa.db.session as s
from cafo_iowa.utils.visualize import build_facility_crop

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "data" / "barn_verification"
INSPECTION_BUCKET = "cafo-methane"

# Example facility_ids spanning both the easy case (one barn) and harder cases (multiple barns)
FACILITY_IDS = [
    "0058f8b1d6d69e293b9a8a5d9dd7f0f0",  # Schrock Farms -- 1 barn
    "009e0b3b36bb3c75f242d6554cecdc71",  # PI 275 Finisher -- 1 barn
    "00f7fc3c1aacdb2fa389791f875e29fc",  # Doty Farms Finisher #1 -- 1 barn
    "79f1dfa26fd124f4db011101b4d22535",  # 24 barns, estimated/reported ratio 1.22
    "5da4ff407104faab3169af4fad14eac6",  # 19 barns, estimated/reported ratio 1.65
    "a1ccdd72447677c3b0b3b6f43b958e5e",  # 11 barns, estimated/reported ratio 1.88
]


def get_facility_name(engine, facility_id):
    with engine.connect() as conn:
        row = conn.execute(
            sqlalchemy.text(
                "SELECT dnr_facility_names FROM raw.facility_document_coverage WHERE facility_id = :fid"
            ),
            {"fid": facility_id},
        ).fetchone()
    if row and row[0]:
        return row[0][0]
    return None


def fetch_most_recent_inspection(engine, facility_id):
    with engine.connect() as conn:
        row = conn.execute(
            sqlalchemy.text(
                "SELECT pdf_name, action_date FROM raw.facility_documents "
                "WHERE facility_id = :fid AND document_type = 'inspection' "
                "ORDER BY action_date DESC LIMIT 1"
            ),
            {"fid": facility_id},
        ).fetchone()
    return row


def build_one(engine, bucket, facility_id):
    out_dir = OUT_ROOT / facility_id
    print(f"=== {facility_id} ===")

    meta = build_facility_crop(facility_id, str(out_dir), engine=engine)
    meta["dnr_facility_name"] = get_facility_name(engine, facility_id)

    inspection = fetch_most_recent_inspection(engine, facility_id)
    if inspection is None:
        print(f"  WARNING: no inspection document found for {facility_id}")
        meta["inspection_source"] = None
    else:
        pdf_name, action_date = inspection
        bucket.blob(pdf_name).download_to_filename(str(out_dir / "inspection.pdf"))
        meta["inspection_source"] = {
            "action_date": action_date.isoformat(),
            "gcs_path": f"gs://{INSPECTION_BUCKET}/{pdf_name}",
        }
        print(f"  inspection: {pdf_name} ({action_date})")

    with open(out_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"  tiles used: {meta['tiles_used']}")
    print(f"  barns: {[(b['number'], b['id']) for b in meta['barns']]}")
    print(f"  wrote {out_dir}")


def main(facility_ids=FACILITY_IDS):
    engine = s.get_engine()
    bucket = storage.Client().bucket(INSPECTION_BUCKET)

    for facility_id in facility_ids:
        build_one(engine, bucket, facility_id)

    print("\nDONE.")


if __name__ == "__main__":
    main()
