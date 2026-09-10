'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { copy } from '../config/copy'
import { settings } from '../config/settings'
import { getHealth, sendChat, streamChat } from '../lib/api'
import type {
  DetectResult,
  DetectionRecord,
  Health,
  Message,
  Source,
  Turn,
} from '../lib/types'
import { CitationPanel } from './CitationPanel'
import { Composer } from './Composer'
import { MessageBubble } from './MessageBubble'
import { SystemStatus } from './SystemStatus'
import { UploadControl } from './UploadControl'

let counter = 0
const nextId = () => `m${++counter}`

/**
 * The conversation.
 *
 * Holds the turns, the detection record currently attached, and the streaming
 * state. History is client-side: every request carries the turns it needs, so
 * the backend stores nothing and there is no session to lose.
 */
export function ChatWindow() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [detection, setDetection] = useState<DetectionRecord | null>(null)
  const [contacts, setContacts] = useState<DetectionRecord[]>([])
  const [detectionIsStub, setDetectionIsStub] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [panelSources, setPanelSources] = useState<Source[]>([])
  const [panelSelected, setPanelSelected] = useState<number | null>(null)

  const abort = useRef<AbortController | null>(null)
  const lastAttached = useRef<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let live = true
    const check = async () => {
      try {
        const result = await getHealth()
        if (!live) return
        setHealth(result)
        setHealthError(null)
      } catch (error) {
        if (!live) return
        setHealth(null)
        setHealthError(error instanceof Error ? error.message : copy.error.backendDown)
      }
    }
    check()
    const timer = setInterval(check, settings.chat.healthPollMs)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    const node = scroller.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages])

  const patch = useCallback((id: string, change: Partial<Message>) => {
    setMessages((current) =>
      current.map((message) => (message.id === id ? { ...message, ...change } : message)),
    )
  }, [])

  const openCitation = useCallback((n: number, sources: Source[]) => {
    if (sources.length === 0) return
    setPanelSources(sources)
    setPanelSelected(sources.some((s) => s.n === n) ? n : sources[0].n)
  }, [])

  const stop = useCallback(() => {
    abort.current?.abort()
    abort.current = null
    setBusy(false)
  }, [])

  const send = useCallback(async (override?: { text?: string; record?: DetectionRecord }) => {
    const text = (override?.text ?? draft).trim()
    if (!text || busy) return

    // An upload sends its own opening turn before React has committed the new
    // detection state, so the record travels with the call rather than being
    // read back from state that is one render behind.
    const record = override?.record ?? detection
    const snapshot = record ? JSON.stringify(record) : null
    const showRecord = snapshot !== null && snapshot !== lastAttached.current
    lastAttached.current = snapshot

    const history: Turn[] = messages
      .filter((message) => !message.failed || message.role === 'user')
      .slice(-settings.chat.maxHistoryTurns)
      .map((message) => ({ role: message.role, content: message.content }))

    const userMessage: Message = {
      id: nextId(),
      role: 'user',
      content: text,
      detection: showRecord ? record : null,
      detectionIsStub: showRecord ? detectionIsStub : false,
    }
    const replyId = nextId()
    setMessages((current) => [
      ...current,
      userMessage,
      { id: replyId, role: 'assistant', content: '', streaming: true, meta: {} },
    ])
    setDraft('')
    setBusy(true)

    const controller = new AbortController()
    abort.current = controller
    const request = { message: text, history, detection_record: record }

    try {
      if (settings.features.streaming) {
        await streamChat(
          request,
          {
            onFrame: (frame) => {
              if (frame.type === 'delta') {
                setMessages((current) =>
                  current.map((message) =>
                    message.id === replyId
                      ? { ...message, content: message.content + frame.text }
                      : message,
                  ),
                )
              } else if (frame.type === 'meta') {
                const { type, ...meta } = frame
                patch(replyId, { meta })
              } else if (frame.type === 'sources') {
                setMessages((current) =>
                  current.map((message) =>
                    message.id === replyId
                      ? { ...message, meta: { ...message.meta, sources: frame.sources } }
                      : message,
                  ),
                )
              } else if (frame.type === 'done') {
                const { type, ...meta } = frame
                patch(replyId, { meta, content: meta.answer, streaming: false })
              } else if (frame.type === 'error') {
                patch(replyId, { streaming: false, failed: frame.detail })
              }
            },
          },
          controller.signal,
        )
      } else {
        const response = await sendChat(request, controller.signal)
        patch(replyId, { meta: response, content: response.answer, streaming: false })
      }
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === 'AbortError'
      patch(replyId, {
        streaming: false,
        failed: aborted
          ? copy.error.streamInterrupted
          : error instanceof Error
            ? error.message
            : copy.error.generic,
      })
    } finally {
      patch(replyId, { streaming: false })
      abort.current = null
      setBusy(false)
    }
  }, [busy, detection, detectionIsStub, draft, messages, patch])

  const onDetections = (result: DetectResult) => {
    setUploadError(null)
    const first = result.detections[0]
    if (!first) {
      setUploadError(copy.upload.noDetections)
      return
    }
    setContacts(result.detections)
    setDetection(first)
    setDetectionIsStub(result.stub)
    lastAttached.current = null
    // The tile is the question. Nobody should have to type one to find out what
    // the detector just found.
    void send({ text: copy.upload.autoBrief, record: first })
  }

  const uploadEnabled = Boolean(health?.upload_enabled)

  return (
    <div className="app">
      <SystemStatus health={health} error={healthError} />

      <div className="thread" ref={scroller}>
        <div className="thread-inner">
          {messages.length === 0 ? (
            <EmptyState onPick={setDraft} disabled={busy} />
          ) : (
            messages.map((message) => (
              <MessageBubble key={message.id} message={message} onCitation={openCitation} />
            ))
          )}

          {healthError && messages.length === 0 && (
            <div className="notice tone-alert">
              <p className="notice-title">{copy.error.title}</p>
              <p className="notice-body">{copy.error.backendDown}</p>
            </div>
          )}
        </div>
      </div>

      <div className="dock">
        <div className="dock-inner">
          {detection && (
            <div className="attached">
              <span className="attached-label">{copy.detection.title}</span>
              <span className="attached-value">
                {detection.object_class ?? detection.label ?? copy.badge.unclassified}
                {typeof detection.confidence === 'number' &&
                  ` · ${copy.badge.confidence(detection.confidence)}`}
              </span>
              {detectionIsStub && <span className="attached-stub">{copy.notice.stubDetectionTitle}</span>}
              {detection.downgraded_from && (
                <span className="attached-stub" title={detection.downgraded_from}>
                  {copy.upload.downgraded}
                </span>
              )}
              <button
                type="button"
                className="button-quiet"
                onClick={() => {
                  setDetection(null)
                  setContacts([])
                  setDetectionIsStub(false)
                  lastAttached.current = null
                }}
              >
                {copy.upload.detach}
              </button>
            </div>
          )}

          {contacts.length > 1 && (
            <div className="attached">
              <span className="attached-label">{copy.upload.contactsLabel}</span>
              {contacts.map((contact, index) => (
                <button
                  key={index}
                  type="button"
                  className={`source-pill ${contact === detection ? 'is-active' : ''}`}
                  onClick={() => {
                    setDetection(contact)
                    lastAttached.current = null
                  }}
                >
                  {copy.upload.contact(
                    index + 1,
                    contact.object_class ?? copy.badge.unclassified,
                    contact.confidence ?? 0,
                  )}
                </button>
              ))}
            </div>
          )}

          {uploadError && <p className="dock-error">{uploadError}</p>}

          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => send()}
            onStop={stop}
            busy={busy}
            disabled={Boolean(healthError)}
          >
            <UploadControl
              enabled={uploadEnabled}
              onResult={onDetections}
              onError={setUploadError}
            />
          </Composer>
        </div>
      </div>

      <CitationPanel
        sources={panelSources}
        selected={panelSelected}
        onSelect={setPanelSelected}
        onClose={() => setPanelSelected(null)}
      />
    </div>
  )
}

function EmptyState({ onPick, disabled }: { onPick: (value: string) => void; disabled: boolean }) {
  return (
    <section className="empty">
      <h1 className="empty-title">{copy.empty.title}</h1>
      <p className="empty-body">{copy.empty.body}</p>
      <p className="empty-label">{copy.empty.examplesLabel}</p>
      <ul className="empty-examples">
        {copy.empty.examples.map((example) => (
          <li key={example}>
            <button
              type="button"
              className="example"
              disabled={disabled}
              onClick={() => onPick(example)}
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
