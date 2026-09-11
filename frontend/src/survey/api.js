/**
 * The only module in this feature that talks to the backend.
 *
 * A component that needs data calls one of these; none of them knows where the
 * backend is. Mirrors src/assistant/lib/api.ts, which follows the same rule.
 */

import { surveyConfig } from "./config"

function url(path) {
  return `${surveyConfig.apiBaseUrl}${path}`
}

export class SurveyApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = "SurveyApiError"
    this.status = status
  }
}

async function getJson(path) {
  let response
  try {
    response = await fetch(url(path))
  } catch (cause) {
    // A failed fetch here almost always means the backend is not running,
    // which is a different problem from the backend saying no, and the
    // interface should be able to tell the operator which one it is. The
    // original error is kept as the cause so it survives into the console.
    const failure = new SurveyApiError(
      "The backend is unreachable. Start it with `uvicorn backend.app.main:app`.",
      0,
    )
    failure.cause = cause
    throw failure
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body && body.detail) detail = body.detail
    } catch {
      // A non-JSON error body is not worth a second failure.
    }
    throw new SurveyApiError(detail, response.status)
  }
  return response.json()
}

/** Every processed survey, newest-looking first is the server's business. */
export async function listSurveys() {
  const body = await getJson(surveyConfig.endpoints.surveys)
  return body.surveys || []
}

/**
 * One survey's export document, exactly as the engine wrote it.
 *
 * Returned unmodified. Every number this page shows is read out of here rather
 * than recomputed, so the page and the export can never disagree about a
 * severity or a rank.
 */
export function fetchExport(surveyId) {
  return getJson(surveyConfig.endpoints.export(surveyId))
}

/** Absolute URL of the standalone map, for the frame and for opening it. */
export function mapUrl(surveyId, hotspotId) {
  const base = url(surveyConfig.endpoints.map(surveyId))
  return hotspotId ? `${base}#${encodeURIComponent(hotspotId)}` : base
}

/** Absolute URL of the prioritised worklist, for download. */
export function actionsUrl(surveyId) {
  return url(surveyConfig.endpoints.actions(surveyId))
}
