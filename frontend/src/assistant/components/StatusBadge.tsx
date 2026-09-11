import { copy } from '../config/copy'
import { theme } from '../config/theme'
import type { ChatResponse, Severity } from '../lib/types'
/**
 * The one-line verdict above an answer: what kind of answer it is, what the
 * classifier said, and the risk level.
 *
 * Severity comes from the backend, which looks it up rather than reading it out
 * of the generated text. This component only decides how it looks.
 */
export function StatusBadge({ meta }: { meta: Partial<ChatResponse> }) {
  const severity = (meta.severity ?? 'unknown') as Severity
  const tone = theme.severity[severity]
  const confidence = typeof meta.confidence === 'number' ? meta.confidence : null
  return (
    <div className="badge-row">
      {meta.intent && <span className="chip chip-quiet">{copy.badge.intent[meta.intent]}</span>}
      {meta.object_class && !meta.is_anomaly && (
        <span className="chip chip-quiet">{meta.object_class}</span>
      )}
      {meta.is_anomaly && <span className="chip chip-quiet">{copy.badge.unclassified}</span>}
      {confidence !== null && (
        <span className="chip chip-plain">{copy.badge.confidence(confidence)}</span>
      )}
      <span className={`chip tone-${tone}`}>
        {copy.badge.severityLabel}
        <span className="chip-divider" aria-hidden="true" />
        {copy.badge.severity[severity]}
      </span>
    </div>
  )
}
