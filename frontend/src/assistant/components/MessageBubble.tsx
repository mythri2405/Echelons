import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { copy } from '../config/copy'
import { citationTarget, linkCitations } from '../lib/citations'
import type { Message, Source, SurveyContext } from '../lib/types'
import { StatusBadge } from './StatusBadge'
interface Props {
  message: Message
  onCitation: (n: number, sources: Source[]) => void
}
/**
 * One message.
 *
 * The assistant half carries the honesty machinery. An ungrounded answer, an
 * answer that declined to fill a gap, and an unidentified object each render
 * differently from a confident one, because an operator scanning quickly should
 * not have to read the prose to find out which they are looking at.
 */
export function MessageBubble({ message, onCitation }: Props) {
  if (message.role === 'user') {
    return (
      <article className="message message-user">
        <p className="message-role">{copy.roles.user}</p>
        <div className="bubble bubble-user">{message.content}</div>
        {message.detection && <DetectionSummary message={message} />}
      </article>
    )
  }
  const meta = message.meta ?? {}
  const sources = meta.sources ?? []
  const ungrounded = meta.grounded === false && !message.streaming
  const showRefusal = meta.refusal === true && meta.grounded !== false
  return (
    <article className="message message-assistant">
      <p className="message-role">{copy.roles.assistant}</p>
      <div className={`bubble bubble-assistant ${ungrounded ? 'is-ungrounded' : ''}`}>
        {!message.streaming && meta.intent && (
          <StatusBadge meta={meta} survey={message.survey} />
        )}

        {message.survey && <SurveyHandover survey={message.survey} />}
        {meta.coverage_gap && (
          <Notice
            tone="caution"
            title={copy.notice.coverageGapTitle}
            body={copy.notice.coverageGapBody}
          />
        )}
        {meta.is_anomaly && (
          <Notice tone="caution" title={copy.notice.anomalyTitle} body={copy.notice.anomalyBody} />
        )}
        {ungrounded && (
          <Notice tone="alert" title={copy.notice.ungroundedTitle} body={copy.notice.ungroundedBody} />
        )}
        {showRefusal && (
          <Notice tone="caution" title={copy.notice.refusalTitle} body={copy.notice.refusalBody} />
        )}
        <div className="prose">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a({ href, children, ...rest }) {
                const target = citationTarget(href)
                if (target === null) {
                  return (
                    <a href={href} target="_blank" rel="noreferrer" {...rest}>
                      {children}
                    </a>
                  )
                }
                return (
                  <button
                    type="button"
                    className="cite"
                    title={copy.citations.markerTitle(target)}
                    onClick={() => onCitation(target, sources)}
                  >
                    {target}
                  </button>
                )
              },
            }}
          >
            {linkCitations(message.content)}
          </ReactMarkdown>
          {message.streaming && <span className="caret" aria-hidden="true" />}
        </div>
        {meta.matches && meta.matches.length > 0 && !message.streaming && (
          <section className="matches">
            <h4 className="matches-title">{copy.matches.title}</h4>
            <p className="matches-caveat">{copy.matches.caveat}</p>
            <ol className="matches-list">
              {meta.matches.map((match) => (
                <li key={match.id}>
                  <div className="matches-head">
                    <span className="matches-name">{match.name}</span>
                    <span className="matches-score mono">
                      {copy.matches.similarity} {match.similarity.toFixed(2)}
                    </span>
                  </div>
                  <p className="matches-line">
                    <span className="matches-label">{copy.matches.hazard}</span> {match.hazard}
                  </p>
                  <p className="matches-line">
                    <span className="matches-label">{copy.matches.confirms}</span> {match.confirms}
                  </p>
                  <p className="matches-line">
                    <span className="matches-label">{copy.matches.rulesOut}</span> {match.rules_out}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        )}
        {sources.length > 0 && (
          <footer className="sources-strip">
            <span className="sources-count">{copy.citations.count(sources.length)}</span>
            {sources.map((source) => (
              <button
                key={source.id}
                type="button"
                className="source-pill"
                onClick={() => onCitation(source.n, sources)}
              >
                <span className="source-pill-index">{source.n}</span>
                {source.title}
              </button>
            ))}
          </footer>
        )}
      </div>
      {message.failed && (
        <div className="notice tone-alert">
          <p className="notice-title">{copy.error.title}</p>
          <p className="notice-body">{message.failed}</p>
        </div>
      )}
    </article>
  )
}
function SurveyHandover({ survey }: { survey: SurveyContext }) {
  const georeferenced = survey.lat !== null && survey.lon !== null
  return (
    <div className="survey-handover">
      <p className="survey-from">{copy.survey.from}</p>
      <dl className="detection-fields">
        <div>
          <dt>{copy.survey.action}</dt>
          <dd>{survey.recommended_action}</dd>
        </div>
        <div>
          <dt>{copy.survey.position}</dt>
          <dd className="mono">
            {georeferenced
              ? `${survey.lat}, ${survey.lon}`
              : `x ${survey.centroid.global_x}, y ${survey.centroid.global_y}`}
          </dd>
        </div>
        {typeof survey.priority_rank === 'number' && (
          <div>
            <dt>{copy.survey.rank}</dt>
            <dd>{survey.priority_rank}</dd>
          </div>
        )}
        {typeof survey.detection_count === 'number' && (
          <div>
            <dt>{copy.survey.detections}</dt>
            <dd>{survey.detection_count}</dd>
          </div>
        )}
      </dl>
      {!georeferenced && <p className="survey-note">{copy.survey.notGeoreferenced}</p>}
      {survey.demo && <p className="survey-demo">{copy.survey.demo}</p>}
    </div>
  )
}

function Notice({ tone, title, body }: { tone: string; title: string; body: string }) {
  return (
    <div className={`notice tone-${tone}`}>
      <p className="notice-title">{title}</p>
      <p className="notice-body">{body}</p>
    </div>
  )
}
function DetectionSummary({ message }: { message: Message }) {
  const record = message.detection
  if (!record) return null
  const entries = Object.entries(record).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  )
  return (
    <div className="detection-attached">
      {message.detectionIsStub && (
        <p className="detection-stub">{copy.notice.stubDetectionTitle}</p>
      )}
      <dl className="detection-fields">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{copy.detection.fields[key] ?? key}</dt>
            <dd>{Array.isArray(value) ? value.join(', ') : String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
