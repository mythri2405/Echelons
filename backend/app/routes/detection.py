"""Upload a sonar tile, detect what is in it, keep the record.

This route used to store the image and then save a hardcoded test detection.
The storage half was real and is unchanged. The detection half now runs the two
YOLOv8 checkpoints through backend/detect.py, which merges their boxes and
applies the per-class confidence floors before anything is written down.

Persistence is best-effort. Without Supabase credentials the detection still
runs and is returned; it is simply not stored, and the response says so. A
missing database should cost you history, not the ability to look at a tile.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from ... import config, detect
from ..services.detection_service import save_detections
from ..supabase_client import supabase_ready, require_supabase

router = APIRouter()


def _for_storage(record: dict) -> dict:
    """One detection in the shape the detections table expects.

    Two conversions matter. The detector reports [x, y, w, h] and the table
    stores corners, so the box is converted rather than reinterpreted. And
    `anomaly` is true whenever the object is unidentified, which includes a
    class the floors withheld: the contact is real, the name is not.
    """
    x, y, w, h = record.get("bbox", [0, 0, 0, 0])
    label = record.get("object_class") or ""
    withheld = bool(record.get("downgraded_from"))
    unidentified = withheld or label in config.UNKNOWN_LABELS

    from ... import chat

    return {
        "id": str(uuid.uuid4()),
        "class": label,
        "confidence": record.get("confidence"),
        "bbox": [x, y, x + w, y + h],
        "anomaly": unidentified,
        "severity": chat.severity_for({"label": label}, unidentified),
    }


@router.post("/detect")
async def detect_route(
    file: UploadFile = File(...),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
):
    """Run both checkpoints over one tile and record the result.

    Latitude and longitude are whatever the caller supplies and nothing more.
    A tile carries no position of its own, so absent means null in the row, not
    a guess.
    """
    if file.content_type not in config.ACCEPTED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type {file.content_type!r}. "
                   f"Accepted: {', '.join(config.ACCEPTED_UPLOAD_TYPES)}")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(image_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Tile is {len(image_bytes)} bytes; the limit is {config.MAX_UPLOAD_BYTES}.")

    filename = file.filename or "tile"
    records, is_stub, models = detect.run_detector(image_bytes, filename)

    scan_id = str(uuid.uuid4())
    storage_path = f"{scan_id}{os.path.splitext(filename)[1]}"
    persisted = False
    saved = []

    if supabase_ready():
        client = require_supabase()
        client.storage.from_("sonar-images").upload(
            path=storage_path,
            file=image_bytes,
            file_options={"content-type": file.content_type, "upsert": "false"},
        )
        client.table("scans").insert({
            "id": scan_id,
            "image_url": storage_path,
            "latitude": latitude,
            "longitude": longitude,
            "status": "analysed",
        }).execute()
        saved = save_detections(scan_id, [_for_storage(r) for r in records])
        persisted = True

    return {
        "scan_id": scan_id,
        "image_url": storage_path if persisted else None,
        "status": "analysed",
        "stored": persisted,
        "stub": is_stub,
        "models": models or ["stub"],
        "filename": filename,
        "bytes": len(image_bytes),
        # The full records, with provenance and any withheld class, for a client
        # that wants to reason about them. The stored rows are the flattened
        # version above.
        "detections": records,
        "saved": saved,
    }
