"""Module 1. Sonar strips in, a positioned tile set out.

    from survey_preparation import prepare_survey
    tiles_dir, manifest_path = prepare_survey(["survey/strip_a.png"], "out/")

A side-scan strip is long, thin and far larger than any detector's input. This
module cuts it into overlapping 640-pixel tiles, records where each tile came
from, and writes a manifest that lets every later stage put a detection back
where it was found.

The manifest is the contract. Everything downstream reads positions from it and
never re-derives them from a filename, so the pixel arithmetic in this file is
the only place it happens.

WHAT A TILE IS CALLED
    {strip}_{x}_{y}.jpg, where x and y are the tile's top-left offset in the
    ORIGINAL strip, in pixels. Not a tile index. A tile's name therefore states
    its position, and the name is reproducible from the manifest and back.

COVERAGE
    Offsets march in steps of STRIDE and stop as soon as the next tile would
    start past the end of the strip, so the last tile in each direction is
    partial and every pixel of the strip is covered exactly once or twice.
    Because STRIDE is smaller than TILE, a partial tile is never narrower than
    TILE - STRIDE, so the run never produces a useless sliver.

MEMORY
    Strips are opened one at a time and each tile is written before the next is
    cut. Peak memory is one strip plus one tile, not the whole survey, so the
    number of strips does not change the footprint.

DETERMINISM
    Strips are processed in sorted order, offsets ascend, and nothing depends
    on dictionary iteration or wall-clock time. The same inputs produce
    byte-identical tiles and the same manifest rows in the same order.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import hazard_config as cfg
from hazard_geo import Georeference, build_references

log = logging.getLogger("deepecho.hazard")

# Image formats taken seriously as survey strips when a directory is passed.
STRIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")

# A survey strip is legitimately enormous, and Pillow's default bomb guard
# fires at ~179 megapixels. Raised rather than disabled: an accidental 20
# gigapixel input should still stop rather than exhaust the machine.
MAX_STRIP_PIXELS = 4_000_000_000


def _resolve_strips(strip_paths: Any) -> list[Path]:
    """One path, several paths, or a directory. Always sorted, always files."""
    if strip_paths is None:
        raise ValueError("strip_paths is required")
    if isinstance(strip_paths, (str, Path)):
        strip_paths = [strip_paths]
    if not isinstance(strip_paths, Iterable):
        raise TypeError("strip_paths must be a path or an iterable of paths")

    resolved: list[Path] = []
    for entry in strip_paths:
        path = Path(entry)
        if path.is_dir():
            resolved.extend(sorted(p for p in path.iterdir()
                                   if p.suffix.lower() in STRIP_SUFFIXES))
        elif path.is_file():
            resolved.append(path)
        else:
            raise FileNotFoundError(f"survey strip not found: {path}")

    if not resolved:
        raise ValueError("no survey strips found in the given paths")
    return sorted(dict.fromkeys(resolved), key=lambda p: (p.name, str(p)))


def _strip_names(paths: Sequence[Path]) -> dict[Path, str]:
    """A stable, unique name per strip, taken from the file stem.

    Two strips in different folders can share a stem. Since the stem becomes
    part of every tile filename, a collision would have one strip's tiles
    overwrite another's, so the second occurrence is suffixed.
    """
    names: dict[Path, str] = {}
    used: dict[str, int] = {}
    for path in paths:
        stem = path.stem
        count = used.get(stem, 0)
        used[stem] = count + 1
        names[path] = stem if count == 0 else f"{stem}-{count + 1}"
    return names


def _offsets(extent: int, tile: int, stride: int) -> list[int]:
    """Tile origins along one axis. See COVERAGE in the module docstring."""
    if extent <= tile:
        return [0]
    origins = [0]
    while origins[-1] + tile < extent:
        origins.append(origins[-1] + stride)
    return origins


def _denoise(array, percentiles: tuple[float, float]):
    """Median filter plus a conservative percentile stretch. Intensity only.

    Geometry is untouched on purpose: a tile's pixel grid IS the survey's
    coordinate system, so any resize, rotation or pad would move every object
    in it away from its recorded position.
    """
    import numpy as np
    from PIL import Image, ImageFilter

    filtered = np.asarray(
        Image.fromarray(array).filter(ImageFilter.MedianFilter(cfg.DENOISE_MEDIAN_SIZE)),
        dtype=np.float32)

    low, high = np.percentile(filtered, percentiles)
    if high <= low:
        # A flat tile has nothing to stretch. Returning it unchanged is
        # correct; dividing by zero and calling the result contrast is not.
        return filtered.astype(np.uint8)
    return np.clip((filtered - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)


def _grey(array):
    """The 2-D grey view used for scoring, whatever the tile's mode."""
    import numpy as np

    if array.ndim == 2:
        return array
    # Rec. 601 luma. The weights matter less than being consistent, since the
    # score is compared against a threshold, not against another system.
    return (array[..., 0] * 0.299 + array[..., 1] * 0.587 + array[..., 2] * 0.114
            ).astype(np.float32)


