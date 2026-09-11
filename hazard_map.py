"""Module 2. A tile set in, a ranked hazard picture out.

    from hazard_map import build_hazard_map
    export = build_hazard_map("models/known.pt", "out/tiles", "out/")

Nothing in this module imports a dashboard, a web framework, a retriever or a
language model. It is a library, it runs offline, and the only heavy dependency
is whatever the detector needs. That separation is the point:

    THE HAZARD MAP ANSWERS   where things are and how urgent they are
    THE RAG ASSISTANT ANSWERS what a thing is and what is known about it

Those two questions have different evidence and different failure modes. A
severity score is arithmetic over a detector's output and is reproducible. A
grounded answer about an object is retrieval over a document corpus. Merging
them would let a confident sentence raise a priority, or a priority imply a
fact, and neither is something either system can support.

THE PIPELINE
    tiles + manifest
      -> detector, loaded once, run over every tile      hazard_detect
      -> raw boxes into survey coordinates               hazard_coords
      -> severity = class_weight * confidence            hazard_severity
      -> duplicates from overlapping tiles merged        hazard_dedup
      -> geographic position attached, or null           hazard_geo
      -> detections aggregated into ranked hotspots      hazard_hotspots
      -> export.json and actions.csv                     hazard_export
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import hazard_config as cfg
from hazard_coords import attach_geo, to_global
from hazard_dedup import deduplicate, merge_across_models
from hazard_detect import Detector, UltralyticsDetector, list_tiles, run_detector
from hazard_export import (build_export, build_summary, run_configuration,
                           safe_model_reference, utc_now, write_actions, write_export)
from hazard_geo import build_references, references_from_manifest
from hazard_hotspots import build_hotspots
from hazard_severity import apply_confidence_floor, score_detection
from survey_preparation import load_manifest

log = logging.getLogger("deepecho.hazard")


def _find_manifest(tiles_dir: Path, manifest: Any) -> Path | None:
    """The manifest the caller named, or the one sitting beside the tiles."""
    if manifest is not None:
        return Path(manifest)
    for candidate in (tiles_dir.parent / cfg.MANIFEST_JSON,
                      tiles_dir.parent / cfg.MANIFEST_CSV,
                      tiles_dir / cfg.MANIFEST_JSON,
                      tiles_dir / cfg.MANIFEST_CSV):
        if candidate.is_file():
            return candidate
    return None


def _inherit_tile_positions(detections: list[dict[str, Any]],
                            rows: dict[str, dict[str, Any]],
                            already_located: set[str]) -> int:
    """Give a detection its tile's recorded fix when its strip could not be fitted.

    Used only for a strip with too few located tiles to fit a transform. The
    position is a real recorded one, just coarser than the detection: it is the
    centre of the tile, not the object inside it.
    """
    inherited = 0
    for detection in detections:
        if detection.get("latitude") is not None:
            continue
        if str(detection.get("strip") or "") in already_located:
            continue
        row = rows.get(detection["representative_tile"])
        if not row or row.get("lat") in (None, "") or row.get("lon") in (None, ""):
            continue
        detection["latitude"] = float(row["lat"])
        detection["longitude"] = float(row["lon"])
        detection["position_precision"] = "tile centre"
        inherited += 1
    return inherited


def build_hazard_map(model_path: Any, tiles_dir: Any, out_dir: Any, manifest: Any = None,
                     *, detector: Detector | None = None, nav: Any = None,
                     conf: float | None = None, merge_dist: float | None = None,
                     grid: int | None = None, top_n: int | None = None,
                     demo: bool = False, title: str | None = None) -> dict[str, Any]:
    """Detect, deduplicate, score, aggregate and export one survey.

    model_path
        A YOLOv8 checkpoint. Loaded once, for the whole run.
    tiles_dir
        The directory prepare_survey() wrote.
    out_dir
        export.json and actions.csv are written here.
    manifest
        The manifest path. Found automatically beside the tiles if omitted.
        Without one, tile positions are recovered from the {strip}_{x}_{y}
        filenames and there is no geographic position at all.

    detector
        A callable replacing the built-in loader, for a checkpoint hosted
        elsewhere -- in DeepEcho it is the subprocess worker that keeps torch
        away from faiss. See hazard_detect for the interface.
    nav
        Navigation for this run, in prepare_survey's formats. Normally omitted:
        positions come from the manifest. Supply it to use the original
        transform instead of the one refitted from the manifest.
    conf, merge_dist, grid, top_n
        Per-run overrides of CONF_THRESH, MERGE_DIST, GRID and TOP_N_HOTSPOTS.
    title
        A human label for the survey, shown wherever one is listed. Separate
        from survey_id, which is an identifier and stays stable.
    demo
        Marks every output as synthetic. Set by demo_survey.py and by nothing
        else. It is a first-class field rather than a note added afterwards,
        so a demo export cannot be mistaken for a real one by a consumer that
        only reads the JSON.

    Returns the export dictionary, the same object written to export.json.
    """
    started = time.perf_counter()
    tiles_dir = Path(tiles_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- inputs ------------------------------------------------------------
    manifest_path = _find_manifest(tiles_dir, manifest)
    rows: list[dict[str, Any]] = []
    survey_meta: dict[str, Any] = {}
    if manifest_path is not None:
        rows, survey_meta = load_manifest(manifest_path)
        log.info("manifest: %s, %d tiles", manifest_path.name, len(rows))
    else:
        log.warning("no manifest found beside %s; tile positions will be read from "
                    "filenames and no geographic position is available", tiles_dir)

    by_tile = {str(row["tile"]): row for row in rows}
    tiles = list_tiles(tiles_dir)
    if not tiles:
        raise FileNotFoundError(f"no tile images in {tiles_dir}")

    # --- detection ---------------------------------------------------------
    if detector is None:
        detector = UltralyticsDetector(model_path, conf=conf)
    threshold = float(getattr(detector, "conf", cfg.CONF_THRESH if conf is None else conf))

    raw, failed_tiles = run_detector(detector, tiles, by_tile)
    raw_count = len(raw)

    # --- survey coordinates and severity ----------------------------------
    to_global(raw)
    # Two checkpoints seeing one object in one tile is folded first, before
    # anything counts detections. Otherwise a wreck both models found is two
    # contacts and doubles its own hotspot's severity.
    raw = merge_across_models(raw)
    # The floor runs BEFORE scoring, because withholding a class changes what
    # the object is called and therefore what it weighs. It never drops a box.
    withheld = 0
    for detection in raw:
        apply_confidence_floor(detection)
        withheld += "class_withheld" in detection
        score_detection(detection)
    if withheld:
        log.info("%d detection(s) had their class withheld for sitting below its "
                 "per-class confidence floor; all are still reported as unidentified",
                 withheld)

    # --- deduplication -----------------------------------------------------
    detections = deduplicate(raw, merge_dist=merge_dist)

    # --- geographic position, or an honest null ---------------------------
    if nav is not None:
        sizes = {str(row["strip"]): (int(row.get("width") or 0), int(row.get("height") or 0))
                 for row in rows}
        references, nav_source = build_references(nav, sizes)
        nav_source["source"] = f"{nav_source.get('source')} (supplied to build_hazard_map)"
    else:
        references, nav_source = references_from_manifest(rows)

    attach_geo(detections, references)
    inherited = _inherit_tile_positions(detections, by_tile, set(references))
    if inherited:
        nav_source["detections_inheriting_tile_position"] = inherited
        log.info("%d detection(s) took their tile's recorded position because their "
                 "strip had too few fixes to fit a transform", inherited)

    georeferenced = any(d.get("latitude") is not None for d in detections)
    coordinate_mode = cfg.COORD_MODE_GEO if georeferenced else cfg.COORD_MODE_RELATIVE

    # --- hotspots ----------------------------------------------------------
    hotspots = build_hotspots(detections, references, grid=grid)

    # --- export ------------------------------------------------------------
    strips = sorted({str(row["strip"]) for row in rows} or
                    {str(d.get("strip") or "") for d in detections})
    summary = build_summary(
        raw_count=raw_count, detections=detections, hotspots=hotspots,
        strips=strips, tiles=len(tiles), georeferenced=georeferenced,
        coordinate_mode=coordinate_mode)

    model_reference = safe_model_reference(model_path)
    elapsed = time.perf_counter() - started

    configuration = run_configuration()
    configuration["detection"]["CONF_THRESH"] = threshold
    if merge_dist is not None:
        configuration["deduplication"]["MERGE_DIST"] = float(merge_dist)
    if grid is not None:
        configuration["hotspots"]["GRID"] = int(grid)

    metadata = {
        "engine": cfg.ENGINE_NAME,
        "processing_version": cfg.PROCESSING_VERSION,
        "processed_at": utc_now(),
        "processing_seconds": round(elapsed, 3),
        "survey_id": survey_meta.get("survey_id") or out_dir.resolve().name,
        "title": title or survey_meta.get("title") or out_dir.resolve().name,
        "coordinate_mode": coordinate_mode,
        "confidence_threshold": threshold,
        **model_reference,
        "detector_classes": list(getattr(detector, "classes", []) or []),
        "detector": getattr(detector, "name", type(detector).__name__),
        "demo": demo,
    }
    if demo:
        metadata["data_source"] = "SYNTHETIC DEMO DATA"
        metadata["demo_warning"] = (
            "Every detection in this file was generated by demo_survey.py. No "
            "sonar was recorded, no real object was detected, and nothing here "
            "is evidence of anything.")

    provenance = {
        "demo": demo,
        "processing_version": cfg.PROCESSING_VERSION,
        "severity_policy_version": cfg.SEVERITY_POLICY_VERSION,
        "coordinate_mode": coordinate_mode,
        "coordinate_note": (
            "global_x and global_y are pixel offsets within their own strip and "
            "are present for every detection. Latitude and longitude are null "
            "wherever navigation does not support one, and are never inferred."),
        "navigation": nav_source,
        "source_strips": survey_meta.get("strips", [{"strip": s} for s in strips]),
        "tile_count": len(tiles),
        "tiles_in_manifest": len(rows),
        "tiles_processed": len(tiles) - len(failed_tiles),
        # Empty on a clean run. A populated list says the survey is incomplete
        # and names which tiles are missing from it.
        "tiles_failed": failed_tiles,
        "manifest": None if manifest_path is None else manifest_path.name,
        "tiling": survey_meta.get("tiling", {}),
        "model": model_reference,
        "confidence_threshold": threshold,
        "severity_formula": "severity = class_weight * confidence",
        "class_confidence_floors": dict(cfg.CLASS_CONFIDENCE_FLOOR),
        "class_floor_rule": (
            "a detection below its class's floor is relabelled "
            f"'{cfg.DOWNGRADE_LABEL}' and never dropped; the original call is "
            "kept in the detection's downgraded_from. This changes the claim, "
            "not the direction of the score: it lowers severity only for "
            "classes weighted above UNKNOWN_CLASS_SEVERITY."),
        "class_floors_withheld": withheld,
        "ranking_rule": "hotspots sorted by total_severity descending; "
                        "H001 is the highest priority",
        "audit_note": (
            "Every hotspot carries a `rationale` naming the detection that set "
            "its severity, and every detection carries the tiles it was seen in "
            "and how many views were merged into it."),
    }

    export = build_export(metadata=metadata, summary=summary, detections=detections,
                          hotspots=hotspots, provenance=provenance,
                          configuration=configuration)

    export_path = write_export(out_dir, export)
    actions_path = write_actions(out_dir, hotspots, top_n=top_n)

    tiers = summary["detections_by_tier"]
    hotspot_tiers = summary["hotspots_by_tier"]
    log.info(
        "survey complete | strips=%d tiles=%d raw=%d deduplicated=%d duplicates_removed=%d "
        "| detections critical=%d medium=%d low=%d "
        "| hotspots=%d (critical=%d medium=%d low=%d) "
        "| total_severity=%.3f coordinates=%s time=%.2fs",
        summary["strips_processed"], summary["tiles_processed"], raw_count,
        len(detections), summary["duplicates_removed"],
        tiers.get("critical", 0), tiers.get("medium", 0), tiers.get("low", 0),
        len(hotspots), hotspot_tiers.get("critical", 0), hotspot_tiers.get("medium", 0),
        hotspot_tiers.get("low", 0),
        summary["total_severity"], coordinate_mode, elapsed)
    if demo:
        log.warning("SYNTHETIC DEMO DATA: this export was generated from a "
                    "simulated survey and is not evidence of anything")
    log.info("wrote %s and %s", export_path.name, actions_path.name)

    return export
