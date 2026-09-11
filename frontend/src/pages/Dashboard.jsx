import {
  Play,
  ScanSearch,
  AlertTriangle,
  Ship,
  CheckCircle2,
} from "lucide-react";

import StatCard from "../components/StatCard";
import { stats, detections } from "../data/mockData";

function Dashboard() {
  return (
    <div className="dashboard">

      <section className="stats-grid">

        <StatCard
          title="Detected Objects"
          value={stats.objects}
          subtitle="Across current scan"
        />

        <StatCard
          title="Anomalies"
          value={stats.anomalies}
          subtitle="3 require review"
          type="anomaly"
        />

        <StatCard
          title="Wrecks / Ships"
          value={stats.wrecks}
          subtitle="High-confidence results"
        />

        <StatCard
          title="Analyzed"
          value={`${stats.analyzed}%`}
          subtitle="Current sonar survey"
        />

      </section>

      <section className="dashboard-content">

        <div className="sonar-panel">

          <div className="panel-header">
            <div>
              <h2>Latest Sonar Scan</h2>
              <p>Side-scan sonar imagery analysis</p>
            </div>

            <span className="scan-badge">
              Scan SSS-024
            </span>
          </div>

          <div className="sonar-placeholder">

            <ScanSearch size={52} />

            <h3>Sonar Scan Preview</h3>

            <p>
              Upload a side-scan sonar image to begin
              automated detection and anomaly analysis.
            </p>

          </div>

          <button className="analyze-button">
            <Play size={18} />
            Analyze Scan
          </button>

        </div>

        <div className="recent-panel">

          <div className="panel-header">
            <div>
              <h2>Recent Detections</h2>
              <p>Latest AI findings</p>
            </div>
          </div>

          <div className="detection-list">

            {detections.map((detection) => (

              <div
                className="detection-item"
                key={detection.id}
              >

                <div
                  className={`detection-icon ${detection.type}`}
                >
                  {detection.type === "anomaly" ? (
                    <AlertTriangle size={19} />
                  ) : detection.type === "wreck" ? (
                    <Ship size={19} />
                  ) : (
                    <CheckCircle2 size={19} />
                  )}
                </div>

                <div className="detection-info">

                  <div className="detection-top">
                    <strong>{detection.name}</strong>

                    <span>
                      {detection.confidence}%
                    </span>
                  </div>

                  <p>
                    {detection.latitude.toFixed(4)},{" "}
                    {detection.longitude.toFixed(4)}
                  </p>

                  <small>{detection.time}</small>

                </div>

              </div>

            ))}

          </div>

          <button className="view-all-button">
            View All Detections
          </button>

        </div>

      </section>

    </div>
  );
}

export default Dashboard;