class StripUnreadableError(ValueError):
    """Every strip in the survey failed to open."""


def _tile_strip(path: Path, strip: str, size: tuple[int, int],
                reference: "Georeference | None", tiles_dir: Path,
                rows: list[dict[str, Any]]) -> int:
    """Cut one strip into tiles, appending manifest rows. Returns tiles skipped.

    Separated from prepare_survey so that a strip which cannot be read fails on
    its own rather than taking the survey with it. Raises only for a problem
    with this strip; the caller decides what a failure means for the batch.
    """
    import numpy as np
    from PIL import Image

    width, height = size
    skipped = 0

    with Image.open(path) as image:
        # Palette and bilevel images are promoted; anything else keeps its
        # mode so a grey strip stays a single channel on disk.
        if image.mode in ("P", "1", "I", "F", "LA", "RGBA", "CMYK"):
            image = image.convert("L" if image.mode in ("1", "I", "F", "LA") else "RGB")

        xs = _offsets(width, cfg.TILE, cfg.STRIDE)
        ys = _offsets(height, cfg.TILE, cfg.STRIDE)
        log.info("strip %s: %dx%d px, %d x %d tile grid",
                 strip, width, height, len(xs), len(ys))

        for y in ys:
            for x in xs:
                right, bottom = min(x + cfg.TILE, width), min(y + cfg.TILE, height)
                array = np.asarray(image.crop((x, y, right, bottom)))
                if cfg.DENOISE:
                    array = _denoise(array, cfg.DENOISE_CLIP_PERCENTILES)

                # Scored on the pixels as written, so the filter judges
                # exactly what the detector will be shown.
                grey = _grey(array)
                content_score = float(np.std(grey)) / 255.0
                if content_score < cfg.MIN_CONTENT:
                    skipped += 1
                    continue

                tile_w, tile_h = right - x, bottom - y
                center_x, center_y = x + tile_w / 2.0, y + tile_h / 2.0
                lat, lon = reference.locate(center_x, center_y) if reference else (None, None)

                name = f"{strip}_{x}_{y}.jpg"
                Image.fromarray(array).save(
                    tiles_dir / name, "JPEG", quality=cfg.TILE_JPEG_QUALITY)

                rows.append({
                    "tile": name,
                    "strip": strip,
                    "x": x,
                    "y": y,
                    "lat": lat,
                    "lon": lon,
                    "mean_intensity": round(float(np.mean(grey)), 3),
                    "width": width,
                    "height": height,
                    "tile_width": tile_w,
                    "tile_height": tile_h,
                    "center_x": center_x,
                    "center_y": center_y,
                    "source_image": path.name,
                    "denoised": cfg.DENOISE,
                    "content_score": round(content_score, 6),
                })

    return skipped


