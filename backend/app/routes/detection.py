from app.services.detection_service import save_detections
from fastapi import APIRouter, UploadFile, File
import os
import uuid

from app.supabase_client import supabase
from typing import Optional

router = APIRouter()


@router.post("/detect")
async def detect(
    file: UploadFile = File(...),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
):

    # 1. Generate unique ID for this scan
    scan_id = str(uuid.uuid4())

    # 2. Get file extension
    file_extension = os.path.splitext(file.filename)[1]

    # 3. Create storage path
    storage_path = f"{scan_id}{file_extension}"

    # 4. Read uploaded image
    file_data = await file.read()

    # 5. Upload image to Supabase Storage
    supabase.storage.from_("sonar-images").upload(
        path=storage_path,
        file=file_data,
        file_options={
            "content-type": file.content_type,
            "upsert": "false"
        }
    )

    # 6. Save scan information in database
    scan_data = {
        "id": scan_id,
        "image_url": storage_path,
        "latitude": latitude,
        "longitude": longitude,
        "status": "uploaded"
    }

    supabase.table("scans").insert(scan_data).execute()

    test_detections = [
    {
        "id": str(uuid.uuid4()),
        "class": "debris",
        "confidence": 0.94,
        "bbox": [120, 80, 350, 290],
        "anomaly": False,
        "severity": "medium"
    }
    ]

    saved_detections = save_detections(
        scan_id,
        test_detections
    )

    # 7. Return response
    return {
        "scan_id": scan_id,
        "image_url": storage_path,
        "status": "uploaded",
        "detections": saved_detections
    }