# Survey Hazard Intelligence

The hazard-map subsystem for DeepEcho (SIH26057). It takes a side-scan sonar
survey and a trained YOLOv8 checkpoint and produces a ranked, auditable picture
of where the hazards are and which one to look at first.

    THE HAZARD MAP ANSWERS    WHERE things are, and HOW URGENT they are
    THE RAG ASSISTANT ANSWERS WHAT a thing is, and WHAT TO DO about it

Those stay separate throughout. A severity score is arithmetic over a
detector's output and can be recomputed by hand from the record it sits in. A
grounded answer is retrieval over a document corpus, with different evidence and
different ways of being wrong. Merged, a confident sentence could raise a
priority, or a priority could imply a fact, and neither system can support that.

## Three things this will not do

Read these before the numbers, because they govern how much the numbers mean.

**The coordinates are not GPS.** Unless you supply navigation, every position
is a pixel offset inside the sonar strip, derived from survey geometry and
nothing else. The export says `"coordinate_mode": "Relative Survey Coordinates"`,
every latitude and longitude is `null`, and the map never formats anything as a
fix. Supply navigation and geographic positions are interpolated from it, under
documented assumptions stated in the export. Nothing is ever inferred, defaulted
or carried over from a previous survey.

**Severity is a heuristic, not a standard.** The class weights, the tier
boundaries and the recommended actions are a configurable policy chosen for this
project. They are not Navy, Coast Guard, NOAA or IMO procedure and they carry no
authority. They are calibrated against nothing: they are a considered ordering of
consequence, and the per-class confidence floors rest on a single observed false
positive each. Everything in `hazard_config.py` is meant to be retuned against a
labelled validation set. The same sentence is in `configuration.disclaimer` of
every export and in a column of every `actions.csv`, so a file that travels on
its own still carries the caveat.

**A detection is not a fact.** YOLO output is a prediction. What it is worth
depends on the checkpoint, its training data, the quality of the sonar, the
quality of the navigation, whether the class definitions match what is actually
on this seabed, and where the confidence threshold sits. Ten tiles of a real
side-scan waterfall record in this repository produce four detections, and all
four appear to be false positives on nadir and shadow boundaries. The engine
ranks what it is given; it cannot tell you the detector was wrong.

## Pipeline

    Raw sonar strips
      │
      ▼  prepare_survey()                                survey_preparation.py
    Positioned tiles + manifest.csv / manifest.json
      │
      ▼  YOLOv8, one or more checkpoints, loaded once    hazard_detect.py
    Tile detections
      │
      ▼  cross-model merge, one box per object per tile  hazard_dedup.py
      ▼  global coordinates, tile-local -> survey        hazard_coords.py
      ▼  severity = class_weight x confidence            hazard_severity.py
      ▼  global deduplication across overlapping tiles   hazard_dedup.py
      ▼  geographic position, or an explicit null        hazard_geo.py
      ▼  spatial aggregation and ranking                 hazard_hotspots.py
      │
      ▼  build_hazard_map()                              hazard_map.py
    ┌──────────────┬───────────────────────────────────────────┐
    │  map.html    │  export.json  ──►  Dashboard  ──►  RAG handoff
    │  actions.csv │                    /map route       assistant
    └──────────────┴───────────────────────────────────────────┘

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python unit_tests.py && ./.venv/bin/python smoke_test.py
```

`numpy` and `pillow` are the only hard dependencies. `folium` is needed to build
`map.html` and never to read one. `ultralytics` is needed only to run a real
checkpoint, because `build_hazard_map()` accepts any callable that returns boxes,
and every test in this repository runs without it.

## Module APIs

### Module 1

```python
from survey_preparation import prepare_survey

tiles_dir, manifest_path = prepare_survey(strip_paths, out_dir, nav=None)
```

| Argument | Meaning |
| --- | --- |
| `strip_paths` | A path, a list of paths, or a directory of images. |
| `out_dir` | Created if absent. Tiles go in `out_dir/tiles`. |
| `nav` | `None`, a path to a control-point CSV, or a dict of four corners. |

From a shell:

```bash
python3 run_survey.py --strips survey/ --model models/known.pt --out out/
```

### Module 2

```python
from hazard_map import build_hazard_map

export = build_hazard_map(model_path, tiles_dir, out_dir, manifest=None,
                          detector=None, nav=None, conf=None,
                          merge_dist=None, grid=None, top_n=None,
                          demo=False, title=None)
