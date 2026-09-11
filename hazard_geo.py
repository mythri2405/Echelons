"""Pixels to latitude and longitude, or an honest refusal.

Everything in this module exists to keep one promise: the system never invents
a position. A tile that cannot be located carries lat = None and lon = None,
and the survey is marked "Relative Survey Coordinates". Relative pixel
coordinates are always preserved, with or without navigation, because they are
the survey's real spatial identity and a geographic fix is a decoration on top
of them.

Two navigation inputs are supported.

CONTROL POINTS (a CSV of pixel -> lat/lon fixes)
    Columns, case-insensitive, in any order:
        strip       the strip's name, matching the image file's stem
        pixel_x     column in the original strip, "x" also accepted
        pixel_y     row in the original strip, "y" also accepted
        latitude    decimal degrees, "lat" also accepted
        longitude   decimal degrees, "lon" or "lng" also accepted

    With three or more fixes that are not collinear, a first-order affine
    transform is fitted by least squares:

        lon = a*px + b*py + c
        lat = d*px + e*py + f

    Six parameters from a linear solve. The fit's residual is reported so a bad
    nav file shows up as a number rather than as quietly wrong positions.

    A side-scan nav file often holds one fix per ping row, so every fix shares
    the same pixel column and the points are collinear. An affine fit is then
    underdetermined across-track and would be a fabrication. That case falls
    back to one-dimensional interpolation along the track line, and the tile's
    position is the along-track position of its centre row. Across-track
    displacement is NOT resolved, and the export says so in
    `provenance.navigation.across_track_resolved`, because without a range
    scale there is nothing to resolve it from.

FOUR CORNERS (the geographic corners of the whole strip)
    A dict per strip with top_left, top_right, bottom_left and bottom_right,
    each [latitude, longitude] in decimal degrees. A tile centre at normalised
    position (u, v) is interpolated bilinearly between them.

Both methods assume the strip covers a small enough area that the seabed is
flat and degrees are locally linear, which is true of a survey strip and not
true of a basin. Neither is valid across the antimeridian or over a pole.

Every position is computed from the TILE CENTRE, never its top-left corner.
Locating a 640-pixel tile by its corner puts it half a tile off, consistently,
in the same direction, which is the kind of error that survives review because
everything looks plausible.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Iterable

# Below this, the second singular value of the centred control points is noise
# and the points are treated as lying on a line. Scaled against the first
# singular value, so it is a shape test and does not care about survey size.
COLLINEAR_RATIO = 1e-6

_LAT_KEYS = ("latitude", "lat")
_LON_KEYS = ("longitude", "lon", "lng", "long")
_X_KEYS = ("pixel_x", "x", "px")
_Y_KEYS = ("pixel_y", "y", "py")


class NavigationError(ValueError):
    """The navigation input was given but cannot be used as supplied."""


def _pick(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and str(row[key]).strip() != "":
            return row[key]
    return None


def _as_pair(value: Any) -> tuple[float, float]:
    """A corner, as [lat, lon] or {"latitude": .., "longitude": ..}."""
    if isinstance(value, dict):
        lat = _pick(value, _LAT_KEYS)
        lon = _pick(value, _LON_KEYS)
        if lat is None or lon is None:
            raise NavigationError(f"corner {value!r} needs a latitude and a longitude")
        return float(lat), float(lon)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise NavigationError(f"corner {value!r} must be [latitude, longitude]")


def _check_degrees(lat: float, lon: float, where: str) -> None:
    if not (-90.0 <= lat <= 90.0):
        raise NavigationError(f"{where}: latitude {lat} is outside -90..90")
    if not (-180.0 <= lon <= 180.0):
        raise NavigationError(f"{where}: longitude {lon} is outside -180..180")


class Georeference:
    """Locates a tile centre within one strip, or refuses to.

    `mode` is "affine", "along_track" or "corners". A strip with no usable
    navigation gets no Georeference at all and its tiles carry nulls.
    """

    def __init__(self, strip: str, mode: str, detail: dict[str, Any]) -> None:
        self.strip = strip
        self.mode = mode
        self.detail = detail

    # -- construction -------------------------------------------------------

    @classmethod
    def from_control_points(cls, strip: str, points: list[tuple[float, float, float, float]]
                            ) -> "Georeference":
        """points are (pixel_x, pixel_y, latitude, longitude)."""
        import numpy as np

        if len(points) < 2:
            raise NavigationError(
                f"strip {strip!r}: {len(points)} navigation fix(es); at least 2 are needed")

        array = np.asarray(points, dtype=float)
        pixels, lats, lons = array[:, :2], array[:, 2], array[:, 3]

        centred = pixels - pixels.mean(axis=0)
        singular = np.linalg.svd(centred, compute_uv=False)
        spread = float(singular[0])
        if spread <= 0.0:
            raise NavigationError(
                f"strip {strip!r}: every navigation fix is at the same pixel")
        collinear = float(singular[1]) / spread < COLLINEAR_RATIO

        if collinear or len(points) < 3:
            # One fix per ping row, the usual side-scan case. Project every fix
            # onto the track line and interpolate along it. Across-track is
            # left unresolved rather than guessed.
            direction = centred[np.argmax(np.abs(centred).sum(axis=1))]
            norm = float(np.linalg.norm(direction))
            direction = direction / norm if norm > 0 else np.array([0.0, 1.0])
            t = centred @ direction
            order = np.argsort(t)
            return cls(strip, "along_track", {
                "origin": pixels.mean(axis=0).tolist(),
                "direction": direction.tolist(),
                "t": t[order].tolist(),
                "lat": lats[order].tolist(),
                "lon": lons[order].tolist(),
                "fixes": len(points),
                "across_track_resolved": False,
                "method": "1-D linear interpolation along the fitted track line, "
                          "extrapolated linearly from the end segment beyond the "
                          "outermost fix",
            })

        # Three or more fixes with genuine two-dimensional spread: fit an
        # affine transform and report how well it fits.
        design = np.column_stack([pixels[:, 0], pixels[:, 1], np.ones(len(pixels))])
        lon_coef, *_ = np.linalg.lstsq(design, lons, rcond=None)
        lat_coef, *_ = np.linalg.lstsq(design, lats, rcond=None)
        residual = float(np.max(np.hypot(design @ lat_coef - lats, design @ lon_coef - lons)))
        return cls(strip, "affine", {
            "lat_coefficients": lat_coef.tolist(),
            "lon_coefficients": lon_coef.tolist(),
            "fixes": len(points),
            "max_residual_degrees": round(residual, 9),
            "across_track_resolved": True,
            "method": "first-order affine transform fitted by least squares over "
                      "all navigation fixes",
        })

    @classmethod
    def from_corners(cls, strip: str, corners: dict[str, Any],
                     width: int, height: int) -> "Georeference":
        missing = [k for k in ("top_left", "top_right", "bottom_left", "bottom_right")
                   if k not in corners]
        if missing:
            raise NavigationError(f"strip {strip!r}: corners missing {', '.join(missing)}")
        resolved = {}
        for key in ("top_left", "top_right", "bottom_left", "bottom_right"):
            lat, lon = _as_pair(corners[key])
            _check_degrees(lat, lon, f"strip {strip!r} {key}")
            resolved[key] = (lat, lon)
        return cls(strip, "corners", {
            "corners": {k: list(v) for k, v in resolved.items()},
            "width": width,
            "height": height,
            "across_track_resolved": True,
            "method": "bilinear interpolation of the four strip corners over "
                      "normalised pixel position",
        })

    # -- use ----------------------------------------------------------------

    def locate(self, center_x: float, center_y: float) -> tuple[float | None, float | None]:
        """Latitude and longitude of a tile or detection centre, in degrees."""
        if self.mode == "corners":
            return self._locate_corners(center_x, center_y)
        if self.mode == "affine":
            return self._locate_affine(center_x, center_y)
        return self._locate_along_track(center_x, center_y)

    def _locate_corners(self, cx: float, cy: float) -> tuple[float, float]:
        detail = self.detail
        corners = detail["corners"]
        # Normalise against the last addressable pixel, so the far corner lands
        # exactly on the far corner rather than one pixel short of it.
        span_x = max(detail["width"] - 1, 1)
        span_y = max(detail["height"] - 1, 1)
        u = min(max(cx / span_x, 0.0), 1.0)
        v = min(max(cy / span_y, 0.0), 1.0)
        out = []
        for axis in (0, 1):
            top = (1 - u) * corners["top_left"][axis] + u * corners["top_right"][axis]
            bottom = (1 - u) * corners["bottom_left"][axis] + u * corners["bottom_right"][axis]
            out.append((1 - v) * top + v * bottom)
        return round(out[0], 8), round(out[1], 8)

    def _locate_affine(self, cx: float, cy: float) -> tuple[float, float]:
        a, b, c = self.detail["lat_coefficients"]
        d, e, f = self.detail["lon_coefficients"]
        return round(a * cx + b * cy + c, 8), round(d * cx + e * cy + f, 8)

    def _locate_along_track(self, cx: float, cy: float) -> tuple[float, float]:
        ox, oy = self.detail["origin"]
        dx, dy = self.detail["direction"]
        t = (cx - ox) * dx + (cy - oy) * dy
        return (round(_interpolate(t, self.detail["t"], self.detail["lat"]), 8),
                round(_interpolate(t, self.detail["t"], self.detail["lon"]), 8))

    def describe(self) -> dict[str, Any]:
        """What went into this fix, for the provenance block."""
        described = {"strip": self.strip, "mode": self.mode}
        described.update({k: v for k, v in self.detail.items()
                          if k not in {"t", "lat", "lon", "origin", "direction"}})
        return described


def _interpolate(t: float, knots: list[float], values: list[float]) -> float:
    """Linear interpolation, extrapolated from the end segment beyond the ends.

    numpy.interp clamps instead, which would put every tile past the last
    navigation fix at exactly that fix's position. Clamping looks safe and is
    not: it silently stacks detections on a single point. Extrapolating from
    the end segment is the same first-order assumption the interior already
    rests on, applied consistently.
    """
    if len(knots) == 1:
        return values[0]
    if t <= knots[0]:
        lo, hi = 0, 1
    elif t >= knots[-1]:
        lo, hi = len(knots) - 2, len(knots) - 1
    else:
        hi = next(i for i in range(1, len(knots)) if knots[i] >= t)
        lo = hi - 1
    span = knots[hi] - knots[lo]
    if span == 0:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (t - knots[lo]) / span


# --- Loading ---------------------------------------------------------------


def load_control_points(path: Path) -> dict[str, list[tuple[float, float, float, float]]]:
    """Navigation fixes from a CSV, grouped by strip."""
    path = Path(path)
    if not path.is_file():
        raise NavigationError(f"navigation file not found: {path}")

    grouped: dict[str, list[tuple[float, float, float, float]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise NavigationError(f"{path.name} has no header row")
        # Normalise the header once so "Pixel_X" and "pixel_x" are the same.
        for raw in reader:
            row = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
            strip = _pick(row, ("strip", "strip_name", "source", "image"))
            px, py = _pick(row, _X_KEYS), _pick(row, _Y_KEYS)
            lat, lon = _pick(row, _LAT_KEYS), _pick(row, _LON_KEYS)
            if None in (px, py, lat, lon):
                continue
            try:
                values = (float(px), float(py), float(lat), float(lon))
            except (TypeError, ValueError) as exc:
                raise NavigationError(f"{path.name}: non-numeric row {raw!r}") from exc
            _check_degrees(values[2], values[3], f"{path.name} row for {strip!r}")
            key = str(strip).strip() if strip is not None else ""
            grouped.setdefault(Path(key).stem if key else "", []).append(values)

    if not grouped:
        raise NavigationError(
            f"{path.name}: no usable rows. Needs strip, pixel_x, pixel_y, "
            f"latitude and longitude.")
    return grouped


def build_references(nav: Any, strips: dict[str, tuple[int, int]]
                     ) -> tuple[dict[str, Georeference], dict[str, Any]]:
    """Turn whatever the caller passed into one Georeference per strip.

    `strips` maps a strip name to its (width, height). Returns the references
    and a description of where they came from, for the provenance block. A
    strip the navigation does not mention simply gets no reference, and its
    tiles carry nulls; that is a partial survey, not an error.
    """
    if nav is None:
        return {}, {"source": None, "mode": "none",
                    "note": "No navigation supplied. Positions are relative survey pixels."}

    if isinstance(nav, (str, Path)):
        nav = {"mode": "control_points", "path": str(nav)}

    if not isinstance(nav, dict):
        raise NavigationError(
            "nav must be None, a path to a control-point CSV, or a dict")

    references: dict[str, Georeference] = {}

    # A bare {"strip": {"top_left": ...}} is accepted as corners, so the common
    # case does not need a mode field.
    mode = nav.get("mode")
    if mode is None:
        mode = "control_points" if "path" in nav else "corners"

    if mode == "control_points":
        path = nav.get("path") or nav.get("csv")
        if not path:
            raise NavigationError("control-point navigation needs a 'path'")
        grouped = load_control_points(Path(path))
        for strip in strips:
            points = grouped.get(strip) or grouped.get("")
            if not points:
                continue
            references[strip] = Georeference.from_control_points(strip, points)
        source = {"source": str(Path(path).name), "mode": "control_points"}

    elif mode == "corners":
        table = nav.get("strips", {k: v for k, v in nav.items() if k != "mode"})
        for strip, (width, height) in strips.items():
            corners = table.get(strip)
            if corners is None and len(table) == 1 and len(strips) == 1:
                # One strip, one corner set, no name match. Obvious intent.
                corners = next(iter(table.values()))
            if corners is None:
                continue
            references[strip] = Georeference.from_corners(strip, corners, width, height)
        source = {"source": "four-corner coordinates supplied by the caller",
                  "mode": "corners"}
    else:
        raise NavigationError(f"unknown navigation mode {mode!r}")

    if not references:
        raise NavigationError(
            "navigation was supplied but matched none of the strips "
            f"({', '.join(sorted(strips)) or 'none'}). Check the strip names.")

    source["strips_located"] = sorted(references)
    source["strips_unlocated"] = sorted(set(strips) - set(references))
    source["references"] = [ref.describe() for ref in references.values()]
    source["across_track_resolved"] = all(
        ref.detail.get("across_track_resolved", True) for ref in references.values())
    source["assumptions"] = (
        "Locally flat seabed and locally linear degrees over the extent of one "
        "strip. Not valid across the antimeridian or over a pole.")
    return references, source


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Used for reporting, never for merging."""
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def references_from_manifest(rows: list[dict[str, Any]]
                             ) -> tuple[dict[str, Georeference], dict[str, Any]]:
    """Recover a per-strip transform from a manifest's located tile centres.

    Module 2 is given a tile set and a manifest, not the original navigation
    file, so it has to reconstruct the mapping to place a detection that sits
    somewhere inside a tile rather than at its centre.

    Each located tile contributes one control point: its centre pixel and the
    latitude and longitude recorded for it. The same fitter used for a raw
    navigation file then runs over those points, and reports its residual. For
    a manifest written by affine or along-track navigation the refit is exact.
    For four-corner navigation it is a first-order approximation of a bilinear
    surface, and `max_residual_degrees` is how far off it is, in degrees, at
    the worst tile. That number is in the export rather than in a comment,
    because an approximation nobody can measure is indistinguishable from an
    error.

    A strip with fewer than two located tiles cannot be fitted at all. Its
    detections inherit the position of the tile they were found in, which is a
    real recorded fix rather than an extrapolation, and the provenance says so.
    """
    points: dict[str, list[tuple[float, float, float, float]]] = {}
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None or lat == "" or lon == "":
            continue
        strip = str(row.get("strip") or "")
        cx = row.get("center_x")
        cy = row.get("center_y")
        if cx is None or cy is None:
            # An older or hand-edited manifest without the centre columns.
            # Reconstruct it from the offset and the tile's own size.
            cx = float(row["x"]) + float(row.get("tile_width") or 0) / 2.0
            cy = float(row["y"]) + float(row.get("tile_height") or 0) / 2.0
        points.setdefault(strip, []).append((float(cx), float(cy), float(lat), float(lon)))

    references: dict[str, Georeference] = {}
    inherited: list[str] = []
    for strip, fixes in points.items():
        try:
            references[strip] = Georeference.from_control_points(strip, fixes)
        except NavigationError:
            inherited.append(strip)

    if not points:
        return {}, {"source": None, "mode": "none",
                    "note": "The manifest records no latitude or longitude. "
                            "Positions are relative survey pixels."}

    described = {
        "source": "refitted from the manifest's located tile centres",
        "mode": "manifest_refit",
        "strips_located": sorted(references),
        "strips_inheriting_tile_position": sorted(inherited),
        "references": [ref.describe() for ref in references.values()],
        "across_track_resolved": all(
            ref.detail.get("across_track_resolved", True) for ref in references.values()),
        "assumptions": (
            "Locally flat seabed and locally linear degrees over the extent of "
            "one strip. Not valid across the antimeridian or over a pole."),
    }
    return references, described
