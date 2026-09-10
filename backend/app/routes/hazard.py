from fastapi import APIRouter
from app.supabase_client import supabase

router = APIRouter()


@router.get("/hazard/map")
def get_hazard_map():

    scans_response = (
        supabase
        .table("scans")
        .select("*")
        .execute()
    )

    detections_response = (
        supabase
        .table("detections")
        .select("*")
        .execute()
    )

    scans = scans_response.data or []
    detections = detections_response.data or []

    hazards = []

    for scan in scans:

        latitude = scan.get("latitude")
        longitude = scan.get("longitude")

        if latitude is None or longitude is None:
            continue

        scan_detections = [
            detection
            for detection in detections
            if detection.get("scan_id") == scan.get("id")
        ]

        if not scan_detections:
            continue

        anomaly_count = sum(
            1
            for detection in scan_detections
            if detection.get("anomaly") is True
        )

        object_count = len(scan_detections)

        severity = "low"

        if anomaly_count > 0:
            severity = "high"
        elif object_count >= 3:
            severity = "medium"

        hazards.append({
            "scan_id": scan.get("id"),
            "latitude": latitude,
            "longitude": longitude,
            "object_count": object_count,
            "anomaly_count": anomaly_count,
            "severity": severity,
            "status": scan.get("status"),
            "created_at": scan.get("created_at")
        })

    return {
        "total_hazards": len(hazards),
        "hazards": hazards
    }