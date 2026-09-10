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

    scans = scans_response.data
    detections = detections_response.data

    hazards = []

    for scan in scans:

        scan_detections = [
            detection
            for detection in detections
            if detection["scan_id"] == scan["id"]
        ]

        if not scan_detections:
            continue

        anomaly_count = sum(
            1
            for detection in scan_detections
            if detection["anomaly"] is True
        )

        severity = "low"

        if anomaly_count > 0:
            severity = "high"
        elif len(scan_detections) >= 3:
            severity = "medium"

        hazards.append({
            "scan_id": scan["id"],
            "latitude": scan["latitude"],
            "longitude": scan["longitude"],
            "object_count": len(scan_detections),
            "anomaly_count": anomaly_count,
            "severity": severity
        })

    return {
        "hazards": hazards
    }