```

`model_path` takes one checkpoint or several. `detector` replaces the built-in
loader with any callable taking an image path and returning
`[{"class": str, "confidence": float, "bbox": [x1, y1, x2, y2]}]`, which is how
the engine runs inside DeepEcho without pulling torch into a process that has
already loaded faiss.

Both entry points are importable on their own and neither needs the dashboard,
the assistant, a database, a key or a network.

```bash
python3 run_survey.py --strips survey/ --model models/known.pt models/anomaly.pt \
    --out out/ --title "Mangaluru approach"
python3 demo_survey.py                       # the whole pipeline, no survey needed
```

## Configuration

Every threshold lives in `hazard_config.py` and nothing else hard-codes a value.

| Setting | Default | What it does |
| --- | --- | --- |
| `TILE` | 640 | Tile edge, matching the checkpoints' training size. |
| `STRIDE` | 512 | Step between tiles, giving 128 px of overlap. |
| `MIN_CONTENT` | 0.02 | Keep a tile when its grey-level standard deviation over 255 is at least this. |
| `DENOISE` | False | 3x3 median plus a 1st-to-99th percentile stretch. Intensity only. |
| `CONF_THRESH` | 0.30 | Boxes below this are never read out of the model. |
| `CLASS_CONFIDENCE_FLOOR` | per class | Below its floor a class is withheld, not dropped. |
| `DETECTOR_MERGE_IOU` | 0.5 | Cross-model overlap, same tile. |
| `MERGE_DIST` | 60 px | Survey-wide merge distance, same class and strip. |
| `GRID` | 512 px | Hotspot cell edge. |
| `SEVERITY` | table | Class weight, the consequence of being wrong. |
| `UNKNOWN_CLASS_SEVERITY` | 0.8 | A class the table has never seen. Never 0.0. |
| `SEVERITY_TIERS` | 0.75 / 0.40 | critical, medium, low. |
| `RISK_DENSITY_WEIGHT` | 0.25 | How much the objects beyond the worst one add. |
| `TOP_N_HOTSPOTS` | 0 (all) | Rows in `actions.csv`. |

## Tiling and coverage

Tiles are named exactly `{strip}_{x}_{y}.jpg`, where x and y are the tile's
top-left offset in the original strip, in pixels. Not an index. The name parses
back even when the strip's own name contains underscores, though the manifest is
the contract and filenames are only a fallback.

Offsets step by `STRIDE` and stop once the next tile would start past the end, so
the last tile in each direction is partial and every pixel is covered. Because
`STRIDE` is smaller than `TILE`, a partial tile is never narrower than
`TILE - STRIDE`, so a run never produces a useless sliver.

Strips are opened one at a time and each tile is written before the next is cut,
so peak memory is one strip plus one tile rather than the whole survey.

`MIN_CONTENT` is stated exactly because a silent filter is how a contact goes
missing. A tile is kept when

    content_score = standard deviation of the tile's 8-bit grey levels / 255

is at or above the threshold, measured on the tile as written, so what is scored
is what the detector will be shown.

## Coordinate provenance

Without navigation: `lat` and `lon` are `null` everywhere, the mode is
`Relative Survey Coordinates`, and that is a complete, usable result.

**Control-point CSV.** Columns `strip, pixel_x, pixel_y, latitude, longitude`.
Three or more non-collinear fixes fit a first-order affine transform by least
squares, and the worst residual is reported in the export. A nav file with one
fix per ping row is collinear, so an affine fit would be underdetermined
across-track; that falls back to one-dimensional interpolation along the track
line and sets `across_track_resolved: false` rather than guessing a range scale
it does not have.

**Four corners.** `top_left`, `top_right`, `bottom_left`, `bottom_right`, each
`[latitude, longitude]`. A tile centre is interpolated bilinearly between them.

Both assume a locally flat seabed and locally linear degrees over one strip.
Neither is valid across the antimeridian or over a pole, and the export says so.
Every position is computed from the **tile centre**, never its corner: locating a
640-pixel tile by its corner puts it half a tile out, consistently, in one
direction, which is the kind of error that survives review.

Two strips are two coordinate frames. Without navigation nothing says how far
apart they are, so deduplication and hotspots are scoped to a single strip.

## Severity provenance

One formula, and it is the whole of it:

    severity = class_weight * confidence

Every record keeps `class_weight`, `confidence`, `severity` and `severity_basis`
side by side, so any score in the export can be recomputed by hand from the
record itself. Matching is exact on the normalised class name, else the longest
table key contained in it, else `UNKNOWN_CLASS_SEVERITY`. So `moored_mine`,
`sea mine` and `Mine` all reach the mine weight without being listed, and a class
the policy has never been taught is treated as unidentified rather than weighted
out of existence.

A class below its confidence floor is relabelled `unknown` and the original call
is kept in `downgraded_from`. Nothing is dropped, because a deleted box hides a
contact from the operator.

Read this before changing a floor: withholding a class does **not** uniformly
lower severity. It lowers it only for classes weighted above
`UNKNOWN_CLASS_SEVERITY`. A withheld `human` gets quieter, a withheld `aircraft`
gets louder, and both are the policy working. "Downgrade" describes the claim,
not the score.

## Deduplication

Two stages, answering different questions. Neither does the other's job.

| Stage | Question | Test | Merges classes |
| --- | --- | --- | --- |
| Cross-model | did two checkpoints see the same box in this tile? | box overlap (IoU) | yes |
| Survey-wide | did one object appear across overlapping tiles? | centre distance | never |

The cross-model stage merges across classes because the checkpoints do not share
a vocabulary: on a real record of the submarine S-7, `known.pt` called the wreck
"ship" at 0.82 and `anomaly.pt` called the same box "shipwreck" at 0.39,
overlapping at IoU 0.82. Counted separately that is one submarine with double its
severity. The losing call is kept as a structured `second_opinion`.

The survey-wide stage never merges classes, because across tiles two different
classes near each other are two objects. It stays distance-based rather than
overlap-based because a sonar return's box shape varies with range, so the same
object at two ranges would fail an overlap test.

Detections are taken highest-confidence first and each either joins an accepted
representative or becomes one; membership is only tested against representatives.
Without that, A merges B, B merges C, and a line of separate objects collapses
into one contact hundreds of pixels long.

## Hotspots and ranking

The survey is divided into a `GRID`-pixel square grid per strip, and a cell
holding at least one detection becomes a hotspot. A fixed frame rather than a
grown cluster, so two runs produce the same hotspots in the same order. Known
limitation, stated because it is real: two detections either side of a cell
boundary land in different hotspots. Both are still reported and ranked.

Hotspots rank by `total_severity`, descending, never by count. The dominant class
is severity-weighted for the same reason, so three pieces of debris beside a mine
still leaves the mine dominant and the action is the mine's.

**The honest edge of that rule**, tested in `unit_tests.py` so nobody discovers it
on stage: enough low-severity objects do outrank one high-severity object. Five
tyres at 0.9 confidence sum to 1.350 against one mine's 0.900, so the tyre field
ranks first. What separates them is `max_severity` and `risk_score`, both of which
put the mine ahead, and both of which are in the export and on the map beside the
total.

Derived metrics, all arithmetic on the numbers above:

| Metric | What it is |
| --- | --- |
| `risk_score` | `max_severity + RISK_DENSITY_WEIGHT * (total_severity - max_severity)`. An index, not a percentage: it has no upper bound. |
| `detection_density` | Detections per megapixel of cell area. |
| `hazard_diversity` | Distinct classes in the cell. |
| `confidence_mean`, `confidence_max` | The detector's own certainty. |
| `severity_per_detection` | Separates one bad object from many mild ones. |
| `spatial_extent` | Bounding box of the detection centres, not of the cell. |
| `priority_rank` | Position in the ranking. 1 is first. |
| `rationale` | The above in a sentence, naming the detection that set the severity. |

Identifiers are `H001`, `H002`, assigned after ranking, so the id and the rank
never disagree.

## Output structure

```
out/
├── tiles/                  {strip}_{x}_{y}.jpg
├── manifest.csv            tile,strip,x,y,lat,lon,mean_intensity + extras
├── manifest.json           the same rows, plus a survey block
├── export.json             the contract below
├── actions.csv             the worklist, in rank order
└── map.html                standalone, needs no network
```

`manifest.csv` always begins with `tile, strip, x, y, lat, lon, mean_intensity`,
in that order. Added after them: `width`, `height`, `tile_width`, `tile_height`,
`center_x`, `center_y`, `source_image`, `denoised`, `content_score`.

### export.json

```jsonc
{
  "metadata":       { "engine", "processing_version", "processed_at",
                      "survey_id", "title", "coordinate_mode",
                      "confidence_threshold", "model_name", "model_path",
                      "detector_classes", "demo" },
  "survey_summary": { "total_raw_detections", "total_deduplicated_detections",
                      "duplicates_removed", "total_hotspots", "total_severity",
                      "highest_priority_hotspot", "highest_severity_class",
                      "class_distribution", "detections_by_tier",
                      "hotspots_by_tier", "georeferenced", "coordinate_mode",
                      "strips_processed", "tiles_processed",
                      "model_confidence_threshold" },
  "detections": [ { "id", "object_class", "confidence", "class_weight",
                    "severity", "severity_tier", "severity_basis",
                    "recommended_action", "global_x", "global_y",
                    "bbox_global", "latitude", "longitude",
                    "class_withheld?", "downgraded_from?",
                    "provenance": { "strip", "representative_tile",
                                    "source_tiles", "merged_count",
                                    "merged_from", "tile_offset",
                                    "bbox_tile", "second_opinion?" } } ],
  "hotspots":   [ { "hotspot_id", "priority_rank", "strip", "cell",
                    "centroid", "detection_count", "total_severity",
                    "max_severity", "severity_tier", "dominant_class",
                    "recommended_action", "risk_score", "detection_density",
                    "hazard_diversity", "confidence_mean", "confidence_max",
                    "severity_per_detection", "spatial_extent",
                    "detection_ids", "top_detection", "rationale" } ],
  "configuration": { "tiling", "detection", "deduplication",
                     "hotspots", "severity_policy", "disclaimer" },
  "provenance":    { "coordinate_mode", "navigation", "source_strips",
                     "tile_count", "tiles_processed", "tiles_failed",
                     "model", "severity_formula", "ranking_rule",
                     "class_confidence_floors", "audit_note" }
}
```

The base contract `{"detections": [], "hotspots": []}` is a subset, so a consumer
written against the minimal shape keeps working. Every field is load-bearing: a
value that could not be determined is `null` with something in `provenance`
saying why, rather than a plausible default that reads like measurement.

## The map

`map.html` depends on nothing once it exists. Leaflet is inlined and the sonar
imagery is embedded as a data URI, so it opens from a USB stick on a machine that
has never seen this project. Folium links eleven files from four CDNs by default,
which renders as a blank rectangle offline; `hazard_assets.py` inlines the three
that are used and removes the eight that are not.

A survey with no navigation is drawn on a pixel plane with the sonar strip as the
base layer and no world map underneath, because there is no world position to put
one at. A navigated survey is drawn on real coordinates with an optional street
basemap, off by default.

Layers, each toggleable: sonar imagery, survey tiles, severity heatmap, all
detections, critical, medium, low, and hotspots. The heatmap is weighted by
severity and never by count, so a hundred tyres cannot glow hotter than one mine.

## Dashboard integration

Route `/map` in the DeepEcho dashboard. Everything lives in
`frontend/src/survey/`: the page, five components, a config file holding every
URL and label, an API module that is the only thing that fetches, a handoff
module, and a stylesheet scoped to `.sv-`. Delete that directory and three lines
and the feature is gone.

| Endpoint | Returns |
| --- | --- |
| `GET /survey` | Every processed survey, enough for a picker. |
| `GET /survey/{id}/export` | The export document, unmodified. |
| `GET /survey/{id}/map` | The standalone `map.html`. |
| `GET /survey/{id}/actions.csv` | The worklist. |
| `POST /survey/process` | Runs the engine. Behind a flag, off by default. |

The page reads `export.json` once and renders it. No number is recomputed in the
browser and no threshold is duplicated: the engine decided the severities, the
ranking and the actions and recorded why, and the page displays that decision.
Filter options are derived from the loaded export, so a survey full of classes
nobody has seen still filters correctly.

`POST /survey/process` runs `run_survey.py` in a subprocess rather than in the
API process. faiss and torch each ship their own libomp and on macOS whichever
initialises second aborts the server mid-request; the application has already
loaded faiss for the assistant. Client-supplied strip paths are resolved and
required to sit inside an allowed root, so `..`, an absolute path and a symlink
all fail the same way.

## RAG handoff

The map hands a hotspot to the assistant as a structured object and stops there.
No retrieval, no prompt and no knowledge live on this side of the line.

```js
{
  hotspot_id: "H001",
  dominant_class: "ship",
  severity: 0.4937,              // the hotspot's max_severity, 0 to 1
  confidence: 0.8228,
  centroid: { global_x: 168.6, global_y: 291.4 },
  lat: null,                     // null unless the survey has navigation
  lon: null,
  recommended_action: "Flag navigation hazard",

  // additive, safe to ignore
  severity_tier: "medium", priority_rank: 1, detection_count: 1,
  total_severity: 0.4937, coordinate_mode: "Relative Survey Coordinates",
  survey_id: "s7-submarine", demo: false, evidence_tile: "..._0_0.jpg"
}
```

It does not travel as a detection record. The assistant maps `object_class` onto
its own label and looks severity up in its own table, so the same hotspot would
carry one urgency on the map and another beside the answer, with nobody able to
see both at once. The map owns urgency; the assistant displays what it is given.

`total_severity` is a sum over a grid cell and routinely exceeds 1. It must never
be rendered as a severity. `severity_tier` is already computed and should be
taken rather than re-derived, so the two systems cannot drift.

## Testing

```bash
python3 unit_tests.py         # 40 unit tests, no files, no model, under a second
python3 smoke_test.py         # 187 end-to-end checks on synthetic sonar
python3 validate_output.py out/   # validates one survey's artefacts
python3 real_model_test.py    # a real checkpoint over a few tiles, or skips
```

The four do not overlap on purpose. Unit tests exercise single functions against
values chosen by hand. The smoke test drives the whole pipeline with synthetic
strips and a stand-in detector that reports the objects they were drawn from, so
the assertions are exact rather than approximate. `validate_output.py` reads a
survey's files the way a stranger would and believes nothing it was not shown;
it is checked against eight deliberate sabotages. `real_model_test.py` covers the
one seam a mock cannot: that a real checkpoint loads and its output has the shape
the engine expects. It skips with a stated reason when torch is absent, because
that is not a failure.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `map.html` is a blank white page | Built without network access and Leaflet could not be vendored. Build one map with a network to populate `vendor/`, then it works offline forever. |
| `OMP: Error #15` | torch and faiss in one process. Use `detector=` with a subprocess, or call `run_survey.py` from a shell. |
| No tiles written | Every tile scored below `MIN_CONTENT`. Set it to 0.0 to keep them all. |
| Every lat/lon is null | No navigation was supplied. That is correct behaviour, not a bug. |
| `ModuleNotFoundError: folium` | Only needed to build a map. `pip install folium`, or pass `--no-map`. |
| A strip is missing from the survey | It could not be opened. `manifest.json` lists it under `strips_unreadable` with the reason. |
| Hotspot ranking looks wrong | Read `rationale` on the hotspot. It names the detection that set the severity. |

