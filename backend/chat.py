"""The seam: one call in, structured answer out.

rag.py already does the hard parts -- retrieval, the grounding prompt, the
refusal behaviour -- but its entry point prints to stdout and takes an argparse
namespace, so a server cannot use it. This module builds a parallel path over
the same clean pieces:

    Retriever.search()  ->  the hits, unchanged
    rag.generate()      ->  the answer text, unchanged
    Chunk.meta          ->  the citations that generate() throws away

Nothing here re-implements retrieval or edits the system prompt. What it adds
is what a conversation needs and a one-shot CLI did not: history that survives
a follow-up, intent chosen for the operator instead of by them, and metadata
the interface can render.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterator

import rag

from . import config


class EngineError(RuntimeError):
    """A failure inside rag.py, converted from SystemExit.

    rag.py is a CLI and exits the process on a bad state. Under uvicorn that
    would take the worker down mid-request, so every call into it is funnelled
    through here.
    """


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        raise EngineError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Loaded once, not per request
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_retriever() -> "rag.Retriever":
    return _guard(rag.Retriever.load, ef_search=config.EF_SEARCH)


@lru_cache(maxsize=1)
def get_catalog() -> "rag.Catalog | None":
    return _guard(rag.Catalog.load)


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _content_terms(text: str) -> list[str]:
    """Unigrams worth carrying. rag.tokenize also emits bigrams; not wanted here."""
    return [w for w in WORD_RE.findall(text.lower())
            if w not in rag.STOP and len(w) > 2]


def is_follow_up(message: str, history: list[dict]) -> bool:
    """Does this turn only make sense against the previous one?

    Three signals, any of which is enough: it is short, it opens like a
    continuation, or it refers to something by pronoun. All three are cheap and
    wrong in the same harmless direction -- carrying a few extra terms into a
    TF-IDF query costs nothing, while failing to carry them means "what if it's
    at 40 metres?" searches the corpus for the word "metres".
    """
    if not history:
        return False
    text = message.strip().lower()
    if len(text.split()) <= config.FOLLOW_UP_MAX_WORDS:
        return True
    if text.startswith(config.FOLLOW_UP_OPENERS):
        return True
    return any(re.search(rf"\b{re.escape(ref)}\b", text) for ref in config.FOLLOW_UP_REFERENTS)


def carried_terms(history: list[dict]) -> list[str]:
    """Topic words from earlier user turns, most recent first, deduplicated.

    Only user turns. Assistant answers are long, and folding them in lets the
    assistant's own wording steer the next retrieval instead of the operator's.
    """
    seen: list[str] = []
    for turn in reversed(history[-config.HISTORY_TURNS:]):
        if turn.get("role") != "user":
            continue
        for term in _content_terms(turn.get("content", "")):
            if term not in seen:
                seen.append(term)
            if len(seen) >= config.CARRY_TERMS:
                return seen
    return seen


def condense(message: str, history: list[dict], record: dict, mode: str) -> str:
    """The standalone query actually used for retrieval.

    The operator's words, plus the topic they are still talking about, plus the
    same task expansion the CLI uses. Deterministic: no model call, so a
    follow-up costs exactly one round trip like any other turn.
    """
    parts = [message.strip(), term_expansions(message)]
    if is_follow_up(message, history):
        parts.append(" ".join(carried_terms(history)))
    if record:
        parts.append(" ".join(str(record[f]) for f in ("label", "visual_description", "notes")
                              if record.get(f)))
        parts.append(class_synonyms(record.get("label")))
    parts.append(rag.QUERY_EXPANSION.get(mode, ""))
    return " ".join(p for p in parts if p.strip()).strip()


def term_expansions(message: str) -> str:
    """Corpus words for the operator's words. Deduplicated, order preserved."""
    out: list[str] = []
    for word in _content_terms(message):
        for extra in config.TERM_EXPANSIONS.get(word, "").split():
            if extra not in out:
                out.append(extra)
    return " ".join(out)


def class_synonyms(label: str | None) -> str:
    """Corpus words for a detector's class name. Longest match wins."""
    if not label:
        return ""
    name = _normalise(label)
    for phrase in sorted(config.CLASS_SYNONYMS, key=len, reverse=True):
        if phrase in name:
            return config.CLASS_SYNONYMS[phrase]
    return ""


def history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["CONVERSATION SO FAR (oldest first). Use it to resolve what the "
             "operator means by \"it\" or \"that\". It is context, not a source: "
             "it is never citable and never overrides the SOURCES block."]
    for turn in history[-config.HISTORY_TURNS:]:
        role = "OPERATOR" if turn.get("role") == "user" else "ASSISTANT"
        content = (turn.get("content") or "").strip()
        if len(content) > config.HISTORY_CHARS:
            content = content[:config.HISTORY_CHARS].rstrip() + " [...]"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------

