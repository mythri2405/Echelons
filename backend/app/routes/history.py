from fastapi import APIRouter, HTTPException
from app.supabase_client import supabase

router = APIRouter()


@router.get("/history")
def get_history():

    response = (
        supabase
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
        supabase
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
        supabase
        .table("detections")
        .select("*")
        .eq("scan_id", scan_id)
        .execute()
    )

    detections = detection_response.data

    total_objects = len(detections)

    total_anomalies = sum(
        1
        for detection in detections
        if detection.get("anomaly") is True
    )

    return {
        "scan_id": scan_id,
        "image_url": scan_response.data[0]["image_url"],
        "status": scan_response.data[0]["status"],
        "total_objects": total_objects,
        "total_anomalies": total_anomalies,
        "detections": detections
    }