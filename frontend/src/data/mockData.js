export const stats = {
  objects: 24,
  anomalies: 5,
  wrecks: 2,
  analyzed: 92,
};

export const detections = [
  {
    id: "DET-001",
    name: "Possible Shipwreck",
    type: "wreck",
    confidence: 94.2,
    latitude: 15.2841,
    longitude: 73.912,
    status: "Detected",
    time: "2 min ago",
  },
  {
    id: "DET-002",
    name: "Marine Debris",
    type: "debris",
    confidence: 88.4,
    latitude: 15.2846,
    longitude: 73.9132,
    status: "Detected",
    time: "5 min ago",
  },
  {
    id: "DET-003",
    name: "Unknown Anomaly",
    type: "anomaly",
    confidence: 63.4,
    latitude: 15.285,
    longitude: 73.9141,
    status: "Review",
    time: "8 min ago",
  },
];