"""The detector, in its own process.

Run as `python -m backend.detector_worker`. Reads one JSON request per line on
stdin, writes one JSON response per line on stdout.

This exists for an unglamorous reason. faiss and torch each bundle their own
copy of libomp, and on macOS the second one to initialise aborts the process
with OMP Error #15. The vendor's own workaround, KMP_DUPLICATE_LIB_OK, is
documented as unsafe and as possibly producing silently incorrect results,
which is not a trade a safety system should make. Keeping the two libraries in
separate processes removes the conflict instead of suppressing it, and costs
one subprocess that loads its weights once and stays up.

The worker is deliberately dumb. It returns raw boxes with the class names the
checkpoints were trained with. Class mapping, merging and severity stay in the
main process, where the configuration lives.
"""

from __future__ import annotations

import io
import json
import sys

from . import config


def load_models() -> dict:
    from ultralytics import YOLO

    return {name: YOLO(str(path))
            for name, path in config.DETECTOR_MODELS.items() if path.exists()}


def predict(models: dict, image_bytes: bytes) -> list[dict]:
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    boxes = []
    for name, model in models.items():
        for result in model.predict(source=image, conf=config.DETECTOR_CONFIDENCE,
                                    imgsz=config.DETECTOR_IMGSZ, verbose=False):
            for box in result.boxes:
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                boxes.append({
                    "model": name,
                    "cls": result.names[int(box.cls)],
                    "confidence": round(float(box.conf), 4),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                })
    return boxes


def main() -> None:
    try:
        models = load_models()
    except Exception as exc:
        print(json.dumps({"ready": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        return

    names = {name: list(model.model.names.values()) for name, model in models.items()}
    print(json.dumps({"ready": True, "models": sorted(models), "classes": names}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            with open(request["image_path"], "rb") as handle:
                boxes = predict(models, handle.read())
            print(json.dumps({"ok": True, "boxes": boxes}), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