def _unclassified(record: dict) -> bool:
    """Did the classifier actually identify this, or not?

    Low confidence counts as not. The classifier's uncertainty is the operator's
    uncertainty, and rounding it away is how a maybe becomes a fact.
    """
    if not record:
        return False
    label = str(record.get("label") or "").strip().lower()
    if label in config.UNKNOWN_LABELS:
        return True
    confidence = record.get("confidence")
    return isinstance(confidence, (int, float)) and confidence < config.ANOMALY_CONFIDENCE_FLOOR


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


def route_intent(message: str, record: dict) -> str:
    """Pick the mode so the operator never has to.

    Order is deliberate and is a safety property, not a style choice. An
    explicit request for a report wins outright. Anything that says the object
    is unknown routes to the anomaly path, and so does an unclassified record,
    both of them ahead of the explain keywords -- otherwise "what is this?"
    asked about an unidentified object would route to explain, and explain is
    the one mode that is allowed to name what something is.
    """
    text = message.strip().lower()

    if _matches_any(text, config.INTENT_KEYWORDS["report"]):
        return "report"
    if _matches_any(text, config.INTENT_KEYWORDS["anomaly"]):
        return "anomaly"
    if _unclassified(record):
        return "anomaly"
    if _matches_any(text, config.INTENT_KEYWORDS["explain"]):
        return "explain"
    if config.INTENT_LLM_FALLBACK:
        guessed = _llm_intent(message, bool(record))
        if guessed:
            return guessed
    return config.INTENT_WITH_RECORD if record else config.INTENT_WITHOUT_RECORD


_INTENT_SYSTEM = (
    "Classify the operator's message into exactly one of: question, explain, "
    "anomaly, report. Reply with that single word and nothing else."
)


def _llm_intent(message: str, has_record: bool) -> str | None:
    """Optional tiebreak. Any failure falls back to the rules, silently."""
    try:
        backend = rag.PROVIDERS[config.PROVIDER]()
        context = "A detection record is on screen." if has_record else "No detection record."
        reply = backend.complete(_INTENT_SYSTEM, f"{context}\n\nMESSAGE: {message}",
                                 config.MODEL or backend.default_model)
    except Exception:
        return None
    word = reply.strip().split()[0].lower().strip(".,\"'") if reply.strip() else ""
    return word if word in config.INTENT_TO_MODE else None


# ---------------------------------------------------------------------------
# Severity: looked up, never inferred
# ---------------------------------------------------------------------------

def severity_for(record: dict, anomalous: bool) -> str:
    """Severity from the catalog's hazard field, then the class table, else unknown.

    Never read out of the generated text. A risk level lifted from prose is an
    unsourced number wearing a label, which is the one thing this system exists
    not to produce.
    """
    if anomalous:
        return config.ANOMALY_SEVERITY

    name = _normalise(record.get("label") or "")
    if not name:
        return config.DEFAULT_SEVERITY

    catalog = get_catalog()
    if catalog is not None:
        for entry in catalog.entries:
            if name in (_normalise(entry.get("id", "")), _normalise(entry.get("name", ""))):
                hazard = _normalise(entry.get("hazard", ""))
                if hazard in config.HAZARD_SEVERITY:
                    return config.HAZARD_SEVERITY[hazard]

    for phrase in sorted(config.CLASS_SEVERITY, key=len, reverse=True):
        if phrase in name:
            return config.CLASS_SEVERITY[phrase]
    return config.DEFAULT_SEVERITY


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

def _pdf_url(meta: dict) -> str | None:
    """Link a citation to the publication it was written from, when there is one."""
    raw = meta.get("source_file")
    if not raw:
        return None
    first = str(raw).split(";")[0].strip()
    if not first:
        return None
    name = first.rsplit("/", 1)[-1]
    if not (config.SOURCES_DIR / name).exists():
        return None
    return f"{config.SOURCES_BASE_URL}/{name}"


def sources_from(hits: list[tuple[Any, float]]) -> list[dict]:
    """Turn the hits into citation records.

    Numbering is the whole point: `n` is assigned by enumerating this exact list
    in this exact order, which is the order rag.format_sources() used when it
    built the [S1], [S2] tags in the prompt. Reorder or filter between the two
    and every marker in the answer silently points at the wrong document.
    """
    out = []
    for n, (chunk, score) in enumerate(hits, start=1):
        meta = chunk.meta
        text = chunk.text
        out.append({
            "n": n,
            "id": chunk.id,
            "title": meta.get("title") or meta.get("doc_id") or chunk.id,
            "section": meta.get("section") or None,
            "snippet": text if len(text) <= config.SNIPPET_CHARS
                       else text[:config.SNIPPET_CHARS].rstrip() + " [...]",
            "authority": meta.get("authority"),
            "status": meta.get("status"),
            "doc_id": meta.get("doc_id"),
            "path": meta.get("path"),
            "score": round(float(score), 4),
            "pdf_url": _pdf_url(meta),
        })
    return out


