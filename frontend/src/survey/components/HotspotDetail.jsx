import { ExternalLink, MessageSquareText } from "lucide-react"

import { copy, styleForTier } from "../config"

/**
 * Everything known about one hotspot, and the one place a hazard leaves this
 * feature for the assistant.
 *
 * The severity breakdown is spelled out rather than summarised, because the
 * whole formula is one multiplication and showing it is cheaper than asking
 * anyone to trust it.
 */
function HotspotDetail({ hotspot, detections, survey, onAsk }) {
  if (!hotspot) {
    return (
      <div className="sv-detail sv-detail-empty">
        <p>Select a hotspot to see its detections, evidence and recommended action.</p>
      </div>
    )
  }

  const style = styleForTier(hotspot.severity_tier)
  const centroid = hotspot.centroid || {}
  const georeferenced = centroid.latitude !== null && centroid.latitude !== undefined
  const tiles = [
    ...new Set(detections.flatMap((d) => d.provenance?.source_tiles || [])),
  ].sort()

  return (
    <div className="sv-detail">
      <div className="sv-detail-head">
        <div>
          <span className="sv-detail-id">{hotspot.hotspot_id}</span>
          <h3>{hotspot.dominant_class}</h3>
        </div>
        <span className="sv-chip" style={{ background: style.tint, color: style.color }}>
          {style.label} &middot; rank {hotspot.priority_rank}
        </span>
      </div>

      <p className="sv-recommend" style={{ borderLeftColor: style.color }}>
        <strong>{hotspot.recommended_action}</strong>
      </p>

      <dl className="sv-facts">
        <div>
          <dt>Total severity</dt>
          <dd>
            {hotspot.total_severity.toFixed(4)}
            <span className="sv-sub">summed over the cell, can exceed 1</span>
          </dd>
        </div>
        <div>
          <dt>Worst single</dt>
          <dd>
            {hotspot.max_severity.toFixed(4)}
            <span className="sv-sub">0 to 1, sets the tier</span>
          </dd>
        </div>
        <div>
          <dt>Risk index</dt>
          <dd>
            {hotspot.risk_score.toFixed(4)}
            <span className="sv-sub">not a percentage</span>
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>
            {hotspot.confidence_max.toFixed(2)} max
            <span className="sv-sub">{hotspot.confidence_mean.toFixed(2)} mean</span>
          </dd>
        </div>
        <div>
          <dt>Detections</dt>
          <dd>
            {hotspot.detection_count}
            <span className="sv-sub">{hotspot.hazard_diversity} distinct class(es)</span>
          </dd>
        </div>
        <div>
          <dt>Centroid</dt>
          <dd>
            x {centroid.global_x?.toFixed(1)}, y {centroid.global_y?.toFixed(1)} px
            {/* A latitude is shown only where one genuinely exists. In a
                relative survey this line is absent rather than blank, so
                nothing on screen can be mistaken for a fix. */}
            {georeferenced && (
              <span className="sv-sub">
                {centroid.latitude.toFixed(6)}, {centroid.longitude.toFixed(6)}
              </span>
            )}
          </dd>
        </div>
      </dl>

      <h4 className="sv-detail-sub">Detections in this hotspot</h4>
      <table className="sv-inner-table">
        <thead>
          <tr>
            <th>Class</th>
            <th className="sv-col-num">Conf</th>
            <th className="sv-col-num">Weight</th>
            <th className="sv-col-num">Severity</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {detections.map((detection) => {
            const rowStyle = styleForTier(detection.severity_tier)
            return (
              <tr key={detection.id}>
                <td>
                  {detection.object_class}
                  {/* The detector's own call, where this system judged it too
                      uncertain to assert. Kept visible: the operator should be
                      able to see what was withheld and why. */}
                  {detection.class_withheld && (
                    <span className="sv-withheld">
                      {detection.class_withheld} withheld below {detection.class_floor}
                    </span>
                  )}
                </td>
                <td className="sv-col-num">{detection.confidence.toFixed(2)}</td>
                <td className="sv-col-num">{detection.class_weight}</td>
                <td className="sv-col-num" style={{ color: rowStyle.color }}>
                  {detection.severity.toFixed(3)}
                </td>
                <td className="sv-evidence">
                  {detection.provenance?.representative_tile}
                  {detection.provenance?.merged_count > 1 && (
                    <span className="sv-sub">
                      {detection.provenance.merged_count} views merged
                    </span>
                  )}
                  {detection.provenance?.second_opinion?.map((opinion, index) => (
                    <span className="sv-sub" key={index}>
                      {opinion.model} called it {opinion.object_class} at{" "}
                      {opinion.confidence.toFixed(2)}
                    </span>
                  ))}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {tiles.length > 0 && (
        <p className="sv-tiles">
          <span>Source tiles</span>
          {tiles.join(", ")}
        </p>
      )}

      <div className="sv-detail-actions">
        <button type="button" className="sv-btn sv-btn-primary" onClick={() => onAsk(hotspot)}>
          <MessageSquareText size={15} />
          {copy.askAssistant}
        </button>
        <a
          className="sv-btn"
          href={survey.mapHref}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={15} />
          Open map full screen
        </a>
      </div>
    </div>
  )
}

export default HotspotDetail
