from fastapi import APIRouter, HTTPException
from ..supabase_client import require_supabase

router = APIRouter()


@router.get("/history")
def get_history():

    response = (
        require_supabase()
        .table("scans")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return {
        "scans": response.data
    }

@router.get("/history/{scan_id}")
def get_scan_details(scan_id: str):

    scan_response = (
        require_supabase()
        .table("scans")
        .select("*")
        .eq("id", scan_id)
        .execute()
    )

    if not scan_response.data:
        raise HTTPException(
            status_code=404,
            detail="Scan not found"
        )

    detection_response = (
        require_supabase()
        .table("detections")
        .select("*")
        .eq("scan_id", scan_id)
        .execute()
    )

    scan = scan_response.data[0]
    detections = detection_response.data or []

    total_objects = len(detections)

    total_anomalies = sum(
        1
        for detection in detections
        if detection.get("anomaly") is True
    )

    return {
        "scan_id": scan_id,
        "image_url": scan.get("image_url"),
        "status": scan.get("status"),
        "latitude": scan.get("latitude"),
        "longitude": scan.get("longitude"),
        "created_at": scan.get("created_at"),
        "total_objects": total_objects,
        "total_anomalies": total_anomalies,
        "detections": detections
    }
