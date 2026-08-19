# Barn annotation verification pipeline

Groundwork for eventually having an LLM judge each barn annotation in `processed.barns`
(0/1, correct or not) against aerial imagery and the facility's DNR inspection record. This
covers only the data-preparation half of that: producing, per facility, an image with the
existing barn annotations overlaid plus the facility's most recent inspection document. The
review/judging step itself (the prompt, and whatever reads these folders and produces a
verdict) has not been built yet.

## `build_facility_crop()` (`cafo_iowa/utils/visualize.py`)

Given a `facility_id`, builds a real georeferenced image crop of that facility from NAIP
tiles, sized to guarantee every one of its barn annotations is fully contained:

- Centers a square window on the facility's permit point, with the half-side length set to
  the distance to the farthest barn-polygon corner plus a fixed buffer (default 75m) — so
  the window always contains every barn, regardless of facility footprint.
- Looks up which `processed.naip21_qt` tiles intersect that window, downloads them (via
  `cafo_iowa.data.helpers.gcs.download_single_img`), and mosaics them with
  `rasterio.merge`.
- Writes three files to a given output directory:
  - `crop.tif` — the cropped mosaic, all original NAIP bands (R, G, B, NIR), native
    resolution, real CRS/transform. Meant for programmatic use (e.g. reprojecting a barn
    polygon back onto it), not casual viewing.
  - `image_unmarked.png` — the same crop, RGB-rendered, no annotations. Lets a reviewer
    form an independent read of what's on the ground before seeing what's already claimed.
  - `image_marked.png` — the same crop, RGB-rendered, with the facility boundary, permit
    marker, and each barn individually numbered.
- Returns a dict (facility_id, window bounds, tile CRS, tiles used, and a
  barn-number-to-`processed.barns.id` mapping) for the caller to persist as metadata. Each
  barn entry includes both its projected geometry (`geometry_wkt`, in `tile_crs`) and its
  pixel-space coordinates on `image_marked.png`/`image_unmarked.png` (`pixel_polygon`, the
  true — possibly rotated — footprint; `pixel_bbox`, its axis-aligned bounding box), so a
  reader can index directly against the rendered image instead of reprojecting WKT.

This is a new, independent function — it does not call or modify `plot_facility_example`.
Unlike that function, it pulls real NAIP tiles rather than a `contextily` web basemap, and
takes a `facility_id` directly rather than a pre-built row from `get_facilities()`.

Differs from the DB's own coordinate system where relevant: `processed.*` geometries are
EPSG:26915, but the actual downloaded NAIP rasters are EPSG:32615 — the function reprojects
at runtime rather than assuming either CRS.

## `build_barn_verification_folders.py` (`cafo_iowa/data/`)

Driver script that, for a list of `facility_id`s, calls `build_facility_crop()` and also
fetches that facility's most recent inspection PDF from `raw.facility_documents`
(`document_type = 'inspection'`, most recent `action_date`), writing it alongside the crop
outputs. This assumes `raw.facility_documents` / `raw.facility_document_coverage` are
already populated (from the DNR document-archive project); that loading code isn't part of
this push.

Run from the repo root with the LCR SSH tunnel up:

```
python3 -m cafo_iowa.data.build_barn_verification_folders
```

## Output structure

For each `facility_id`, writes `data/barn_verification/{facility_id}/`:

```
crop.tif             -- georeferenced crop, all NAIP bands, unmarked
image_unmarked.png   -- RGB render, no annotations
image_marked.png     -- RGB render, numbered barn boxes + facility boundary + permit marker
inspection.pdf       -- most recent inspection document, if one exists for this facility
metadata.json        -- barn number<->id mapping, window bounds, tiles used, inspection source
```

## Known limitation: multi-cluster facilities

The "one square window per facility, guaranteed to contain every barn" design works well
for facilities whose barns form a single tight cluster, but breaks down for the (real, not
rare) case where one `facility_id` actually covers two or more widely-separated barn
clusters — e.g. combined DNR registrations on separate parcels. In those cases the window
has to stretch to cover both clusters, and the barns in the denser cluster shrink to the
point of being hard to individually distinguish, let alone judge.

This matters beyond just image quality: if most examples a reviewer (human or model) sees
are easy, tightly-cropped single-cluster cases, and only a few are these sprawling
multi-cluster ones, the reviewer will naturally get better at the easy cases and worse at
exactly the hard ones this project cares most about (facilities with many barns and/or a
large reported/estimated mismatch).

The likely fix is to split multi-cluster facilities into one crop per cluster (these tend
to fall on separate parcels, so clustering by parcel is a natural split) rather than forcing
one oversized image per facility — at the cost of a downstream reviewer needing to reason
across multiple images per facility instead of one. Not yet implemented.
