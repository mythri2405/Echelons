import { useEffect, useRef } from "react"

/**
 * The generated map.html, embedded.
 *
 * The file is the same standalone artefact the engine writes: it carries its
 * own Leaflet and its own imagery and needs nothing from the network. Embedding
 * it rather than rebuilding the map in React means there is one map in this
 * project, not two that can disagree.
 *
 * Selecting a hotspot here posts a message into the frame, which is the only
 * channel between them. The frame is served from the backend's origin rather
 * than the dev server's, so a direct DOM reach would be blocked anyway; the
 * message carries a hotspot identifier and nothing else, and the map ignores
 * any id that is not one of its own.
 */
function MapFrame({ src, focusId, title }) {
  const frame = useRef(null)
  const loaded = useRef(false)

  useEffect(() => {
    if (!focusId || !loaded.current) return
    const target = frame.current?.contentWindow
    if (!target) return
    target.postMessage({ type: "deepecho:focus", hotspot_id: focusId }, "*")
  }, [focusId, src])

  return (
    <iframe
      ref={frame}
      className="sv-map-frame"
      src={src}
      title={title}
      onLoad={() => {
        loaded.current = true
        if (focusId) {
          frame.current?.contentWindow?.postMessage(
            { type: "deepecho:focus", hotspot_id: focusId },
            "*",
          )
        }
      }}
    />
  )
}

export default MapFrame
