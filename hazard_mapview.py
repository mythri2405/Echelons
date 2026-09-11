"""export.json into a standalone map.html.

The file this writes has no dependencies once it exists. No server, no tile
provider, no network, no sibling files. The sonar imagery is embedded in it as
a data URI and the Leaflet and Folium assets come from the CDN links Folium
emits, with the survey itself readable even if those fail. Copy map.html onto a
USB stick, open it on a machine that has never seen this project, and it works.

TWO COORDINATE MODES, AND THEY LOOK DIFFERENT ON PURPOSE

A survey with no navigation is drawn on Leaflet's CRS.Simple, which is a plain
pixel plane, with the sonar strip itself as the base layer. There is no world
map underneath because there is no world position to put it at. The header says
"Relative Survey Coordinates (px)" and every coordinate on the map is written
as a pixel offset. Nothing is formatted as a latitude.

That is not a degraded mode. For relative survey data it is the correct map:
the contacts are drawn on the acoustic image they were found in, at the pixels
they were found at, which is more useful to a survey team than the same dots
floating over a road atlas would be. It also means the map needs nothing from
the internet, so it cannot fail on a conference floor.

A georeferenced survey is drawn on real coordinates instead, with the strip
placed at its geographic footprint and an optional street basemap under it. The
basemap is the only thing here that needs a network, it is off by default, and
the survey renders completely without it.

MULTIPLE STRIPS IN RELATIVE MODE
Two strips are two coordinate frames. To show them together they are laid out
side by side with a gutter, and the map says in writing that the separation is
a display convenience with no geographic meaning. Within each strip every
position is exact.

THE STRIP IMAGE IS STITCHED FROM THE TILES
Not read from the original survey file, which may be long gone by the time
anyone looks at the map. Tiles are pasted back at their manifest offsets, so
the base layer shows exactly what the detector was shown -- including the gaps
where MIN_CONTENT dropped a blank tile, which is information rather than a
defect.
"""

from __future__ import annotations

import abc
import base64
import io
import json
import logging
from pathlib import Path
from typing import Any, Iterable

import hazard_assets
import hazard_config as cfg
import hazard_theme as theme
from hazard_geo import Georeference, references_from_manifest

log = logging.getLogger("deepecho.hazard")

# Below this the transform is treated as axis-aligned and the sonar image can
# be placed as a north-up rectangle. Above it the strip is rotated relative to
# north, a rectangle would be a lie, and the imagery is left out with the
# reason written on the map.
ROTATION_TOLERANCE = 0.05


class MapError(RuntimeError):
    """The map could not be built from what it was given."""


# --- frames ----------------------------------------------------------------


