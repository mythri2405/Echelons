function StatCard({ title, value, subtitle, type }) {
  return (
    <div className={`stat-card ${type || ""}`}>

      <div className="stat-value">
        {value}
      </div>

      <div className="stat-title">
        {title}
      </div>

      {subtitle && (
        <div className="stat-subtitle">
          {subtitle}
        </div>
      )}

    </div>
  );
}

export default StatCard;