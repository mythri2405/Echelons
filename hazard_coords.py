"""Tile-local boxes to survey-wide positions.

A detector reports a box in the coordinate system of the 640-pixel tile it was
shown. That number is meaningless the moment the tile is closed. This module
converts it once, into the survey frame, and everything after this point works
in survey coordinates only.

    bbox_center_x = (x1 + x2) / 2        within the tile
    bbox_center_y = (y1 + y2) / 2
    global_x      = tile_x + bbox_center_x
    global_y      = tile_y + bbox_center_y

global_x and global_y are the canonical spatial identity of a detection. They
exist for every detection in every survey, georeferenced or not, and they are
never overwritten. A latitude and longitude, when navigation allows one, is
attached BESIDE them and never in place of them.

ONE FRAME PER STRIP
    global_x and global_y are offsets inside their own strip. Two strips are
    two coordinate systems: pixel (400, 900) of strip A and pixel (400, 900) of
    strip B are different places on the seabed, and without navigation there is
    nothing that says how far apart. So everything spatial downstream --
    merging, gridding, hotspots -- is scoped to a single strip. Merging across
    strips on pixel proximity alone would be inventing a relationship between
    two frames that have none.
"""

from __future__ import annotations

import logging
from typing import Any

from hazard_geo import Georeference

log = logging.getLogger("deepecho.hazard")


def to_global(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add survey-frame coordinates to every raw detection, in place."""
    for detection in detections:
        x1, y1, x2, y2 = (float(v) for v in detection["bbox_tile"])
        center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        tile_x, tile_y = float(detection["tile_x"]), float(detection["tile_y"])
        detection.update({
            "bbox_center_x": round(center_x, 2),
            "bbox_center_y": round(center_y, 2),
            "global_x": round(tile_x + center_x, 2),
            "global_y": round(tile_y + center_y, 2),
            # The box itself in survey coordinates, so a viewer can draw it
            # over the strip without going back to the tile.
            "bbox_global": [round(tile_x + x1, 2), round(tile_y + y1, 2),
                            round(tile_x + x2, 2), round(tile_y + y2, 2)],
            "width_px": round(x2 - x1, 2),
            "height_px": round(y2 - y1, 2),
        })
    return detections


def attach_geo(detections: list[dict[str, Any]],
               references: dict[str, Georeference]) -> int:
    """Attach lat/lon where the strip has navigation. Returns how many got one.

    A detection on a strip with no navigation is given an explicit null rather
    than having the keys left out, so a consumer can tell "not located" from
    "field missing" without guessing.
    """
    located = 0
    for detection in detections:
        reference = references.get(detection.get("strip") or "")
        if reference is None:
            detection["latitude"] = None
            detection["longitude"] = None
            continue
        lat, lon = reference.locate(detection["global_x"], detection["global_y"])
        detection["latitude"] = lat
        detection["longitude"] = lon
        located += lat is not None

    if references and located < len(detections):
        log.info("%d of %d detections carry a geographic position; the rest are "
                 "on strips with no navigation", located, len(detections))
    return located
