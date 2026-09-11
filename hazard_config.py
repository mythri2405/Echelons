"""Every knob for the survey hazard subsystem, in one file.

The rule for this module: if it is something you might want to change later --
a tile size, a threshold, a severity weight, a recommended action -- it lives
here and nowhere else. The engine modules import from here; they never
hard-code a value of their own.

Nothing in this file is an official standard. The severity weights and the
recommended actions are a configurable operational heuristic chosen for this
project. They are not Navy, Coast Guard, NOAA or IMO procedure, and the export
says so in `configuration.disclaimer` so a file that travels on its own still
carries the caveat.
"""

from __future__ import annotations

import os

# --- Identity --------------------------------------------------------------
# Bumped when a change alters the numbers an export contains. It is written
# into every export so an old file can be told apart from a new one.

ENGINE_NAME = "deepecho-survey-hazard"
PROCESSING_VERSION = "1.0.0"
SEVERITY_POLICY_VERSION = "1.0.0"

# --- Module 1: survey preparation ------------------------------------------

# Tile edge in pixels. 640 is the imgsz the checkpoints were trained at, so a
# tile reaches the network without being rescaled.
TILE = int(os.environ.get("HAZARD_TILE", "640"))

# Step between tile origins. Smaller than TILE on purpose: an object lying on a
# tile boundary is cut in half in both neighbours and missed by both. The
# 128-pixel overlap means every object under 128 px across appears whole in at
# least one tile. The duplicates this creates are removed in global
# deduplication, which is the cheaper half of the trade.
STRIDE = int(os.environ.get("HAZARD_STRIDE", "512"))

# Content filter. A tile is KEPT when its content score is >= MIN_CONTENT.
#
# content_score = standard deviation of the tile's 8-bit grey levels / 255
#
# computed on the tile exactly as it is written to disk, so what is scored is
# what the detector will see. The score is 0.0 for a perfectly flat tile and
# rises with texture. Open water and the unpainted margin either side of a
# side-scan swath are close to flat; seabed, shadow and returns are not.
#
# The default of 0.02 is a standard deviation of about 5 grey levels out of
# 255. It removes blank margin without touching low-contrast seabed, which in
# practice scores an order of magnitude higher. Set it to 0.0 to keep every
# tile, which is the honest setting when you would rather pay for inference
# than risk dropping a faint contact.
MIN_CONTENT = float(os.environ.get("HAZARD_MIN_CONTENT", "0.02"))

# Optional preprocessing, off by default. On, a tile gets a 3x3 median filter
# and a percentile contrast stretch, in that order. Both are intensity-only.
# Nothing here rotates, rescales, warps or pads, because a tile's pixel grid is
# the survey's coordinate system and moving a pixel moves an object.
DENOISE = os.environ.get("HAZARD_DENOISE", "").lower() in {"1", "true", "yes"}
DENOISE_MEDIAN_SIZE = 3
# Percentiles the stretch maps to 0 and 255. Deliberately not 0/100: a single
# hot pixel would otherwise set the whole scale. Conservative, so a faint
# target is lifted without saturating the seabed around it.
DENOISE_CLIP_PERCENTILES = (1.0, 99.0)

# Quality for the written JPEG tiles. High enough that compression artefacts
# stay well below the acoustic noise floor.
TILE_JPEG_QUALITY = int(os.environ.get("HAZARD_TILE_QUALITY", "92"))

# --- Module 2: detection ---------------------------------------------------

# Boxes below this confidence are not read out of the model at all.
CONF_THRESH = float(os.environ.get("HAZARD_CONF_THRESH", "0.30"))

# Inference size. Matches TILE so a tile is not resampled on its way in.
DETECTOR_IMGSZ = int(os.environ.get("HAZARD_IMGSZ", str(TILE)))

# --- Global deduplication --------------------------------------------------

# Two detections of the SAME class whose global centres are within this many
# survey pixels are the same physical object, seen twice through the tile
# overlap. 60 px sits comfortably under the 128 px overlap, so a genuine pair
# of distinct neighbouring objects is not swallowed.
#
# Different classes are never merged on proximity alone. A drum resting inside
# a wreck field is two facts, not one.
MERGE_DIST = float(os.environ.get("HAZARD_MERGE_DIST", "60"))

# --- Cross-model agreement -------------------------------------------------
# Two boxes in the SAME tile from DIFFERENT checkpoints overlapping by at least
# this much are the same physical object seen by both models.
#
# This is a separate stage from MERGE_DIST and the two must not be confused.
#   this one    "did two models see the same box in one tile"      overlap, IoU
#   MERGE_DIST  "did one object appear across overlapping tiles"   centre distance
#
# Survey-wide deduplication stays distance-based on purpose: a sonar return's
# box shape varies with range, so an IoU test across tiles would fail on the
# same object seen at two different ranges.
#
# Unlike MERGE_DIST, this one DOES merge across classes, because the two models
# do not share a vocabulary. On a real side-scan record of the submarine S-7,
# known.pt called the wreck "ship" at 0.82 and anomaly.pt called the same box
# "shipwreck" at 0.39, overlapping at IoU 0.82. Counting that as two contacts
# doubles the hotspot's severity for one object.
#
# The disagreement is never discarded. The more confident call leads and the
# other is kept beside it as a second opinion, because two models disagreeing
# about what something is is information an operator should see.
DETECTOR_MERGE_IOU = float(os.environ.get("HAZARD_DETECTOR_IOU", "0.5"))