def prepare_survey(strip_paths: Any, out_dir: Any, nav: Any = None) -> tuple[Path, Path]:
    """Cut survey strips into positioned tiles and write the manifest.

    strip_paths
        A path, a list of paths, or a directory of images.
    out_dir
        Created if absent. Tiles go in out_dir/tiles, the manifest beside them.
    nav
        None for a relative survey, which is the default and produces null
        lat/lon everywhere. A path to a control-point CSV, or a dict of
        four-corner coordinates per strip. See hazard_geo for both formats.

    Returns (tiles_dir, manifest_csv_path).
    """
    import numpy as np
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_STRIP_PIXELS

    started = datetime.now(timezone.utc)
    paths = _resolve_strips(strip_paths)
    names = _strip_names(paths)

    out_dir = Path(out_dir)
    tiles_dir = out_dir / cfg.TILES_DIRNAME
    tiles_dir.mkdir(parents=True, exist_ok=True)

    # Sizes first, from the headers alone: the georeference for a four-corner
    # strip needs the strip's dimensions before any pixel is read.
    #
    # This is also where an unreadable file is caught, because opening a header
    # is the cheapest way to find out. A file that fails here is dropped from
    # the survey with its reason recorded, rather than taking the batch with it.
    sizes: dict[str, tuple[int, int]] = {}
    unreadable: list[dict[str, str]] = []
    for path in list(paths):
        try:
            with Image.open(path) as image:
                sizes[names[path]] = (image.width, image.height)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            unreadable.append({"strip": names[path], "source_image": path.name,
                               "error": reason})
            log.error("strip %s could not be opened and was skipped: %s",
                      path.name, reason)
            paths.remove(path)

    if not sizes:
        raise StripUnreadableError(
            "no survey strip could be opened. "
            + "; ".join(f"{u['source_image']} ({u['error']})" for u in unreadable))

    references, nav_source = build_references(nav, sizes)
    if references:
        log.info("navigation: %s, located %d of %d strips",
                 nav_source["mode"], len(references), len(sizes))
    else:
        log.info("navigation: none supplied, survey is in relative pixel coordinates")

    rows: list[dict[str, Any]] = []
    skipped = 0

    for path in paths:
        strip = names[path]
        # A survey is a batch, and one bad file in it is a bad file, not a
        # failed survey. A truncated strip, or a JPEG that never finished
        # copying, is skipped with its reason recorded and the rest of the
        # survey still runs. Silence would be worse than either failure mode,
        # so the skip and its reason go into the manifest and the log.
        try:
            skipped += _tile_strip(path, strip, sizes[strip], references.get(strip),
                                   tiles_dir, rows)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            unreadable.append({"strip": strip, "source_image": path.name, "error": reason})
            log.error("strip %s could not be read and was skipped: %s", path.name, reason)

    if unreadable and not rows:
        raise StripUnreadableError(
            "no survey strip could be read. "
            + "; ".join(f"{u['source_image']} ({u['error']})" for u in unreadable))

    manifest_csv = out_dir / cfg.MANIFEST_CSV
    manifest_json = out_dir / cfg.MANIFEST_JSON
    columns = list(cfg.MANIFEST_REQUIRED_COLUMNS) + [
        c for c in (rows[0] if rows else {}) if c not in cfg.MANIFEST_REQUIRED_COLUMNS]

    with manifest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        # An empty cell, not the string "None": a reader that sees "None" in a
        # latitude column has been handed a value that looks like data.
        writer.writerows([{k: ("" if v is None else v) for k, v in row.items()} for row in rows])

    survey = {
        "generated_at": started.isoformat(timespec="seconds"),
        "engine": cfg.ENGINE_NAME,
        "processing_version": cfg.PROCESSING_VERSION,
        "strips": [{"strip": names[p], "source_image": p.name,
                    "width": sizes[names[p]][0], "height": sizes[names[p]][1]} for p in paths],
        "tiles_written": len(rows),
        "tiles_skipped_low_content": skipped,
        "strips_unreadable": unreadable,
        "coordinate_mode": cfg.COORD_MODE_GEO if references else cfg.COORD_MODE_RELATIVE,
        "navigation": nav_source,
        "tiling": {"tile": cfg.TILE, "stride": cfg.STRIDE, "overlap": cfg.TILE - cfg.STRIDE,
                   "min_content": cfg.MIN_CONTENT, "denoise": cfg.DENOISE,
                   "content_score": "standard deviation of the tile's grey levels / 255, "
                                    "measured on the tile as written"},
    }
    manifest_json.write_text(
        json.dumps({"survey": survey, "tiles": rows}, indent=2), encoding="utf-8")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    log.info("prepared %d strips: %d tiles written, %d skipped below MIN_CONTENT=%.3f, %.2fs",
             len(paths), len(rows), skipped, cfg.MIN_CONTENT, elapsed)
    if not rows:
        log.warning("no tile met MIN_CONTENT=%.3f; lower it or check the strips",
                    cfg.MIN_CONTENT)

    return tiles_dir, manifest_csv


def load_manifest(path: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a manifest back, from either the JSON or the CSV.

    Returns (tile rows, survey metadata). The JSON is preferred because it
    keeps types and carries the survey block; the CSV is accepted so a manifest
    edited in a spreadsheet still loads.
    """
    path = Path(path)
    if path.is_dir():
        path = path / cfg.MANIFEST_JSON if (path / cfg.MANIFEST_JSON).is_file() \
            else path / cfg.MANIFEST_CSV
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload, {}
        return payload.get("tiles", []), payload.get("survey", {})

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value == "" or value is None:
                    row[key] = None
                elif key in ("tile", "strip", "source_image"):
                    row[key] = value
                elif key == "denoised":
                    row[key] = str(value).strip().lower() in {"1", "true", "yes"}
                else:
                    try:
                        row[key] = int(value) if key in ("x", "y", "width", "height",
                                                         "tile_width", "tile_height") \
                            else float(value)
                    except ValueError:
                        row[key] = value
            rows.append(row)

    sidecar = path.parent / cfg.MANIFEST_JSON
    survey = {}
    if sidecar.is_file():
        survey = json.loads(sidecar.read_text(encoding="utf-8")).get("survey", {})
    return rows, survey