def matches_from(matches: list[tuple[dict, float]]) -> list[dict]:
    return [{
        "rank": rank,
        "id": entry.get("id", ""),
        "name": entry.get("name", ""),
        "object_class": entry.get("class", ""),
        "hazard": entry.get("hazard", ""),
        "similarity": round(float(score), 4),
        "confirms": entry.get("confirms", ""),
        "rules_out": entry.get("rules_out", ""),
        "source": entry.get("source", ""),
        "status": entry.get("status", ""),
    } for rank, (entry, score) in enumerate(matches, start=1)]


def check_grounding(text: str, source_count: int) -> tuple[bool, bool]:
    """(grounded, refusal).

    Grounded is mechanical: at least one [Sn] marker, and every marker resolves
    to a source that was actually retrieved. A marker pointing past the end of
    the list means the model numbered something that was never given to it.

    Refusal is reported separately because it is the designed behaviour, not a
    failure. An answer is routinely both: cited throughout and still saying the
    standoff distance is not specified in the sources. The flag means "part of
    this answer is the assistant declining to fill a gap", which is exactly what
    an operator should see rendered differently from a confident procedure.
    """
    cited: set[int] = set()
    for group in re.findall(config.CITATION_GROUP_PATTERN, text):
        cited.update(int(n) for n in re.findall(config.CITATION_REF_PATTERN, group))
    grounded = bool(cited) and all(1 <= n <= source_count for n in cited)
    plain = re.sub(r"\s+", " ", re.sub(config.MARKDOWN_NOISE, "", text)).lower()
    refusal = any(re.search(p, plain) for p in config.REFUSAL_PATTERNS)
    return grounded, refusal


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------

def coverage_gap(record: dict) -> bool:
    """Does the corpus have a document about this class of object at all?

    The detector recognises aircraft, human remains, fish and ships. The corpus
    is about ordnance, wrecks, debris and unidentified objects. Those two lists
    only partly overlap, and where they do not the honest answer is that no
    reference covers it. Without this the model reaches for the nearest
    document that sounds close, which is how a body becomes a mine.
    """
    label = record.get("label")
    return bool(label) and config.CLASS_COVERAGE.get(label, True) is False


def build_task(mode: str, message: str, record: dict, matches_block: str,
               history: list[dict]) -> str:
    """Assemble the TASK half of the prompt. rag.TASKS is used as written."""
    blocks = []
    if coverage_gap(record):
        blocks.append(config.COVERAGE_GAP_NOTE.format(label=record["label"]))
    elif mode in ("explain", "report") and record.get("label") and not _unclassified(record):
        blocks.append(config.CLASSIFIED_NOTE.format(
            label=record["label"],
            confidence=record.get("confidence", "not stated")))
    conversation = history_block(history)
    if conversation:
        blocks.append(conversation)

    if mode == "ask":
        if record:
            blocks.append("DETECTION CURRENTLY ON SCREEN:\n" + rag.render_detection(record))
        blocks.append(rag.TASKS["ask"].format(question=message))

    elif history and mode in config.FOLLOW_UP_MODES:
        # Second turn onward on the same contact. The brief has already been
        # given; what is wanted now is an answer to what was just asked.
        context = ["OBSERVATION:\n" + rag.render_detection(record)]
        if matches_block:
            context.append(matches_block)
        blocks.append(config.FOLLOW_UP_TASK.format(
            question=message, context="\n\n".join(context)))

    elif mode == "anomaly":
        blocks.append(rag.TASKS["anomaly"].format(
            detection=rag.render_detection(record), matches=matches_block))
        blocks.append(f"The operator also asked: {message}")

    else:
        # report always produces the whole document, follow-up or not.
        blocks.append(rag.TASKS[mode].format(detection=rag.render_detection(record)))
        blocks.append(f"The operator also asked: {message}")

    return "\n\n".join(blocks)