# --- Severity --------------------------------------------------------------
# severity = class_weight * confidence, and nothing else. Both inputs are kept
# beside the result in every record so any score can be recomputed by hand.
#
# The weights are consequence, not probability: what it costs to be wrong about
# this class. Life safety is 1.0. An unidentified object is 0.8, high enough to
# be looked at and deliberately below a confirmed mine, because asserting that
# something nobody has identified is maximally dangerous is itself a claim
# nothing supports.

SEVERITY: dict[str, float] = {
    "mine": 1.0,
    "ordnance": 1.0,
    "uxo": 1.0,
    "human": 1.0,
    "victim": 1.0,
    "unknown": 0.8,
    "anomaly": 0.8,
    "aircraft": 0.7,
    "plane": 0.7,
    "ship": 0.6,
    "shipwreck": 0.6,
    "wreck": 0.6,
    "chain": 0.5,
    "cable": 0.5,
    "net": 0.5,
    "ghost-gear": 0.5,
    "tire": 0.3,
    "drum": 0.3,
    # Biological returns. Added after a review found that `fish`, which
    # anomaly.pt emits, was absent from this table and fell through to
    # UNKNOWN_CLASS_SEVERITY, scoring 0.8 and ranking a shoal above a confirmed
    # shipwreck at 0.6. DeepEcho's own backend already classes marine life as
    # low, so the fallback was contradicting a policy the project had already
    # settled. 0.2 sits below debris: a fish is not a hazard, and a misfired
    # fish call on something that is not a fish still stays visible.
    "fish": 0.2,
    "marine-life": 0.2,
    "debris": 0.3,
    "bottle": 0.3,
    "can": 0.3,
}

# A class the table has never heard of. Not 0.0: a model trained on classes
# this policy does not know about must not have its detections silently
# weighted out of existence. It is treated as an unidentified object.
UNKNOWN_CLASS_SEVERITY = float(os.environ.get("HAZARD_UNKNOWN_SEVERITY", "0.8"))

# --- Per-class confidence floors -------------------------------------------
# CONF_THRESH admits a box. These decide whether its CLASS is trustworthy
# enough to report, which is a different question and has a different answer
# per class.
#
# A detection below its class's floor is NOT dropped. It is relabelled
# `unknown` and the original call is preserved in `downgraded_from`. Deleting
# the box would hide a contact from the operator, which is worse than showing
# one without a name.
#
# READ THIS BEFORE CHANGING THEM. Relabelling to `unknown` does not always
# lower severity. It lowers it only for classes weighted above
# UNKNOWN_CLASS_SEVERITY, which here is the life-safety set at 1.0. For a class
# weighted below 0.8 the relabel RAISES severity, because this policy
# deliberately ranks an unidentified object above a confirmed wreck:
#
#   human    at 0.46, below floor:  1.0 x 0.46 = 0.46  ->  0.8 x 0.46 = 0.37
#   aircraft at 0.55, below floor:  0.7 x 0.55 = 0.39  ->  0.8 x 0.55 = 0.44
#
# Both are the policy working as written. "Downgrade" describes the claim, not
# the score, and reading it as de-escalation will mislead you.
#
# PROVENANCE OF THESE NUMBERS. They come from the DeepEcho backend, measured
# across seven public side-scan tiles: one false-positive `human` at 0.463 on
# debris beside a wreck, one false-positive `aircraft` at 0.322 on a wreck,
# against correct `ship` calls spanning 0.318 to 0.829. One observation per
# false-positive class is not a fitted threshold. These are precautionary and
# are meant to be retuned against a labelled validation set. Do not let them
# acquire authority by being copied.
CLASS_CONFIDENCE_FLOOR: dict[str, float] = {
    # The highest-consequence claim in the vocabulary, and a legal and
    # humanitarian assertion. Strictest floor.
    "human": 0.75,
    "victim": 0.75,
    "aircraft": 0.60,
    "plane": 0.60,
    "fish": 0.60,
    "ship": 0.25,
    "shipwreck": 0.25,
    "wreck": 0.25,
}

# What a below-floor class becomes. Matches DeepEcho's DOWNGRADE_LABEL so a
# record crossing between the two systems keeps its meaning.
DOWNGRADE_LABEL = "unknown"

DOWNGRADE_NOTE = (
    "the model called this '{cls}' at {confidence:.2f}, below the {floor:.2f} "
    "this system requires before reporting that class. Reported as unidentified "
    "instead. The original call is retained and nothing was discarded.")

