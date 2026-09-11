from fastapi import APIRouter
from ..supabase_client import require_supabase

router = APIRouter()


@router.get("/stats")
def get_stats():
    scans_response = require_supabase().table("scans").select("*").execute()
    detections_response = require_supabase().table("detections").select("*").execute()

    scans = scans_response.data or []
    detections = detections_response.data or []

    total_scans = len(scans)
    total_detections = len(detections)

    total_anomalies = sum(
        1 for detection in detections
        if detection.get("anomaly") is True
    )

    severity_counts = {
        "low": 0,
        "medium": 0,
        "high": 0
    }

    for detection in detections:
        severity = detection.get("severity")

        if severity in severity_counts:
            severity_counts[severity] += 1

    return {
        "total_scans": total_scans,
        "total_detections": total_detections,
        "total_anomalies": total_anomalies,
        "severity_counts": severity_counts
    }