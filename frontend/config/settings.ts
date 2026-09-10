/**
 * Where the backend is, and which parts of the interface exist.
 *
 * Nothing else in the application knows a URL or a route. `lib/api.ts` reads
 * these and every component goes through it.
 */

const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL

export const settings = {
  /** Base URL of the FastAPI backend. Override with NEXT_PUBLIC_API_BASE_URL. */
  apiBaseUrl: (fromEnv && fromEnv.trim()) || 'http://127.0.0.1:8000',

  endpoints: {
    chat: '/chat',
    chatStream: '/chat/stream',
    detect: '/detect',
    health: '/health',
  },

  features: {
    /**
     * Stream the answer as it is written. Off, the interface falls back to the
     * plain JSON route and the answer appears in one piece.
     */
    streaming: true,

    /**
     * Show the tile upload control. The backend also gates its own endpoint, and
     * /health reports which way that flag is set, so the control stays hidden
     * unless both agree.
     */
    enableUpload: true,

    /** Show the retrieval score next to each citation in the panel. */
    showRetrievalScores: true,
  },

  chat: {
    /** Turns replayed to the backend. It clips again on its own side. */
    maxHistoryTurns: 12,
    /** How long a single answer may take before the request is abandoned. */
    requestTimeoutMs: 120_000,
    /** Health is re-checked on this interval while the page is open. */
    healthPollMs: 30_000,
  },
} as const