# --- Severity tiers --------------------------------------------------------
# One table, used everywhere a score becomes a word. A detection's tier comes
# from its own severity; a hotspot's tier comes from its max_severity, so a
# hotspot is never called critical unless it contains something that is.
#
# The boundaries are set against the score range the formula can produce. With
# weights of 1.0 for life-safety classes, 0.75 is a confirmed-class detection
# the model is at least 75% sure of, or an unidentified object at 0.94. 0.40
# separates "worth a dive plan" from "worth logging".

SEVERITY_TIERS: tuple[tuple[str, float], ...] = (
    ("critical", 0.75),
    ("medium", 0.40),
    ("low", 0.0),
)

# --- Actions ---------------------------------------------------------------
# A recommended next step, per class. Configurable, and advisory only: these
# are this project's defaults, not any authority's published procedure.

ACTIONS: dict[str, str] = {
    "mine": "Deploy EOD team",
    "ordnance": "Deploy EOD team",
    "uxo": "Deploy EOD team",
    "human": "Initiate SAR",
    "victim": "Initiate SAR",
    "debris": "Schedule cleanup",
    "bottle": "Schedule cleanup",
    "can": "Schedule cleanup",
    "shipwreck": "Flag navigation hazard",
    "wreck": "Flag navigation hazard",
    "ship": "Flag navigation hazard",
    # Added after a survey ranked an aircraft contact first and recommended
    # "send for expert identification", which is the default rather than a
    # decision. A wreck on the seabed is a navigation hazard whether it flew
    # or floated.
    "aircraft": "Flag navigation hazard",
    "plane": "Flag navigation hazard",
    # Recoverable litter, same handling as the other debris classes.
    "tyre": "Schedule cleanup",
    "tire": "Schedule cleanup",
    "drum": "Schedule cleanup",
    "unknown": "Send for expert identification",
    "anomaly": "Send for expert identification",
    # Biological returns. The only entry in this table that asks for nothing.
    # Without it a fish inherited the default and the action column read the
    # same for the lowest-severity class on the map as for an object nobody
    # has identified, which drains the meaning out of the column. The trade is
    # stated rather than hidden: a misclassified object called "fish" is now
    # filed instead of examined, which is why the class also carries a
    # confidence floor of 0.60 before it can be asserted at all.
    "fish": "Log only, no action",
    "marine-life": "Log only, no action",
}

# Anything the table does not name. "Send for expert identification" is the
# only honest default: the system has found something it has no policy for.
DEFAULT_ACTION = "Send for expert identification"

# Carried as a column in actions.csv so the file still states what it is when
# it is opened on its own, away from this repository.
ACTION_BASIS = "configurable heuristic; not an official procedure"

DISCLAIMER = (
    "Severity weights, tier boundaries and recommended actions are a "
    "configurable heuristic chosen for this project. They are not Navy, Coast "
    "Guard, NOAA or IMO procedure and carry no authority. Review them against "
    "your own operating rules before acting on them."
)

# --- Hotspots --------------------------------------------------------------

# Detections are aggregated into a square grid of this edge, in survey pixels.
# A cell holding at least one detection becomes a hotspot.
GRID = int(os.environ.get("HAZARD_GRID", "512"))

# How much the objects beyond the worst one add to a hotspot's risk score.
#
#   risk_score = max_severity + RISK_DENSITY_WEIGHT * (total_severity - max_severity)
#
# At 0.25, four more objects as bad as the worst one add one more unit of risk.
# The worst single object still dominates, which is the behaviour you want: a
# cell holding one mine outranks a cell holding a heap of tyres.
#
# It is an INDEX, not a percentage and not a probability. It has no upper bound:
# a cell with enough contacts exceeds 1.0 and is meant to. Everything that
# renders it says "risk index" for that reason, because a reader who sees
# "risk 1.099" and thinks percentage has been misled by the label, not the
# number. Severity tiers are applied to max_severity, which is 0 to 1.
RISK_DENSITY_WEIGHT = float(os.environ.get("HAZARD_RISK_DENSITY_WEIGHT", "0.25"))

# How many hotspots the action list carries. 0 means all of them.
TOP_N_HOTSPOTS = int(os.environ.get("HAZARD_TOP_N", "0"))

# --- Coordinates -----------------------------------------------------------
# The two things the system is allowed to say about where it is. There is no
# third option and no default guess: without navigation the mode is relative
# and every lat/lon in the export is null.

COORD_MODE_RELATIVE = "Relative Survey Coordinates"
COORD_MODE_GEO = "Geo-referenced"

# --- Output ----------------------------------------------------------------

MANIFEST_CSV = "manifest.csv"
MANIFEST_JSON = "manifest.json"
EXPORT_JSON = "export.json"
ACTIONS_CSV = "actions.csv"
TILES_DIRNAME = "tiles"

# The manifest columns that downstream code is entitled to rely on. Extra
# columns are added after these; these seven never move and never disappear.
MANIFEST_REQUIRED_COLUMNS = ("tile", "strip", "x", "y", "lat", "lon", "mean_intensity")
