/** The backend contract, mirrored. Field names match the API exactly. */

export type Role = 'user' | 'assistant'
export type Intent = 'question' | 'explain' | 'anomaly' | 'report'
export type Severity = 'low' | 'medium' | 'high' | 'unknown'

export interface Turn {
  role: Role
  content: string
}

export interface DetectionRecord {
  object_class?: string | null
  label?: string | null
  confidence?: number | null
  bbox?: number[] | null
  depth_m?: number | null
  timestamp?: string | null
  latitude?: string | null
  longitude?: string | null
  sensor?: string | null
  platform?: string | null
  notes?: string | null
  visual_description?: string | null
  embedding?: number[] | null
  // Provenance added by the detector. Which checkpoint made the call, what it
  // called the object before the class map translated it, and the other
  // model's opinion where the two disagreed on the same box.
  detector_model?: string | null
  detector_class?: string | null
  second_opinion?: string | null
  /** Set when the detector's class was below the floor this system requires
   *  for that class. The contact is kept, the claim is not. */
  downgraded_from?: string | null
}

export interface Source {
  n: number
  id: string
  title: string
  section?: string | null
  snippet: string
  authority?: string | null
  status?: string | null
  doc_id?: string | null
  path?: string | null
  score: number
  pdf_url?: string | null
}

export interface Match {
  rank: number
  id: string
  name: string
  object_class: string
  hazard: string
  similarity: number
  confirms: string
  rules_out: string
  source: string
  status: string
}

export interface ChatResponse {
  answer: string
  intent: Intent
  object_class?: string | null
  confidence?: number | null
  is_anomaly: boolean
  severity: Severity
  grounded: boolean
  sources: Source[]
  refusal: boolean
  /** The detector named a class the corpus has no document about. */
  coverage_gap: boolean
  matches: Match[]
  query: string
  provider: string
  model: string
}

export interface Health {
  status: 'ready' | 'degraded'
  corpus_loaded: boolean
  documents: number
  chunks: number
  embedder: string
  index: string
  catalog_entries: number
  catalog_space?: string | null
  provider: string
  model: string
  detector: 'stub' | 'loaded' | 'disabled'
  detector_models: string[]
  upload_enabled: boolean
  /** "connected", or the reason storage is unavailable. */
  storage?: string
}

export interface DetectResult {
  stub: boolean
  models: string[]
  filename: string
  bytes: number
  detections: DetectionRecord[]
  /** False when Supabase is unconfigured. The detection still ran. */
  stored?: boolean
  scan_id?: string
  image_url?: string | null
}

/** Frames on the streaming route. */
export type StreamFrame =
  | ({ type: 'meta'; matches: Match[] } & Omit<ChatResponse, 'answer' | 'sources' | 'grounded' | 'refusal' | 'matches'>)
  | { type: 'sources'; sources: Source[] }
  | { type: 'delta'; text: string }
  | ({ type: 'done' } & ChatResponse)
  | { type: 'error'; detail: string }

/**
 * A hotspot handed over from the survey hazard map.
 *
 * The map owns where and how urgent; the assistant owns what and what to do.
 * So `severity` and `severity_tier` here are the map's numbers and are
 * displayed as given. The assistant does not recompute them, because the same
 * hotspot showing two different urgencies is worse than showing one.
 */
export interface SurveyContext {
  hotspot_id: string
  dominant_class: string
  /** max_severity across the cell. Always 0 to 1, so it maps onto the tiers. */
  severity: number
  confidence: number
  centroid: { global_x: number; global_y: number }
  lat: number | null
  lon: number | null
  recommended_action: string
  severity_tier?: 'critical' | 'medium' | 'low'
  priority_rank?: number
  detection_count?: number
  /** Summed over the grid cell and CAN EXCEED 1. Never render as a severity. */
  total_severity?: number
  coordinate_mode?: string
  survey_id?: string
  demo?: boolean
  evidence_tile?: string
}

/** One rendered message. Assistant messages carry the answer metadata with them. */
export interface Message {
  id: string
  role: Role
  content: string
  streaming?: boolean
  failed?: string | null
  meta?: Partial<ChatResponse> | null
  detection?: DetectionRecord | null
  detectionIsStub?: boolean
  /** Set when this turn came from the hazard map. Its severity wins. */
  survey?: SurveyContext | null
}
