"""Sonar tile in, detection records out.

Two YOLOv8 checkpoints are run over the same tile:

    known.pt    yolov8s on SCTD           aircraft, human, ship
    anomaly.pt  yolov8n on sonar_detect   aircraft, fish, other, shipwreck

Both, not one, because they disagree usefully. The anomaly model carries an
explicit `other` class, which is the detector saying it saw something and could
not name it, and that is exactly the signal the unidentified-object path exists
to handle. Where both models find the same contact, the more confident call
leads and the other is kept beside it as a recorded second opinion.

Inference happens in a subprocess. See backend/detector_worker.py for why.

Records that leave here are the shape /chat already accepts. The one addition
is provenance: which model made the call, and what it called the object before
the class map translated it into the corpus's vocabulary.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from . import config
from .schemas import DetectionRecord, DetectResponse

router = APIRouter()

_lock = threading.Lock()
_worker: subprocess.Popen | None = None
_status: dict = {"ready": False, "models": [], "classes": {}}


def _spawn() -> subprocess.Popen | None:
    """Start the worker and read its handshake. None if it cannot run."""
    global _status
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.detector_worker"],
            cwd=str(config.ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except Exception:
        return None

    handshake = process.stdout.readline() if process.stdout else ""
    try:
        _status = json.loads(handshake)
    except json.JSONDecodeError:
        process.kill()
        return None

    if not _status.get("ready"):
        process.kill()
        return None
    return process


def load_models() -> dict:
    """Model name to class list. Empty means the stub is in use.

    Named to match what the rest of the application asks for; the models
    themselves live in the worker and are never imported here.
    """
    global _worker
    with _lock:
        if _worker is None or _worker.poll() is not None:
            _worker = _spawn()
        return dict(_status.get("classes", {})) if _worker else {}


def _ask(image_bytes: bytes) -> list[dict] | None:
    """Raw boxes from the worker, or None if it is unavailable."""
    global _worker
    with _lock:
        if _worker is None or _worker.poll() is not None:
            _worker = _spawn()
        if _worker is None:
            return None

        # The image goes via a file rather than the pipe: a few megabytes of
        # base64 through a line-delimited protocol is a needless copy.
        with tempfile.NamedTemporaryFile(suffix=".img", delete=True) as handle:
            handle.write(image_bytes)
            handle.flush()
            try:
                _worker.stdin.write(json.dumps({"image_path": handle.name}) + "\n")
                _worker.stdin.flush()
                reply = json.loads(_worker.stdout.readline())
            except Exception:
                _worker.kill()
                _worker = None
                return None

    if not reply.get("ok"):
        raise HTTPException(status_code=422,
                            detail=f"The detector could not read that tile: {reply.get('error')}")
    return reply["boxes"]


def _iou(a: list[float], b: list[float]) -> float:
    """Overlap of two [x, y, w, h] boxes."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    iy = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    overlap = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - overlap
    return overlap / union if union > 0 else 0.0


def _merge(boxes: list[dict], filename: str) -> list[dict]:
    """One record per physical contact, with any disagreement kept visible."""
    kept: list[dict] = []
    for box in sorted(boxes, key=lambda b: b["confidence"], reverse=True):
        twin = next((k for k in kept if _iou(k["bbox"], box["bbox"]) >= config.DETECTOR_MERGE_IOU),
                    None)
        if twin is not None:
            # A disagreement between the two models is information an operator
            # should see, not a tie for the software to settle quietly.
            if twin["detector_class"] != box["cls"]:
                twin["second_opinion"] = (
                    f"the {box['model']} model called this same box "
                    f"'{box['cls']}' at {box['confidence']:.2f}")
            continue

        floor = config.CLASS_CONFIDENCE_FLOOR.get(box["cls"], 0.0)
        trusted = box["confidence"] >= floor
        record = {
            "object_class": (config.DETECTOR_CLASS_MAP.get(box["cls"], box["cls"])
                             if trusted else config.DOWNGRADE_LABEL),
            "confidence": box["confidence"],
            "bbox": box["bbox"],
            "detector_model": box["model"],
            "detector_class": box["cls"],
            "sensor": config.DETECTOR_SENSOR,
            "platform": config.DETECTOR_PLATFORM,
            "notes": (f"Detected in {filename} by the {box['model']} model as "
                      f"'{box['cls']}'. The tile carries no position, depth or range scale."),
        }
        if not trusted:
            record["downgraded_from"] = config.DOWNGRADE_NOTE.format(
                model=box["model"], cls=box["cls"],
                confidence=box["confidence"], floor=floor)
        kept.append(record)
    return kept


def run_detector(image_bytes: bytes, filename: str) -> tuple[list[dict], bool, list[str]]:
    """(detection records, is_stub, models used)."""
    boxes = _ask(image_bytes)
    if boxes is None:
        return [dict(record) for record in config.STUB_DETECTIONS], True, []
    return _merge(boxes, filename), False, sorted(_status.get("models", []))


@router.post("/detect", response_model=DetectResponse)
async def post_detect(tile: UploadFile = File(...)) -> DetectResponse:
    """Accept one sonar tile and return every contact in it.

    A list, because one tile holds several contacts. The client picks one and
    attaches it to a conversation.
    """
    if tile.content_type not in config.ACCEPTED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type {tile.content_type!r}. "
                   f"Accepted: {', '.join(config.ACCEPTED_UPLOAD_TYPES)}")

    image_bytes = await tile.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(image_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Tile is {len(image_bytes)} bytes; the limit is {config.MAX_UPLOAD_BYTES}.")

    records, is_stub, models = run_detector(image_bytes, tile.filename or "tile")
    return DetectResponse(
        stub=is_stub,
        models=models or ["stub"],
        filename=tile.filename or "tile",
        bytes=len(image_bytes),
        detections=[DetectionRecord(**record) for record in records],
    )
