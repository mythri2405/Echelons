from app.supabase_client import supabase


def save_detections(scan_id, detections):

    saved_detections = []

    for detection in detections:

        bbox = detection.get("bbox", [0, 0, 0, 0])

        detection_data = {
            "id": detection["id"],
            "scan_id": scan_id,
            "object_class": detection["class"],
            "confidence": detection["confidence"],
            "x1": bbox[0],
            "y1": bbox[1],
            "x2": bbox[2],
            "y2": bbox[3],
            "anomaly": detection.get("anomaly", False),
            "severity": detection.get("severity")
        }

        response = (
            supabase
            .table("detections")
            .insert(detection_data)
            .execute()
        )

        saved_detections.append(response.data)

    return saved_detections