class Frame(abc.ABC):
    """Survey coordinates to map coordinates, for one of the two modes.

    Abstract on purpose rather than by convention: every drawing routine below
    goes through `point` and `rect` and neither mode may quietly inherit a
    half-implementation. Both subclasses must answer both questions.
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode

    @abc.abstractmethod
    def point(self, strip: str, gx: float, gy: float,
              lat: float | None, lon: float | None) -> list[float] | None:
        """Where a single position lands on the map, or None if it cannot."""

    @abc.abstractmethod
    def rect(self, strip: str, x0: float, y0: float, x1: float, y1: float
             ) -> list[list[float]] | None:
        """The map bounds of a pixel rectangle, or None if it cannot be placed."""


class PixelFrame(Frame):
    """CRS.Simple. Leaflet's y grows upward and a sonar image's grows down, so
    every y is negated. x is shifted per strip by the side-by-side layout."""

    def __init__(self, offsets: dict[str, float]) -> None:
        super().__init__("pixel")
        self.offsets = offsets

    def point(self, strip, gx, gy, lat=None, lon=None):
        return [-float(gy), float(gx) + self.offsets.get(strip, 0.0)]

    def rect(self, strip, x0, y0, x1, y1):
        shift = self.offsets.get(strip, 0.0)
        return [[-float(y1), float(x0) + shift], [-float(y0), float(x1) + shift]]


class GeoFrame(Frame):
    """Real coordinates. Rectangles are located through the strip's own
    transform rather than assumed, so a rotated survey stays correct."""

    def __init__(self, references: dict[str, Georeference]) -> None:
        super().__init__("geo")
        self.references = references

    def point(self, strip, gx, gy, lat=None, lon=None):
        if lat is not None and lon is not None:
            return [float(lat), float(lon)]
        reference = self.references.get(strip)
        if reference is None:
            return None
        located = reference.locate(float(gx), float(gy))
        return None if located[0] is None else [located[0], located[1]]

    def rect(self, strip, x0, y0, x1, y1):
        reference = self.references.get(strip)
        if reference is None:
            return None
        corners = [reference.locate(x, y) for x, y in
                   ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        if any(c[0] is None for c in corners):
            return None
        lats = [c[0] for c in corners]
        lons = [c[1] for c in corners]
        return [[min(lats), min(lons)], [max(lats), max(lons)]]


# --- imagery ---------------------------------------------------------------


def _stitch_strip(tiles_dir: Path, rows: list[dict[str, Any]]) -> tuple[str, int, int] | None:
    """A data URI preview of one strip, rebuilt from its tiles.

    Returns (data_uri, original_width, original_height). The preview is
    downscaled for file size; the returned dimensions are the strip's real ones,
    because that is what the overlay is positioned with.
    """
    from PIL import Image

    placed = [r for r in rows if (tiles_dir / str(r["tile"])).is_file()]
    if not placed:
        return None

    width = int(max(int(r["x"]) + int(r.get("tile_width") or cfg.TILE) for r in placed))
    height = int(max(int(r["y"]) + int(r.get("tile_height") or cfg.TILE) for r in placed))
    width = int(placed[0].get("width") or width)
    height = int(placed[0].get("height") or height)

    # Mid-grey rather than black for the gaps: a dropped low-content tile
    # should read as "not examined", not as "examined and found empty".
    canvas = Image.new("L", (width, height), color=44)
    for row in placed:
        with Image.open(tiles_dir / str(row["tile"])) as tile:
            canvas.paste(tile.convert("L"), (int(row["x"]), int(row["y"])))

    preview = canvas
    longest = max(width, height)
    if longest > theme.PREVIEW_MAX_EDGE:
        scale = theme.PREVIEW_MAX_EDGE / longest
        preview = canvas.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                                Image.LANCZOS)

    buffer = io.BytesIO()
    preview.convert("L").save(buffer, "JPEG", quality=theme.PREVIEW_JPEG_QUALITY)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", width, height


def _axis_aligned(reference: Georeference) -> tuple[bool, bool]:
    """(can be drawn as a north-up rectangle, image rows run north to south)."""
    if reference.mode == "along_track":
        return False, True
    if reference.mode == "corners":
        return True, True
    lat_px, lat_py, _ = reference.detail["lat_coefficients"]
    lon_px, lon_py, _ = reference.detail["lon_coefficients"]
    lat_rotation = abs(lat_px) / (abs(lat_py) or 1e-12)
    lon_rotation = abs(lon_py) / (abs(lon_px) or 1e-12)
    aligned = lat_rotation < ROTATION_TOLERANCE and lon_rotation < ROTATION_TOLERANCE
    # lat falling as the row index rises means row 0 is the northern edge.
    return aligned, lat_py < 0


# --- popups ----------------------------------------------------------------


def _row(label: str, value: Any) -> str:
    return (f"<tr><th>{label}</th><td>{value}</td></tr>")


def _detection_popup(detection: dict[str, Any], frame: Frame) -> str:
    provenance = detection["provenance"]
    style = theme.tier_style(detection["severity_tier"])

    rows = [
        _row("Class", f"<b>{detection['object_class']}</b>"),
        _row("Confidence", f"{detection['confidence']:.2f}"),
        _row("Severity", f"{detection['severity']:.4f} "
                         f"<span class='de-sub'>= {detection['class_weight']} weight "
                         f"&times; {detection['confidence']:.2f} confidence</span>"),
        _row("Tier", f"<span class='de-chip' style='background:{style['surface']};"
                     f"border-color:{style['border']};color:{style['text']}'>"
                     f"{style['label']}</span>"),
        _row("Survey position", f"x {detection['global_x']:.1f}, y {detection['global_y']:.1f} px"),
    ]
    # A geographic position is shown only when one genuinely exists. In a
    # relative survey this row is absent rather than blank, so there is nothing
    # on screen that could be mistaken for a fix.
    if detection.get("latitude") is not None and detection.get("longitude") is not None:
        rows.append(_row("Latitude", f"{detection['latitude']:.6f}"))
        rows.append(_row("Longitude", f"{detection['longitude']:.6f}"))

    rows.append(_row("Source tile", f"<span class='de-mono'>"
                                    f"{provenance['representative_tile']}</span>"))
    merged = provenance["merged_count"]
    rows.append(_row("Views merged", f"{merged}" if merged == 1 else
                     f"{merged} <span class='de-sub'>across "
                     f"{len(provenance['source_tiles'])} tile(s)</span>"))
    rows.append(_row("Action", detection["recommended_action"]))

    return (f"<div class='de-popup'><div class='de-popup-head' "
            f"style='border-left-color:{style['marker']}'>"
            f"<span class='de-mono'>{detection['id']}</span></div>"
            f"<table>{''.join(rows)}</table></div>")


def _hotspot_popup(hotspot: dict[str, Any], frame: Frame) -> str:
    style = theme.tier_style(hotspot["severity_tier"])
    centroid = hotspot["centroid"]

    rows = [
        _row("Priority", f"<b>Rank {hotspot['priority_rank']}</b>"),
        _row("Dominant hazard", f"<b>{hotspot['dominant_class']}</b>"),
        _row("Detections", hotspot["detection_count"]),
        _row("Total severity", f"{hotspot['total_severity']:.4f} "
                               f"<span class='de-sub'>summed over the cell, "
                               f"can exceed 1</span>"),
        _row("Worst single", f"{hotspot['max_severity']:.4f} "
                             f"<span class='de-sub'>0 to 1, sets the tier</span>"),
        _row(theme.TEXT["risk_label"],
             f"{hotspot['risk_score']:.4f} "
             f"<span class='de-sub'>index, not a percentage</span>"),
        _row("Tier", f"<span class='de-chip' style='background:{style['surface']};"
                     f"border-color:{style['border']};color:{style['text']}'>"
                     f"{style['label']}</span>"),
        _row("Centroid", f"x {centroid['global_x']:.1f}, y {centroid['global_y']:.1f} px"),
    ]
    if centroid.get("latitude") is not None:
        rows.append(_row("Latitude", f"{centroid['latitude']:.6f}"))
        rows.append(_row("Longitude", f"{centroid['longitude']:.6f}"))
    rows.append(_row("Action", f"<b>{hotspot['recommended_action']}</b>"))

    return (f"<div class='de-popup'><div class='de-popup-head' "
            f"style='border-left-color:{style['marker']}'>"
            f"<b>{hotspot['hotspot_id']}</b></div>"
            f"<table>{''.join(rows)}</table>"
            f"<p class='de-why'>{hotspot['rationale']}</p></div>")


# --- dashboard chrome ------------------------------------------------------

_CSS = """
html, body { margin: 0; padding: 0; height: 100%; background: ${background}; }
body { font-family: ${sans}; color: ${text}; }

