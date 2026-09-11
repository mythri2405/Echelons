import { styleForTier } from "../config"

/**
 * The priority worklist. Rank, hazard, severity, count, action.
 *
 * Order comes from the export and is not re-sorted here. The engine ranks by
 * total severity rather than by detection count, and re-sorting in the
 * interface would be a second opinion on a decision that has already been made
 * and recorded with its reasoning.
 */
function HotspotTable({ hotspots, selectedId, onSelect, emptyMessage }) {
  if (!hotspots.length) {
    return <p className="sv-empty">{emptyMessage}</p>
  }

  return (
    <div className="sv-table-wrap">
      <table className="sv-table">
        <thead>
          <tr>
            <th className="sv-col-rank">Rank</th>
            <th>Hazard</th>
            <th className="sv-col-num">Severity</th>
            <th className="sv-col-num">Count</th>
            <th>Recommended action</th>
          </tr>
        </thead>
        <tbody>
          {hotspots.map((hotspot) => {
            const style = styleForTier(hotspot.severity_tier)
            const selected = hotspot.hotspot_id === selectedId

            return (
              <tr
                key={hotspot.hotspot_id}
                className={selected ? "sv-row sv-row-selected" : "sv-row"}
                onClick={() => onSelect(hotspot.hotspot_id)}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    onSelect(hotspot.hotspot_id)
                  }
                }}
              >
                <td className="sv-col-rank">
                  <span className="sv-rank" style={{ background: style.tint, color: style.color }}>
                    {hotspot.priority_rank}
                  </span>
                </td>
                <td>
                  <strong>{hotspot.dominant_class}</strong>
                  <span className="sv-id">{hotspot.hotspot_id}</span>
                </td>
                <td className="sv-col-num">
                  <span className="sv-tier-dot" style={{ background: style.color }} />
                  {hotspot.total_severity.toFixed(3)}
                </td>
                <td className="sv-col-num">{hotspot.detection_count}</td>
                <td className="sv-action">{hotspot.recommended_action}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default HotspotTable
