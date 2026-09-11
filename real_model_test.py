#!/usr/bin/env python3
"""Run a real checkpoint over a handful of tiles and check what comes back.

    python3 real_model_test.py
    python3 real_model_test.py --models models/known.pt models/anomaly.pt
    python3 real_model_test.py --tiles 4 --verbose

Exit codes
    0  the test ran and passed, OR it was skipped for a stated reason
    1  the test ran and something is wrong

Skipping is not failing, and the difference is deliberate. This file needs
torch, ultralytics and a trained checkpoint, none of which the engine itself
requires. On a machine without them the correct outcome is a clear sentence
saying which piece is absent, not a red build. unit_tests.py and smoke_test.py
cover the logic without any of it.

WHAT THIS ADDS OVER THE OTHER TWO
    smoke_test.py proves the pipeline with a stand-in detector, so it can prove
    everything except that a real checkpoint loads and that its output has the
    shape the engine expects. That is exactly the seam where a torch upgrade, a
    changed Ultralytics API, or a corrupt download will break things, and it is
    invisible to a mocked test. So this runs the real thing, over a deliberately
    small number of tiles, and checks the seam.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hazard_config as cfg

log = logging.getLogger("deepecho.hazard")

# Directories a checkpoint usually lives in, in preference order. Searched as
# whole directories rather than as a flat list of files, because the same
# checkpoint is commonly copied into more than one of them: loading known.pt
# from two places is loading it twice, and no comparison of paths or contents
# after the fact is as simple as not doing it.
DEFAULT_MODEL_DIRS = ("models", "../models", "../ECHELON/models")

# Places a real side-scan record may be, in preference order.
SAMPLE_DIRS = ("samples", "../ECHELON/samples", "../samples")

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> bool:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)
        print(f"  FAIL  {message}")
        return False
    print(f"  ok    {message}")
    return True


def skip(reason: str) -> int:
    print(f"\nSKIPPED  {reason}")
    print("         The engine does not need a checkpoint. unit_tests.py and")
    print("         smoke_test.py cover the logic without one.")
    return 0


def find_models(given: list[str] | None) -> list[Path]:
    if given:
        return [Path(p) for p in given]
    here = Path(__file__).resolve().parent
    for directory in DEFAULT_MODEL_DIRS:
        path = here / directory
        if not path.is_dir():
            continue
        checkpoints = sorted(path.glob("*.pt"))
        if checkpoints:
            return checkpoints
    return []


def find_strip() -> Path | None:
    """A real side-scan record, if one is to hand."""
    here = Path(__file__).resolve().parent
    for directory in SAMPLE_DIRS:
        path = here / directory
        if not path.is_dir():
            continue
        for candidate in sorted(path.glob("*.jpg")) + sorted(path.glob("*.png")):
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", help="checkpoints to load")
    parser.add_argument("--strip", help="a sonar strip to tile and run over")
    parser.add_argument("--tiles", type=int, default=4,
                        help="how many tiles to run. Kept small on purpose: this "
                             "tests the seam, not the dataset.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR,
                        format="%(levelname)-7s %(message)s")

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return skip("ultralytics is not installed")

    models = find_models(args.models)
    missing = [p for p in models if not p.is_file()]
    if not models:
        return skip("no checkpoint found. Pass --models, or put known.pt in models/.")
    if missing:
        return skip(f"checkpoint not found: {', '.join(str(p) for p in missing)}")

    strip = Path(args.strip) if args.strip else find_strip()
    if strip is None or not strip.is_file():
        return skip("no sonar imagery found. Pass --strip.")

    print(f"checkpoints : {', '.join(p.name for p in models)}")
    print(f"imagery     : {strip.name}")
    print(f"tile budget : {args.tiles}\n")

    workspace = Path(tempfile.mkdtemp(prefix="hazard-real-"))
    try:
        return run(models, strip, args.tiles, workspace)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run(models: list[Path], strip: Path, budget: int, workspace: Path) -> int:
    from hazard_detect import DetectorError, UltralyticsDetector, list_tiles
    from hazard_map import build_hazard_map
    from hazard_mapview import render_map
    from survey_preparation import prepare_survey

    print("LOADING")
    started = time.perf_counter()
    try:
        detector = UltralyticsDetector(models)
    except DetectorError as exc:
        print(f"  FAIL  the checkpoint would not load: {exc}")
        return 1
    load_seconds = time.perf_counter() - started

    check(len(detector.models) == len(models),
          f"all {len(models)} checkpoint(s) loaded in {load_seconds:.1f}s")
    check(bool(detector.classes),
          f"the model reports its classes: {', '.join(detector.classes)}")
    check(detector.conf == cfg.CONF_THRESH,
          f"inference will run at CONF_THRESH={cfg.CONF_THRESH}")

    print("\nTILING")
    tiles_dir, manifest = prepare_survey([strip], workspace)
    every_tile = list_tiles(tiles_dir)
    check(bool(every_tile), f"{len(every_tile)} tile(s) produced from the strip")

    # Only a few tiles are actually run. A checkpoint that loads and infers on
    # four tiles will infer on four hundred; what this is testing is the seam,
    # and a full sweep would turn a smoke test into a batch job.
    keep = {t.name for t in every_tile[:budget]}
    for tile in every_tile[budget:]:
        tile.unlink()
    remaining = list_tiles(tiles_dir)
    check(len(remaining) == len(keep), f"running inference over {len(remaining)} tile(s)")

    print("\nINFERENCE")
    started = time.perf_counter()
    try:
        boxes = detector(remaining[0])
    except Exception as exc:
        print(f"  FAIL  inference raised {type(exc).__name__}: {exc}")
        return 1
    infer_seconds = time.perf_counter() - started
    check(True, f"inference returned in {infer_seconds:.2f}s on one tile")
    check(isinstance(boxes, list), "the detector returns a list")

    for box in boxes:
        check(set(box) >= {"class", "confidence", "bbox"},
              f"a box carries class, confidence and bbox: {sorted(box)}")
        check(0.0 <= box["confidence"] <= 1.0,
              f"confidence {box['confidence']} is within 0..1")
        check(len(box["bbox"]) == 4 and box["bbox"][2] > box["bbox"][0]
              and box["bbox"][3] > box["bbox"][1],
              f"bbox {box['bbox']} is a well-formed x1,y1,x2,y2")
        check(box["class"] in detector.classes,
              f"class {box['class']!r} is one the model declares")

    print("\nWHOLE PIPELINE")
    export = build_hazard_map(models, tiles_dir, workspace, manifest, detector=detector)
    summary = export["survey_summary"]
    print(f"        {summary['total_raw_detections']} raw -> "
          f"{summary['total_deduplicated_detections']} objects in "
          f"{summary['total_hotspots']} hotspot(s)")

    for name in ("manifest.csv", "manifest.json", "export.json", "actions.csv"):
        check((workspace / name).is_file(), f"{name} written")

    render_map(export, workspace, tiles_dir, manifest, title="real model test")
    check((workspace / "map.html").is_file(), "map.html written")

    check(json.loads((workspace / "export.json").read_text()) == export,
          "export.json on disk matches what was returned")

    # Whatever the model emitted, the engine must have scored it and never
    # dropped it for being an unfamiliar class.
    for detection in export["detections"]:
        check(detection["severity"] == round(
            detection["class_weight"] * detection["confidence"], 4),
            f"{detection['id']}: severity is weight x confidence")
        check(detection["class_weight"] > 0,
              f"{detection['id']}: class {detection['object_class']!r} was not "
              f"weighted out of existence")

    # This imagery carries no navigation, so nothing may claim a position.
    check(all(d["latitude"] is None for d in export["detections"]),
          "no detection claims a position, because this record has no navigation")
    check(summary["coordinate_mode"] == cfg.COORD_MODE_RELATIVE,
          f"the survey is marked '{cfg.COORD_MODE_RELATIVE}'")

    print("\nVALIDATION")
    from validate_output import Report, validate

    report = Report()
    validate(workspace, report)
    for failure in report.failures:
        print(f"  FAIL  {failure}")
        FAILURES.append(failure)
    check(not report.failures,
          f"the output validator passes on real-model output "
          f"({report.passed} checks)")

    print()
    if FAILURES:
        print(f"FAILED  {len(FAILURES)} of {CHECKS} checks")
        return 1
    print(f"PASSED  {CHECKS}/{CHECKS} checks against a real checkpoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
