import { useEffect, useRef } from 'react'
import { copy } from '../config/copy'
import { theme } from '../config/theme'
interface Props {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  busy: boolean
  disabled: boolean
  children?: React.ReactNode
}
/** One input box. The operator never picks a mode; the backend routes intent. */
export function Composer({ value, onChange, onSend, onStop, busy, disabled, children }: Props) {
  const field = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const node = field.current
    if (!node) return
    node.style.height = 'auto'
    const max = parseInt(theme.layout.composerMaxHeight, 10)
    node.style.height = `${Math.min(node.scrollHeight, max)}px`
  }, [value])
  const submit = () => {
    if (busy || disabled || !value.trim()) return
    onSend()
  }
  return (
    <div className="composer">
      <div className="composer-inner">
        <textarea
          ref={field}
          className="composer-field"
          rows={1}
          value={value}
          disabled={disabled}
          placeholder={busy ? copy.composer.placeholderStreaming : copy.composer.placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />
        <div className="composer-actions">
          {children}
          {busy ? (
            <button type="button" className="button-secondary" onClick={onStop}>
              {copy.composer.stop}
            </button>
          ) : (
            <button
              type="button"
              className="button-primary"
              onClick={submit}
              disabled={disabled || !value.trim()}
            >
              {copy.composer.send}
            </button>
          )}
        </div>
      </div>
      <p className="composer-hint">{copy.composer.hint}</p>
    </div>
  )
}
