/**
 * Citation markers, from the model's text to something clickable.
 *
 * The prompt asks for [S1], but providers render citations their own way:
 * fullwidth brackets, parentheses, and runs collapsed into [S1, S3, S6]. The
 * backend's grounding check handles all three, and so must this, or a cited
 * answer renders as plain text with brackets in it.
 *
 * The rewrite turns every marker into a markdown link with a `#cite-N` target,
 * which the renderer maps to a clickable marker component. Doing it before
 * parsing rather than after keeps the rest of the markdown untouched.
 */

const GROUP = /[[(【]([^[\]()【】]{0,80})[\])】]/g
const REF = /S\s*(\d+)/g

export function linkCitations(markdown: string): string {
  return markdown.replace(GROUP, (whole, inner: string) => {
    const numbers = Array.from(inner.matchAll(REF), (m) => Number(m[1]))
    if (numbers.length === 0) return whole
    return numbers.map((n) => `[${n}](#cite-${n})`).join('')
  })
}

/** The source number behind a `#cite-N` href, or null if it is an ordinary link. */
export function citationTarget(href: string | undefined): number | null {
  if (!href) return null
  const match = /^#cite-(\d+)$/.exec(href)
  return match ? Number(match[1]) : null
}