def _prepare_turn(message: str, history: list[dict], detection: dict | None,
                  intent: str | None, k: int | None, per_doc: int | None,
                  provider: str | None, model: str | None) -> dict:
    """Everything that happens before the model is called.

    Routing, condensing, retrieval and catalog matching are identical whether
    the answer is returned whole or streamed, so they live here and both entry
    points use them. It runs eagerly rather than inside a generator, so a
    missing index fails as a proper HTTP error instead of as a frame arriving
    after the response has already started.
    """
    history = history or []
    record = {key: value for key, value in (detection or {}).items() if value is not None}
    provider = provider or config.PROVIDER
    model = model if model is not None else config.MODEL

    intent = intent or route_intent(message, record)
    mode = config.INTENT_TO_MODE[intent]
    anomalous = intent == "anomaly" or _unclassified(record)

    query = condense(message, history, record, mode)
    hits = _guard(get_retriever().search, query,
                  k=k or config.TOP_K, per_doc=per_doc or config.PER_DOC)

    matches: list[dict] = []
    matches_block = ""
    if mode == "anomaly" and hits:
        catalog = get_catalog()
        if catalog is None:
            matches_block = ("NEAREST KNOWN OBJECTS: unavailable. No catalog is indexed, "
                             "so no comparison was made. Do not speculate about identity.")
        else:
            ranked = _guard(catalog.match, record, top=config.CATALOG_TOP)
            matches_block = rag.format_matches(ranked, catalog.space)
            matches = matches_from(ranked)

    return {
        "meta": {
            "intent": intent,
            "object_class": record.get("label"),
            "confidence": record.get("confidence"),
            "is_anomaly": anomalous,
            "severity": severity_for(record, anomalous),
            "coverage_gap": coverage_gap(record),
            "query": query,
            "provider": provider,
            "model": model,
        },
        "hits": hits,
        "sources": sources_from(hits),
        "matches": matches,
        "matches_block": matches_block,
        "filled": build_task(mode, message, record, matches_block, history) if hits else "",
    }


def _finalise(work: dict, text: str) -> dict:
    grounded, refusal = check_grounding(text, len(work["sources"]))
    return {**work["meta"], "answer": text, "sources": work["sources"],
            "matches": work["matches"], "grounded": grounded, "refusal": refusal}


# Nothing retrieved means nothing to ground an answer in, so no model is called
# at all. Inventing a protocol here is the exact failure this system is built to
# avoid, and the cheapest way not to do it is not to ask.
def _no_sources(work: dict) -> dict:
    return {**work["meta"], "answer": config.NO_SOURCE_ANSWER, "sources": [],
            "matches": [], "grounded": False, "refusal": True}


def answer(message: str,
           history: list[dict] | None = None,
           detection: dict | None = None,
           *,
           intent: str | None = None,
           k: int | None = None,
           per_doc: int | None = None,
           provider: str | None = None,
           model: str | None = None) -> dict:
    """Answer one turn, whole. Returns the response contract as a plain dict."""
    work = _prepare_turn(message, history or [], detection, intent, k, per_doc,
                         provider, model)
    if not work["hits"]:
        return _no_sources(work)

    text = _guard(rag.generate, work["filled"], work["hits"],
                  work["meta"]["provider"], work["meta"]["model"])
    return _finalise(work, text)


def answer_stream(message: str,
                  history: list[dict] | None = None,
                  detection: dict | None = None,
                  *,
                  intent: str | None = None,
                  k: int | None = None,
                  per_doc: int | None = None,
                  provider: str | None = None,
                  model: str | None = None) -> Iterator[dict]:
    """Answer one turn, in frames. Same routing, same sources, same rules.

    Frame order is meta, sources, then deltas, then done. The citations go out
    before the first word because retrieval has already finished by then, so the
    panel is populated while the answer is still being written. `grounded` can
    only be computed once the whole answer exists, so it rides in the done
    frame and nowhere earlier.
    """
    work = _prepare_turn(message, history or [], detection, intent, k, per_doc,
                         provider, model)
    return _emit(work)


def _emit(work: dict) -> Iterator[dict]:
    yield {"type": "meta", **work["meta"], "matches": work["matches"]}
    if config.STREAM_SOURCES_EARLY:
        yield {"type": "sources", "sources": work["sources"]}

    if not work["hits"]:
        final = _no_sources(work)
        yield {"type": "delta", "text": final["answer"]}
        yield {"type": "done", **final}
        return

    pieces: list[str] = []
    try:
        for piece in rag.generate_stream(work["filled"], work["hits"],
                                         work["meta"]["provider"], work["meta"]["model"]):
            pieces.append(piece)
            yield {"type": "delta", "text": piece}
    except SystemExit as exc:
        # The response is already 200 by now, so a failure can only be reported
        # in the stream. Whatever text arrived before it is still grounded text
        # and is finalised rather than discarded.
        yield {"type": "error", "detail": str(exc)}
        if pieces:
            yield {"type": "done", **_finalise(work, "".join(pieces))}
        return

    yield {"type": "done", **_finalise(work, "".join(pieces))}