## Files

| File | What it is |
| --- | --- |
| `hazard_config.py` | Every knob. Nothing else hard-codes a value. |
| `survey_preparation.py` | Module 1. Strips to positioned tiles plus a manifest. |
| `hazard_map.py` | Module 2. The orchestrator and public entry point. |
| `hazard_detect.py` | The detector interface and the Ultralytics loader. |
| `hazard_coords.py` | Tile-local boxes to survey coordinates. |
| `hazard_dedup.py` | Cross-model and survey-wide deduplication. |
| `hazard_severity.py` | The formula, the tiers, the floors and the actions. |
| `hazard_hotspots.py` | Spatial aggregation, ranking and derived metrics. |
| `hazard_geo.py` | Pixels to latitude and longitude, or a refusal. |
| `hazard_export.py` | The JSON contract, the summary and `actions.csv`. |
| `hazard_mapview.py` | `export.json` to a standalone `map.html`. |
| `hazard_theme.py` | Every colour and label the map uses. |
| `hazard_assets.py` | Inlines Leaflet so the map works offline. |
| `run_survey.py` | Command-line runner over the whole pipeline. |
| `demo_survey.py` | The pipeline on a simulated survey. |
| `unit_tests.py`, `smoke_test.py`, `validate_output.py`, `real_model_test.py` | See Testing. |
| `vendor/` | Leaflet and the heat plugin. Commit it. |