/* Folium sizes its map div inline. The dashboard occupies the top and left
   edges, so the map is repositioned to the space that is left. */
.folium-map {
  position: fixed !important;
  top: var(--de-top) !important; left: var(--de-left) !important;
  right: 0 !important; bottom: 0 !important;
  width: auto !important; height: auto !important;
}
:root { --de-top: 56px; --de-left: 330px; }

/* Leaflet paints #ddd behind an empty map, which reads as a broken page. A
   portrait survey strip in a landscape window always leaves margins, so they
   have to look like canvas rather than like failure. */
.leaflet-container { background: ${surround} !important; }

.de-header {
  position: fixed; top: 0; left: 0; right: 0; height: 56px; z-index: 1200;
  display: flex; align-items: center; gap: 16px; padding: 0 18px;
  background: ${navy_deep}; color: ${text_inverse};
  border-bottom: 1px solid ${navy};
}
.de-wordmark { font-size: 17px; font-weight: 600; letter-spacing: 0.02em; }
.de-wordmark span { color: ${teal_tint}; font-weight: 400; }
.de-title {
  font-family: ${mono}; font-size: 12.5px; color: ${navy_tint};
  padding-left: 16px; border-left: 1px solid rgba(255,255,255,0.22);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.de-header-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.de-badge {
  font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 4px 9px; border-radius: 999px; white-space: nowrap;
  border: 1px solid rgba(255,255,255,0.28); color: ${navy_tint};
}
.de-badge-mode { background: ${teal_deep}; border-color: ${teal}; color: #fff; }
.de-badge-ok { background: rgba(255,255,255,0.08); }

/* With the banner up, everything below it moves down by its height. Without
   this the map slid under the banner and lost its top 36 pixels. */
body.de-has-demo { --de-top: 92px; }

.de-demo {
  position: fixed; top: 56px; left: 0; right: 0; z-index: 1200;
  background: ${alert_surface}; border-bottom: 1px solid ${alert_border};
  color: ${alert_text}; padding: 7px 18px; font-size: 12px;
  display: flex; align-items: baseline; gap: 12px;
}
.de-demo b { letter-spacing: 0.08em; font-size: 11.5px; }

.de-panel {
  position: fixed; top: var(--de-top); left: 0; bottom: 0; width: 330px; z-index: 1150;
  background: ${surface}; border-right: 1px solid ${border};
  overflow-y: auto; font-size: 13px;
}
.de-section { padding: 14px 16px; border-bottom: 1px solid ${border}; }
.de-section h2 {
  margin: 0 0 10px; font-size: 11px; letter-spacing: 0.08em;
  text-transform: uppercase; color: ${text_faint}; font-weight: 600;
}

.de-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: ${border}; }
.de-stat { background: ${surface}; padding: 9px 10px; }
.de-stat .v { font-size: 19px; font-weight: 600; font-family: ${mono}; line-height: 1.2; }
.de-stat .k { font-size: 10.5px; color: ${text_muted}; letter-spacing: 0.04em;
              text-transform: uppercase; margin-top: 2px; }
.de-stat.alert .v { color: ${alert_text}; }

.de-note {
  font-size: 11.5px; line-height: 1.5; color: ${text_muted};
  background: ${surface_muted}; border-left: 2px solid ${border_strong};
  padding: 8px 10px; margin: 10px 0 0;
}
.de-note.mode { background: ${teal_tint}; border-left-color: ${teal}; color: ${teal_deep}; }

.de-legend-row { display: flex; align-items: center; gap: 9px; padding: 4px 0; }
.de-dot { width: 12px; height: 12px; border-radius: 50%; flex: none;
          border: 2px solid rgba(0,0,0,0.25); }
.de-legend-row .lbl { font-weight: 500; }
.de-legend-row .rng { margin-left: auto; font-family: ${mono}; font-size: 11px;
                      color: ${text_faint}; }

.de-prio { padding: 0; }
.de-prio-item {
  display: block; width: 100%; text-align: left; border: 0; border-bottom: 1px solid ${border};
  background: ${surface}; padding: 10px 16px; cursor: pointer; font: inherit;
  border-left: 3px solid transparent;
}
.de-prio-item:hover { background: ${surface_muted}; }
.de-prio-item.active { background: ${navy_tint}; border-left-color: ${navy}; }
.de-prio-top { display: flex; align-items: center; gap: 8px; }
.de-rank {
  font-family: ${mono}; font-size: 11px; font-weight: 600; padding: 1px 6px;
  border-radius: 3px; border: 1px solid; flex: none;
}
.de-prio-id { font-family: ${mono}; font-weight: 600; font-size: 12.5px; }
.de-first {
  margin-left: auto; font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
  color: ${teal_deep}; background: ${teal_tint}; border: 1px solid ${teal};
  border-radius: 999px; padding: 1px 7px;
}
.de-prio-class { margin-top: 4px; font-size: 12.5px; }
.de-prio-action { margin-top: 2px; font-size: 12px; color: ${text_muted}; }
.de-bar { height: 4px; background: ${surface_muted}; border-radius: 2px; margin-top: 7px; }
.de-bar i { display: block; height: 100%; border-radius: 2px; }
.de-prio-meta { margin-top: 5px; font-family: ${mono}; font-size: 10.5px; color: ${text_faint}; }

.de-empty { padding: 16px; font-size: 12.5px; color: ${text_muted}; line-height: 1.55; }
.de-disclaimer { font-size: 11px; line-height: 1.5; color: ${text_faint}; }
.de-disclaimer b { color: ${text_muted}; display: block; margin-bottom: 4px;
                   font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase; }

/* Leaflet's own controls, brought into the design system. The layer control
   is rendered expanded, which hides its toggle button and with it the only
   image Leaflet's stylesheet would have asked the network for. */
.leaflet-control-layers-toggle { display: none !important; }
.leaflet-control-layers {
  font-family: ${sans}; font-size: 12.5px; color: ${text};
  border: 1px solid ${border} !important; border-radius: 5px !important;
  box-shadow: 0 1px 2px rgba(21,40,69,0.10) !important; padding: 9px 12px !important;
  background: ${surface} !important;
}
.leaflet-control-layers label { margin: 0; display: block; padding: 2px 0; cursor: pointer; }
.leaflet-control-layers label span { display: inline-flex; align-items: center; gap: 6px; }
.leaflet-control-layers-separator { border-top: 1px solid ${border}; margin: 6px 0; }
.leaflet-bar a, .leaflet-bar a:hover {
  color: ${navy}; border-bottom-color: ${border};
}
.leaflet-control-attribution {
  font-size: 10px; background: rgba(255,255,255,0.82) !important; color: ${text_faint};
}
.leaflet-control-attribution a { color: ${teal_deep}; }

/* Popups */
.de-popup { font-family: ${sans}; font-size: 12.5px; min-width: 250px; }
.de-popup-head {
  border-left: 3px solid ${border_strong}; padding: 1px 0 1px 8px; margin-bottom: 8px;
  font-size: 13px;
}
.de-popup table { border-collapse: collapse; width: 100%; }
.de-popup th {
  text-align: left; font-weight: 500; color: ${text_muted}; padding: 2px 10px 2px 0;
  white-space: nowrap; vertical-align: top; font-size: 11.5px;
}
.de-popup td { padding: 2px 0; vertical-align: top; }
.de-mono { font-family: ${mono}; font-size: 11.5px; }
.de-sub { color: ${text_faint}; font-size: 11px; }
.de-chip { border: 1px solid; border-radius: 3px; padding: 0 6px; font-size: 11px; }
.de-why {
  margin: 9px 0 0; padding-top: 8px; border-top: 1px solid ${border};
  font-size: 11.5px; line-height: 1.5; color: ${text_muted};
}
.leaflet-popup-content { margin: 11px 13px; }

@media (max-width: 880px) {
  :root { --de-left: 0px; }
  .de-panel { top: auto; bottom: 0; width: 100%; height: 42%; border-right: 0;
              border-top: 1px solid ${border}; }
  .folium-map { bottom: 42% !important; }
}
"""


def _css() -> str:
    from string import Template

    tokens = dict(theme.COLOR)
    tokens["sans"] = theme.FONT_SANS
    tokens["mono"] = theme.FONT_MONO
    tokens["surround"] = theme.MAP_SURROUND
    return f"<style>{Template(_CSS).substitute(tokens)}</style>"


def _stat(value: Any, label: str, alert: bool = False) -> str:
    return (f"<div class='de-stat{' alert' if alert else ''}'>"
            f"<div class='v'>{value}</div><div class='k'>{label}</div></div>")


def _dashboard(export: dict[str, Any], title: str, demo: bool,
               multi_strip: bool) -> str:
    summary = export["survey_summary"]
    hotspots = export["hotspots"]
    georeferenced = summary["georeferenced"]
    tiers = summary["detections_by_tier"]
    critical = tiers.get("critical", 0)

    mode_label = theme.TEXT["geo_mode"] if georeferenced else theme.TEXT["relative_mode"]
    mode_note = theme.TEXT["geo_note"] if georeferenced else theme.TEXT["relative_note"]

    header = (
        f"<div class='de-header'>"
        f"<div class='de-wordmark'>{theme.TEXT['app']}"
        f"<span> {theme.TEXT['subtitle']}</span></div>"
        f"<div class='de-title'>{title}</div>"
        f"<div class='de-header-right'>"
        f"<span class='de-badge de-badge-mode'>{mode_label}</span>"
        f"<span class='de-badge de-badge-ok'>Processed "
        f"{summary['tiles_processed']} tiles</span>"
        f"</div></div>")

    banner = ""
    if demo:
        banner = (f"<div class='de-demo'><b>{theme.TEXT['demo_banner']}</b>"
                  f"<span>{theme.TEXT['demo_note']}</span></div>")

    stats = (
        "<div class='de-section'><h2>Survey</h2><div class='de-stats'>"
        + _stat(summary["total_deduplicated_detections"], "Detections")
        + _stat(summary["total_hotspots"], "Hotspots")
        + _stat(critical, "Critical", alert=critical > 0)
        + _stat(f"{summary['total_severity']:.2f}", "Total severity")
        + "</div>"
        + (f"<p class='de-note'>{summary['duplicates_removed']} duplicate view(s) "
           f"merged from {summary['total_raw_detections']} raw boxes.</p>"
           if summary["duplicates_removed"] else "")
        + f"<p class='de-note mode'>{mode_note}</p>"
        + (f"<p class='de-note'>{theme.TEXT['multi_strip_note']}</p>"
           if multi_strip and not georeferenced else "")
        + "</div>")

    legend_rows = []
    for tier, floor in cfg.SEVERITY_TIERS:
        style = theme.tier_style(tier)
        # The NEAREST boundary above this tier, not the first one listed.
        # SEVERITY_TIERS is ordered high to low, so next() returned critical's
        # 0.75 for every tier and the legend read "low: below 0.75".
        above = [f for _t, f in cfg.SEVERITY_TIERS if f > floor]
        upper = min(above) if above else None
        span = f"{floor:.2f} and up" if upper is None else f"{floor:.2f} to {upper:.2f}"
        span = f"below {upper:.2f}" if floor == 0.0 and upper else span
        legend_rows.append(
            f"<div class='de-legend-row'>"
            f"<span class='de-dot' style='background:{style['fill']};"
            f"border-color:{style['marker']}'></span>"
            f"<span class='lbl'>{style['label']}</span>"
            f"<span class='rng'>{span}</span></div>")

    legend = ("<div class='de-section'><h2>" + theme.TEXT["legend_heading"] + "</h2>"
              + "".join(legend_rows)
              + f"<p class='de-note'>{theme.TEXT['heat_note']}</p></div>")

    if hotspots:
        items = []
        worst = max(h["total_severity"] for h in hotspots) or 1.0
        for hotspot in hotspots:
            style = theme.tier_style(hotspot["severity_tier"])
            first = (f"<span class='de-first'>{theme.TEXT['start_here']}</span>"
                     if hotspot["priority_rank"] == 1 else "")
            items.append(
                f"<button class='de-prio-item' data-hotspot='{hotspot['hotspot_id']}'>"
                f"<div class='de-prio-top'>"
                f"<span class='de-rank' style='background:{style['surface']};"
                f"border-color:{style['border']};color:{style['text']}'>"
                f"{hotspot['priority_rank']}</span>"
                f"<span class='de-prio-id'>{hotspot['hotspot_id']}</span>{first}</div>"
                f"<div class='de-prio-class'><b>{hotspot['dominant_class']}</b>"
                f" &middot; {hotspot['detection_count']} detection"
                f"{'s' if hotspot['detection_count'] != 1 else ''}</div>"
                f"<div class='de-prio-action'>{hotspot['recommended_action']}</div>"
                f"<div class='de-bar'><i style='width:"
                f"{max(3, round(100 * hotspot['total_severity'] / worst))}%;"
                f"background:{style['fill']}'></i></div>"
                f"<div class='de-prio-meta'>"
                f"{theme.TEXT['total_severity_label']} {hotspot['total_severity']:.3f}"
                f" &middot; {theme.TEXT['max_severity_label']} "
                f"{hotspot['max_severity']:.3f}"
                f" &middot; {theme.TEXT['risk_label'].lower()} "
                f"{hotspot['risk_score']:.3f}</div>"
                f"</button>")
        priority = ("<div class='de-section' style='padding-bottom:0'><h2>"
                    + theme.TEXT["priority_heading"] + "</h2></div>"
                    + "<div class='de-prio'>" + "".join(items) + "</div>")
    else:
        priority = f"<div class='de-empty'>{theme.TEXT['no_detections']}</div>"

    disclaimer = (f"<div class='de-section'><p class='de-disclaimer'>"
                  f"<b>{theme.TEXT['disclaimer_heading']}</b>{cfg.DISCLAIMER}</p></div>")

    return (header + banner
            + "<div class='de-panel'>"
            + stats + legend + priority + disclaimer + "</div>"
            # One class, read by the stylesheet, moves the map and the panel
            # down together when the banner is present.
            + ("<script>document.body.classList.add('de-has-demo');</script>"
               if demo else ""))


# --- the map ---------------------------------------------------------------

_JS = """
(function () {
  var map = ${map};
  var targets = ${targets};

  function focus(id, button) {
    var target = targets[id];
    if (!target) { return; }
    document.querySelectorAll('.de-prio-item.active')
      .forEach(function (el) { el.classList.remove('active'); });
    if (button) { button.classList.add('active'); }
    map.setView(target.center, target.zoom, { animate: true });
    var marker = window[target.marker];
    if (marker && marker.openPopup) {
      window.setTimeout(function () { marker.openPopup(); }, 260);
    }
  }

  document.querySelectorAll('.de-prio-item').forEach(function (button) {
    button.addEventListener('click', function () {
      focus(button.getAttribute('data-hotspot'), button);
    });
  });

  // Leaflet measures the container once, on creation. The dashboard resizes it
  // afterwards, so without this the map renders into the old rectangle and the
  // tiles sit offset until the first manual pan.
  window.setTimeout(function () { map.invalidateSize(); }, 60);
  window.addEventListener('resize', function () { map.invalidateSize(); });

  // The page is also embedded in the DeepEcho dashboard, in a frame served
  // from a different origin. These two are the whole interface it offers, and
  // both are read-only: the host can ask the map to look at a hotspot, and the
  // map says which one it is showing. Nothing here accepts code, a URL, or
  // anything that is not one of this survey's own hotspot identifiers, and an
  // id that is not in `targets` is ignored rather than acted on.
  window.addEventListener('message', function (event) {
    var data = event && event.data;
    if (!data || data.type !== 'deepecho:focus') { return; }
    var id = String(data.hotspot_id || '');
    if (!Object.prototype.hasOwnProperty.call(targets, id)) { return; }
    focus(id, document.querySelector('.de-prio-item[data-hotspot="' + id + '"]'));
  });

  // A hotspot named in the URL fragment is opened on load, so a link can point
  // at one without the host having to send a message at all.
  var fragment = (window.location.hash || '').replace(/^#/, '');
  if (Object.prototype.hasOwnProperty.call(targets, fragment)) {
    window.setTimeout(function () { focus(fragment, null); }, 120);
  }
})();
"""


def _detection_marker(detection: dict[str, Any], position: list[float]):
    import folium

    style = theme.tier_style(detection["severity_tier"])
    merged = int(detection["provenance"]["merged_count"])
    radius = min(theme.MERGED_RADIUS_CAP_PX,
                 theme.DETECTION_RADIUS_PX + (merged - 1) * theme.MERGED_RADIUS_BONUS_PX)
    return folium.CircleMarker(
        location=position,
        radius=radius,
        color=style["marker"],
        weight=theme.DETECTION_WEIGHT,
        fill=True,
        fill_color=style["fill"],
        fill_opacity=theme.DETECTION_FILL_OPACITY,
        popup=folium.Popup(_detection_popup(detection, None), max_width=340),
        tooltip=(f"{detection['object_class']} &middot; severity "
                 f"{detection['severity']:.3f}"),
    )


def render_map(export: dict[str, Any], out_dir: Any, tiles_dir: Any = None,
               manifest: Any = None, *, title: str | None = None,
               demo: bool = False, basemap: bool = False, offline: bool = True,
               filename: str = "map.html") -> Path:
    """Write a standalone map.html for one survey.

    export      the dictionary build_hazard_map returned, or a loaded export.json
    out_dir     where map.html goes
    tiles_dir   the tiles, used to rebuild the sonar base layer
    manifest    the manifest; found beside the tiles if omitted
    title       the survey name shown in the header
    demo        stamps the map as synthetic. See demo_survey.py.
    basemap     in a georeferenced survey, include an OpenStreetMap layer.
                Off by default and off at open even when on, because it is the
                only thing on the map that needs a network.
    offline     inline Leaflet into the page and strip the libraries folium
                links but this map never uses. On by default. See
                hazard_assets for what is kept and what is dropped.
    """
    try:
        import folium
        from folium.plugins import HeatMap
    except ImportError as exc:
        raise MapError(
            "folium is not installed, so map.html cannot be built. Run "
            "`pip install folium`, or pass --no-map to run_survey.py if you only "
            "need export.json and actions.csv. The engine itself does not need it."
        ) from exc

    from survey_preparation import load_manifest

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    if manifest is not None:
        rows, _ = load_manifest(manifest)
    elif tiles_dir is not None:
        for candidate in (Path(tiles_dir).parent / cfg.MANIFEST_JSON,
                          Path(tiles_dir).parent / cfg.MANIFEST_CSV):
            if candidate.is_file():
                rows, _ = load_manifest(candidate)
                break

    detections = export["detections"]
    hotspots = export["hotspots"]
    georeferenced = bool(export["survey_summary"]["georeferenced"])
    grid = int(export["configuration"]["hotspots"]["GRID"])

    by_strip: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_strip.setdefault(str(row["strip"]), []).append(row)
    # A survey run without a manifest still maps: the detections name their own
    # strip, there is simply no imagery to draw under them.
    for detection in detections:
        by_strip.setdefault(str(detection["provenance"]["strip"] or ""), [])
    strips = sorted(by_strip)

    # --- frame and base map ------------------------------------------------
    if georeferenced:
        references, _ = references_from_manifest(rows)
        frame: Frame = GeoFrame(references)
        located = [d for d in detections if d.get("latitude") is not None]
        centre = ([sum(d["latitude"] for d in located) / len(located),
                   sum(d["longitude"] for d in located) / len(located)]
                  if located else [0.0, 0.0])
        fmap = folium.Map(location=centre, zoom_start=15, tiles=None,
                          control_scale=True, prefer_canvas=True)
        if basemap:
            folium.TileLayer("OpenStreetMap", name="Street basemap", show=False,
                             control=True).add_to(fmap)
    else:
        offsets: dict[str, float] = {}
        cursor = 0.0
        for strip in strips:
            offsets[strip] = cursor
            widths = [int(r.get("width") or 0) for r in by_strip[strip]]
            local = [d["global_x"] for d in detections
                     if str(d["provenance"]["strip"] or "") == strip]
            cursor += (max(widths) if widths else (max(local) if local else cfg.TILE)) \
                + theme.STRIP_GUTTER_PX
        frame = PixelFrame(offsets)
        # min_zoom below 0 so a strip taller than the window can be zoomed out
        # to fit. CRS.Simple has no natural zoom floor.
        # zoomSnap=0 is the whole fix for "the map opens mostly empty".
        #
        # Leaflet snaps a fitBounds zoom down to a whole integer by default.
        # On CRS.Simple a whole zoom step is a factor of two, so a survey that
        # ideally fits at zoom -1.79 is rendered at -2, at 0.25 scale instead
        # of 0.29, and the wasted linear scale squares into wasted area. On a
        # 1600x2048 survey in a typical window that is the difference between
        # filling 14% of the viewport and filling 40% of it. There are no
        # raster tiles here to misalign, so nothing is paid for it.
        fmap = folium.Map(location=[0, 0], zoom_start=0, min_zoom=-6, max_zoom=6,
                          crs="Simple", tiles=None, prefer_canvas=True,
                          zoomSnap=0, zoomDelta=0.5)

    # --- sonar imagery -----------------------------------------------------
    imagery = folium.FeatureGroup(name=theme.LAYERS["strip"],
                                  show="strip" in theme.LAYERS_ON_BY_DEFAULT)
    drawn_bounds: list[list[float]] = []
    skipped_imagery: list[str] = []
    extents: dict[str, tuple[int, int]] = {}

    for strip in strips:
        strip_rows = by_strip[strip]
        stitched = (_stitch_strip(Path(tiles_dir), strip_rows)
                    if tiles_dir and strip_rows else None)
        if stitched is None:
            continue
        data_uri, width, height = stitched

        if georeferenced:
            reference = getattr(frame, "references", {}).get(strip)
            if reference is None:
                continue
            aligned, north_up = _axis_aligned(reference)
            if not aligned:
                skipped_imagery.append(strip)
                continue
            bounds = frame.rect(strip, 0, 0, width, height)
            origin = "upper" if north_up else "lower"
        else:
            bounds = frame.rect(strip, 0, 0, width, height)
            origin = "upper"

        if bounds is None:
            continue
        folium.raster_layers.ImageOverlay(
            image=data_uri, bounds=bounds, origin=origin, opacity=1.0,
            zindex=1, pixelated=False).add_to(imagery)
        # A tall strip in a wide window leaves margins however well it is
        # fitted. The outline makes the survey's extent legible against them
        # rather than letting the image dissolve into the background.
        folium.Rectangle(bounds=bounds, color=theme.STRIP_OUTLINE,
                         weight=theme.STRIP_OUTLINE_WEIGHT, fill=False,
                         tooltip=f"{strip} &middot; {width} x {height} px"
                         ).add_to(imagery)
        extents[strip] = (width, height)
        drawn_bounds.extend(bounds)

    imagery.add_to(fmap)

    # --- tile footprints ---------------------------------------------------
    tile_layer = folium.FeatureGroup(name=theme.LAYERS["tiles"],
                                     show="tiles" in theme.LAYERS_ON_BY_DEFAULT)
    for strip in strips:
        for row in by_strip[strip]:
            bounds = frame.rect(strip, int(row["x"]), int(row["y"]),
                                int(row["x"]) + int(row.get("tile_width") or cfg.TILE),
                                int(row["y"]) + int(row.get("tile_height") or cfg.TILE))
            if bounds is None:
                continue
            folium.Rectangle(
                bounds=bounds, color=theme.COLOR["teal"],
                weight=theme.TILE_OUTLINE_WEIGHT, opacity=theme.TILE_OUTLINE_OPACITY,
                fill=False,
                tooltip=(f"{row['tile']} &middot; content "
                         f"{float(row.get('content_score') or 0):.3f}")).add_to(tile_layer)
            drawn_bounds.extend(bounds)
    tile_layer.add_to(fmap)

    # --- severity heat -----------------------------------------------------
    # Weighted by severity, never by count. A hundred tyres must not glow
    # hotter than one mine, and a count-weighted heatmap does exactly that.
    heat_points = []
    for detection in detections:
        position = frame.point(strip=str(detection["provenance"]["strip"] or ""),
                               gx=detection["global_x"], gy=detection["global_y"],
                               lat=detection.get("latitude"), lon=detection.get("longitude"))
        if position is None:
            continue
        heat_points.append([position[0], position[1], float(detection["severity"])])

    if heat_points:
        heat_group = folium.FeatureGroup(name=theme.LAYERS["heat"],
                                         show="heat" in theme.LAYERS_ON_BY_DEFAULT)
        HeatMap(
            heat_points,
            # Normalised against the strongest severity present, so the scale is
            # the survey's own. max_zoom keeps leaflet.heat from renormalising
            # as the operator zooms, which would make heat mean different things
            # at different zooms.
            max_zoom=6,
            radius=max(8, round(grid * theme.HEAT_RADIUS_FRACTION)),
            blur=max(6, round(grid * theme.HEAT_BLUR_FRACTION)),
            min_opacity=theme.HEAT_MIN_OPACITY,
            gradient=theme.HEAT_GRADIENT,
        ).add_to(heat_group)
        heat_group.add_to(fmap)

    # --- detections --------------------------------------------------------
    all_layer = folium.FeatureGroup(name=theme.LAYERS["detections"],
                                    show="detections" in theme.LAYERS_ON_BY_DEFAULT)
    tier_layers = {}
    for tier, _floor in cfg.SEVERITY_TIERS:
        tier_layers[tier] = folium.FeatureGroup(
            name=theme.LAYERS.get(tier, theme.tier_style(tier)["label"]),
            show=tier in theme.LAYERS_ON_BY_DEFAULT)

    unplaced = 0
    for detection in detections:
        position = frame.point(strip=str(detection["provenance"]["strip"] or ""),
                               gx=detection["global_x"], gy=detection["global_y"],
                               lat=detection.get("latitude"), lon=detection.get("longitude"))
        if position is None:
            unplaced += 1
            continue
        _detection_marker(detection, position).add_to(all_layer)
        layer = tier_layers.get(detection["severity_tier"])
        if layer is not None:
            _detection_marker(detection, position).add_to(layer)
        drawn_bounds.append(position)

    all_layer.add_to(fmap)
    for layer in tier_layers.values():
        layer.add_to(fmap)

    # --- hotspots ----------------------------------------------------------
    # A hotspot is a grid cell, so it is drawn as that cell rather than as a
    # circle, and a numbered badge sits at the centroid. Drawing a radius the
    # aggregation never used would imply a precision it does not have.
    hotspot_layer = folium.FeatureGroup(name=theme.LAYERS["hotspots"],
                                        show="hotspots" in theme.LAYERS_ON_BY_DEFAULT)
    targets: dict[str, dict[str, Any]] = {}

    for hotspot in hotspots:
        strip = str(hotspot["strip"] or "")
        cell_x, cell_y = hotspot["cell"]
        size = int(hotspot["cell_size_px"])
        style = theme.tier_style(hotspot["severity_tier"])

        # A cell on the edge of a survey runs past the end of the strip. The
        # part beyond the imagery contains nothing and cannot, so it is clipped:
        # it would otherwise stretch the fitted bounds and pull the whole map
        # further out than the data warrants.
        x0, y0 = cell_x * size, cell_y * size
        x1, y1 = x0 + size, y0 + size
        extent = extents.get(strip)
        if extent:
            x1, y1 = min(x1, extent[0]), min(y1, extent[1])
        bounds = frame.rect(strip, x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None
        centre = frame.point(strip, hotspot["centroid"]["global_x"],
                             hotspot["centroid"]["global_y"],
                             hotspot["centroid"].get("latitude"),
                             hotspot["centroid"].get("longitude"))
        if centre is None:
            continue

        if bounds is not None:
            folium.Rectangle(
                bounds=bounds, color=style["marker"], weight=theme.HOTSPOT_WEIGHT,
                fill=True, fill_color=style["fill"],
                fill_opacity=theme.HOTSPOT_FILL_OPACITY,
                tooltip=f"{hotspot['hotspot_id']} &middot; rank "
                        f"{hotspot['priority_rank']}").add_to(hotspot_layer)
            drawn_bounds.extend(bounds)

        badge = folium.Marker(
            location=centre,
            icon=folium.DivIcon(
                icon_size=(30, 30), icon_anchor=(15, 15),
                html=f"<div style=\"width:26px;height:26px;border-radius:50%;"
                     f"background:{style['marker']};color:#fff;font:600 12px/26px "
                     f"{theme.FONT_MONO};text-align:center;"
                     f"border:2px solid rgba(255,255,255,0.9);"
                     f"box-sizing:content-box\">{hotspot['priority_rank']}</div>"),
            popup=folium.Popup(_hotspot_popup(hotspot, frame), max_width=360),
            tooltip=f"{hotspot['hotspot_id']} &middot; {hotspot['dominant_class']}")
        badge.add_to(hotspot_layer)

        targets[hotspot["hotspot_id"]] = {
            "center": centre,
            "zoom": 1 if frame.mode == "pixel" else 18,
            "marker": badge.get_name(),
        }

    hotspot_layer.add_to(fmap)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    if drawn_bounds:
        lats = [p[0] for p in drawn_bounds]
        lons = [p[1] for p in drawn_bounds]
        fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(24, 24))

    # --- chrome ------------------------------------------------------------
    from string import Template

    title = title or export["metadata"].get("survey_id") or "Survey"
    multi_strip = len(strips) > 1

    root = fmap.get_root()
    root.header.add_child(folium.Element(_css()))
    root.html.add_child(folium.Element(_dashboard(export, title, demo, multi_strip)))
    root.script.add_child(folium.Element(Template(_JS).substitute(
        map=fmap.get_name(), targets=json.dumps(targets))))
    root.title = f"{title} | {theme.TEXT['app']} {theme.TEXT['subtitle']}"

    path = out_dir / filename
    html = root.render()

    if offline:
        try:
            html, assets = hazard_assets.inline(html)
        except hazard_assets.AssetError as exc:
            # Loud, because the failure mode it causes is a blank white page on
            # a machine with no network, and that is discovered on stage.
            log.warning("map.html will load Leaflet from a CDN and will NOT render "
                        "offline: %s", exc)
            assets = {"inlined": [], "dropped": [], "remaining_external": ["CDN fallback"]}
    else:
        assets = {"inlined": [], "dropped": [], "remaining_external": ["CDN by request"]}

    path.write_text(html, encoding="utf-8")

    if unplaced:
        log.warning("%d detection(s) had no position to draw and are not on the map",
                    unplaced)
    if skipped_imagery:
        log.info("sonar imagery omitted for rotated strip(s): %s",
                 ", ".join(skipped_imagery))
    external = [u for u in assets["remaining_external"] if "openstreetmap" not in u.lower()]
    log.info("wrote %s (%.1f KB, %s, %d detections, %d hotspots, %s)",
             path.name, path.stat().st_size / 1024,
             "geo-referenced" if georeferenced else "relative pixels",
             len(detections), len(hotspots),
             "self-contained" if not external else f"{len(external)} external reference(s)")
    return path
