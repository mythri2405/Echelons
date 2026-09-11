import { Upload, Activity } from "lucide-react";

function Header() {
  return (
    <header className="header">

      <div>
        <h1>Dashboard</h1>
        <p>Monitor and analyze underwater sonar surveys</p>
      </div>

      <div className="header-actions">

        <div className="connection-status">
          <Activity size={16} />
          ML Service Ready
        </div>

        <button className="upload-button">
          <Upload size={18} />
          Upload Sonar Scan
        </button>

      </div>

    </header>
  );
}

export default Header;