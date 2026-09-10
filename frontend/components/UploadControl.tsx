'use client'

import { useRef, useState } from 'react'

import { copy } from '../config/copy'
import { settings } from '../config/settings'
import { detectTile } from '../lib/api'
import type { DetectResult } from '../lib/types'

interface Props {
  enabled: boolean
  onResult: (result: DetectResult) => void
  onError: (message: string) => void
}

/**
 * Tile upload.
 *
 * Hidden unless the feature flag and the backend's own flag both allow it, so
 * the control never offers something the server will refuse.
 */
export function UploadControl({ enabled, onResult, onError }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  if (!enabled || !settings.features.enableUpload) return null

  const choose = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      onResult(await detectTile(file))
    } catch (error) {
      onError(error instanceof Error ? error.message : copy.error.generic)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*"
        className="visually-hidden"
        onChange={(event) => choose(event.target.files?.[0])}
      />
      <button
        type="button"
        className="button-secondary"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        {busy ? copy.upload.uploading : copy.upload.button}
      </button>
    </>
  )
}
