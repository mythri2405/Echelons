import { useEffect } from 'react'
import { copy } from '../config/copy'
import { settings } from '../config/settings'
import type { Source } from '../lib/types'
interface Props {
  sources: Source[]
  selected: number | null
  onSelect: (n: number) => void
  onClose: () => void
}
/**
 * The proof panel.
 *
 * Everything the assistant asserts is supposed to trace to a passage in a real
 * publication. This is where an operator checks that, so it shows the passage
 * itself rather than a summary of it, names who published it, and links the
 * original file when one is attached.
 */
export function CitationPanel({ sources, selected, onSelect, onClose }: Props) {
  const open = selected !== null && sources.length > 0
  const active = sources.find((s) => s.n === selected) ?? null
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  return (
    <>
      <div
        className={`panel-scrim ${open ? 'is-open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className={`panel ${open ? 'is-open' : ''}`} aria-hidden={!open}>
        <header className="panel-head">
          <h2 className="panel-title">{copy.citations.panelTitle}</h2>
          <button type="button" className="button-quiet" onClick={onClose}>
            {copy.citations.close}
          </button>
        </header>
        {active && (
          <div className="panel-body">
            <div className="source-card">
              <div className="source-index">{active.n}</div>
              <div className="source-headings">
                <h3 className="source-title">{active.title}</h3>
                {active.section && (
                  <p className="source-sub">
                    {copy.citations.section}: {active.section}
                  </p>
                )}
              </div>
            </div>
            <dl className="source-meta">
              {active.authority && (
                <div>
                  <dt>{copy.citations.authority}</dt>
                  <dd>{active.authority}</dd>
                </div>
              )}
              {active.status && (
                <div>
                  <dt>{copy.citations.status}</dt>
                  <dd>{active.status}</dd>
                </div>
              )}
              {settings.features.showRetrievalScores && (
                <div>
                  <dt>{copy.citations.similarity}</dt>
                  <dd className="mono">{active.score.toFixed(3)}</dd>
                </div>
              )}
            </dl>
            <blockquote className="source-snippet">{active.snippet}</blockquote>
            {active.pdf_url ? (
              <a
                className="button-link"
                href={`${settings.apiBaseUrl}${active.pdf_url}`}
                target="_blank"
                rel="noreferrer"
              >
                {copy.citations.openPdf}
              </a>
            ) : (
              <p className="source-sub">{copy.citations.noPdf}</p>
            )}
            <h4 className="panel-subhead">{copy.citations.listTitle}</h4>
            <ul className="source-list">
              {sources.map((source) => (
                <li key={source.id}>
                  <button
                    type="button"
                    className={`source-list-item ${source.n === active.n ? 'is-active' : ''}`}
                    onClick={() => onSelect(source.n)}
                  >
                    <span className="source-list-index">{source.n}</span>
                    <span className="source-list-title">{source.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </>
  )
}
