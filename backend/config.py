"""Every knob in one file.

The rule for this module: if it is something you might want to change later --
a path, a threshold, a model name, a severity mapping, a phrase the operator
reads -- it lives here and nowhere else. Routes and engine code import from
here; they never hard-code a value of their own.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# rag.py sits at the repository root and is imported as a top-level module.
# Running `uvicorn backend.main:app` from the root already puts it on the path;
# this insert makes the backend importable from anywhere else too.

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KB_DIR = ROOT / "kb"
SOURCES_DIR = ROOT / "sources"

# Original publications are served read-only so a citation can open the PDF it
# was written from. Mount point, then the URL a client should use.
SOURCES_MOUNT = "/sources"
SOURCES_BASE_URL = os.environ.get("DEEPECHO_SOURCES_BASE_URL", SOURCES_MOUNT)

# --- Server ----------------------------------------------------------------

HOST = os.environ.get("DEEPECHO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEEPECHO_PORT", "8000"))

# The Vite dev server, on both spellings of localhost, plus the Vite preview
# port. Local only: nothing here is exposed to the internet.
CORS_ORIGINS = [
    o.strip() for o in
    os.environ.get(
        "DEEPECHO_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173").split(",")
    if o.strip()
]

# --- Generation ------------------------------------------------------------
# Reuse whatever the CLI is configured for. DEEPECHO_PROVIDER in .env selects
# gemini or groq; an empty model string means the provider's own default.

PROVIDER = os.environ.get("DEEPECHO_PROVIDER", "gemini")
MODEL = os.environ.get("DEEPECHO_MODEL", "")

# --- Retrieval -------------------------------------------------------------
# Mirrors the CLI defaults. Raise EF_SEARCH before anything else if recall ever
# drops below 1.000 in `python3 rag.py bench`.

# Raised from the CLI's 6 and 2 when the corpus grew from 7 documents to 9.
# The governing document for a question now has up to seven sections, and a cap
# of two meant the section that actually answered "who do I notify in India"
# lost to two broader sections of the same document. At 8 and 3 the answer is
# retrieved and the results still span five documents, so diversity holds.
TOP_K = int(os.environ.get("DEEPECHO_TOP_K", "8"))
PER_DOC = int(os.environ.get("DEEPECHO_PER_DOC", "3"))
EF_SEARCH = int(os.environ.get("DEEPECHO_EF_SEARCH", "64"))
CATALOG_TOP = int(os.environ.get("DEEPECHO_CATALOG_TOP", "3"))

# How much of a chunk the citation panel receives. Chunks are ~900 characters,
# so the default sends the whole thing and the panel shows real source text
# rather than a teaser.
SNIPPET_CHARS = int(os.environ.get("DEEPECHO_SNIPPET_CHARS", "900"))

# --- Conversation ----------------------------------------------------------

# Turns of history folded into the prompt. Older turns still shape retrieval
# through the condensed query, they just stop being quoted verbatim.
HISTORY_TURNS = 6

# A follow-up is condensed against earlier turns before it is used to search.
# Without this, "what if it's at 40 metres?" retrieves on the word "metres".
FOLLOW_UP_MAX_WORDS = 12
FOLLOW_UP_OPENERS = (
    "and", "but", "so", "then", "what if", "what about", "how about", "why",
    "why not", "ok", "okay", "also", "does that", "is that", "can it", "would it",
)
FOLLOW_UP_REFERENTS = (
    "it", "its", "it's", "that", "this", "they", "them", "those", "these",
    "the object", "the same", "the contact", "the target",
)
# Content words carried forward from earlier turns into the retrieval query.
CARRY_TERMS = 12

# Each quoted turn is clipped to this many characters before it goes into the
# prompt. An assistant answer can run several hundred words and six of them
# would crowd out the sources, which are the part that must not be crowded out.
HISTORY_CHARS = 700

# --- Intent routing --------------------------------------------------------
# Rules first: they are deterministic, free, and instant. Checked in this
# order, first hit wins. The LLM tiebreak below is off by default.

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Deliberately phrases, not the bare word "report". "who do I report a
    # mine to?" is a question about the reporting channel, not a request to
    # generate a document, and a bare keyword gets that backwards.
    "report": (
        "write a report", "write me a report", "write up", "write-up", "write it up",
        "incident report", "generate a report", "draft a report", "draft the report",
        "make a report", "make me a report", "give me a report", "need a report",
        "prepare a report", "produce a report", "file a report", "log this",
        "paperwork", "formal submission",
    ),
    "anomaly": (
        "unidentified", "unknown object", "unclassified", "anomaly", "anomalous",
        "cannot identify", "can't identify", "couldn't identify", "could not identify",
        "unable to identify", "not sure what", "no idea what", "no classification",
        "didn't classify", "did not classify", "failed to classify",
    ),
    "explain": (
        "explain", "what is this", "what is it", "what am i looking at",
        "brief me", "walk me through", "tell me about this", "what does this mean",
        "is it dangerous", "is this a hazard", "how risky",
    ),
}

# Fallback when no keyword matches: with a detection record in hand the operator
# is asking about that object; without one it is a general corpus question.
INTENT_WITH_RECORD = "explain"
INTENT_WITHOUT_RECORD = "question"

# One cheap LLM classification when the rules are ambiguous. Off by default:
# it adds a round trip to every turn and the rules cover the demo vocabulary.
INTENT_LLM_FALLBACK = os.environ.get("DEEPECHO_INTENT_LLM", "").lower() in {"1", "true", "yes"}

# The API speaks the product's vocabulary; rag.py speaks its own.
INTENT_TO_MODE = {
    "question": "ask",
    "explain": "explain",
    "anomaly": "anomaly",
    "report": "report",
}

# --- Follow-up turns -------------------------------------------------------
# The first turn on a detection gets the full brief from rag.TASKS. A follow-up
# must not: asked "could it be ordnance?", an assistant that re-runs the whole
# four-step anomaly template has not answered the question, it has repeated
# itself. This reframes the task so the operator's actual question leads.
#
# It relaxes nothing. The grounding and unidentified-object rules live in the
# system prompt and apply to every turn regardless of which template is used.
FOLLOW_UP_MODES = ("explain", "anomaly")

FOLLOW_UP_TASK = """The operator is continuing the same conversation. Answer THIS \
question, and only this question.

QUESTION: {question}

{context}

Answer directly. Do not restate the full brief, and do not repeat protocol steps \
already given earlier in the conversation unless the question asks for them. \
Every standing rule still applies: cite every claim, say plainly where the \
sources do not cover something, and for an unclassified object never state or \
imply an identity."""

# --- Anomaly detection -----------------------------------------------------

# A classified detection below this confidence is treated as unclassified. The
# classifier's own uncertainty is the operator's uncertainty.
ANOMALY_CONFIDENCE_FLOOR = float(os.environ.get("DEEPECHO_ANOMALY_FLOOR", "0.45"))

# Labels that mean "the classifier did not know".
UNKNOWN_LABELS = {
    "", "unknown", "unidentified", "unclassified", "anomaly", "other", "none", "null",
}

# --- Detector vocabulary ---------------------------------------------------
# A detector's class names are not the corpus's words. The corpus says "wreck";
# a YOLO class says "shipwreck", and TF-IDF scores that at exactly 0.000 against
# the wreck document while a mine document happens to score 0.095. So a detected
# class is expanded into the vocabulary the documents actually use.
#
# Query-side only. The corpus, the chunking and the index are untouched, and a
# term the index has never seen carries no weight, so a wrong guess here is
# inert rather than harmful.

CLASS_SYNONYMS: dict[str, str] = {
    "aircraft wreck": "aircraft wreckage notification custody",
    "human remains": "human remains respect disturbance grave",
    "fish or marine life": "natural",
    "shipwreck": "wreck vessel",
    "wreck": "wreck vessel",
    "naval mine": "mine ordnance munition",
    "sea mine": "mine ordnance munition",
    "moored mine": "mine moored ordnance munition",
    "bottom mine": "mine seabed ordnance munition",
    "mine": "mine ordnance munition",
    "unexploded ordnance": "unexploded ordnance munition",
    "uxo": "unexploded ordnance munition",
    "torpedo": "ordnance munition",
    "structural debris": "debris",
    "debris": "debris",
    "derelict fishing gear": "net entanglement debris",
    "fishing net": "net entanglement debris",
    "ghost net": "net entanglement debris",
    "net": "net entanglement",
    "pressure vessel": "cylinder drum unknown contents",
    "gas cylinder": "cylinder drum unknown contents",
    "cylinder": "cylinder drum unknown contents",
    "barrel": "drum cylinder unknown contents",
    "drum": "drum cylinder unknown contents",
    "pipeline": "pipeline",
    "boulder": "rock natural",
    "geological": "rock natural",
    "rock": "rock natural",
}

# --- Detector classes ------------------------------------------------------
# The two checkpoints emit these classes:
#
#   known.pt    (yolov8s, SCTD)          aircraft, human, ship
#   anomaly.pt  (yolov8n, sonar_detect)  aircraft, fish, other, shipwreck
#
# None of them is a mine, a UXO, a drum or a net, which is what most of the
# corpus is about. The map below translates a detector class into the label the
# knowledge base and the catalog use. Where no honest translation exists the
# class is marked as uncovered further down rather than being forced onto a
# document that does not describe it.

DETECTOR_CLASS_MAP: dict[str, str] = {
    "ship": "shipwreck",
    "shipwreck": "shipwreck",
    "aircraft": "aircraft wreck",
    "human": "human remains",
    "fish": "fish or marine life",
    # The detector's own word for "I saw something and cannot name it". It maps
    # to unknown so the assistant routes it down the unidentified-object path.
    "other": "unknown",
}

# Per-class confidence floors, above the detector's own global threshold.
#
# Measured across seven public side-scan tiles, six of them wrecks and none
# containing a human:
#
#   class      n   min    max    note
#   ship       8   0.318  0.829  the workhorse class, behaves well
#   other      3   0.359  0.545  the anomaly model's "I cannot name it"
#   shipwreck  1   0.843
#   human      1   0.463  fired on debris beside a wreck. A false positive.
#   aircraft   1   0.322  fired on a wreck. A false positive.
#
# Both false positives came from known.pt and both sat below 0.5, while the
# correct ship calls clustered higher. The floors below are set from that, and
# from consequence: "human remains" is the highest-consequence claim in the
# whole vocabulary, it is a legal and humanitarian assertion, and the corpus has
# no document supporting any procedure for it. It gets the strictest floor.
#
# One observation per false-positive class is not a fitted threshold. These are
# precautionary and are meant to be retuned against a labelled validation set.
CLASS_CONFIDENCE_FLOOR: dict[str, float] = {
    "human": 0.75,
    "aircraft": 0.60,
    "fish": 0.60,
    "ship": 0.25,
    "shipwreck": 0.25,
    "other": 0.25,
}

# A class below its floor is downgraded to this, never deleted. Dropping the box
# would hide a contact from the operator, which is worse than reporting it
# without a name. Downgrading keeps the contact and routes it to the
# unidentified-object protocol, which is the correct handling for something the
# detector saw and cannot confidently name.
#
# "Downgrade" names what happens to the CLAIM, not to the risk. An unidentified
# object is treated as more serious than a confirmed one, so withholding a class
# lowers the assessed risk only where that class outranked unidentified. A
# withheld "human" gets quieter; a withheld "aircraft wreck" gets louder. Both
# are the policy working, and the word misleads if read as de-escalation.
DOWNGRADE_LABEL = "unknown"
DOWNGRADE_NOTE = (
    "the {model} model called this '{cls}' at {confidence:.2f}, below the {floor:.2f} "
    "this system requires before reporting that class. Reported as unidentified "
    "instead. The original call is retained here and nothing was discarded."
)

# Which classes the corpus actually has a document for. A class marked False is
# not a failure of the detector; it is a gap in the references, and the answer
# must say so instead of reaching for the nearest document that sounds close.
CLASS_COVERAGE: dict[str, bool] = {
    "shipwreck": True,
    # Covered since kb/aircraft-wreck-underwater.md was added: the Indian AAIB
    # rules for notification and custody, plus the heritage and military cases.
    "aircraft wreck": True,
    # Covered since kb/human-remains-underwater.md was added. The document is
    # about obligations at such a site, not about identifying remains from a
    # sonar return, and it says so.
    "human remains": True,
    "fish or marine life": False,
    "unknown": True,
}

# Injected when the detector did classify the object and the corpus does cover
# that class. Without it the retrieved unidentified-object protocol dominates
# and the assistant opens with "unidentified object" for a contact its own
# detector called a shipwreck at 0.76, which reads as the system ignoring its
# own model. It adds no confidence the record does not already carry.
CLASSIFIED_NOTE = (
    "CLASSIFICATION: the detector classified this contact as '{label}' at a "
    "confidence of {confidence}. It is a classified detection, not an "
    "unclassified one, so answer about that class specifically and do not open "
    "by calling it unidentified. Say clearly that a classifier output is not a "
    "confirmed identification and state what would confirm or overturn it, "
    "using only the sources."
)

# Injected into the prompt when a detected class has no governing document.
COVERAGE_GAP_NOTE = (
    "CORPUS COVERAGE: the SOURCES below contain no document written about "
    "'{label}'. Say that plainly before anything else. Do not substitute a "
    "document about a different class of object, and do not give a procedure "
    "for one. Give only what the sources genuinely support for an object of "
    "unknown character, and name the gap."
)

# --- Operator vocabulary ---------------------------------------------------
# The index tokenises without stemming, so "notify" and "notification" are
# unrelated terms. An operator asking "who do I notify in India?" scored 0.000
# against the section that answers it, because that section says "notice",
# "notification" and names the authorities, and never says "notify".
#
# Same shape of fix as CLASS_SYNONYMS, and same limits: query-side only, and a
# term the index has never seen carries no weight, so a wrong entry is inert.
TERM_EXPANSIONS: dict[str, str] = {
    "notify": "notification notice authority",
    "notifying": "notification notice authority",
    "notified": "notification notice authority",
    "inform": "notification notice authority",
    "contact": "notification notice authority",
    "call": "notification notice",
    "tell": "notification notice",
    "standoff": "separation distance",
    "disarm": "render safe disposal",
    "defuse": "render safe disposal",
    "salvage": "recovery removal",
    "lift": "recovery removal",
    "raise": "recovery removal",
    "custody": "custody evidence preservation",
    "grave": "human remains venerated",
    "body": "human remains",
    "bodies": "human remains",
    "remains": "human remains venerated",
}

# --- Severity --------------------------------------------------------------
# Severity is looked up, never inferred from the generated text. Reading a risk
# level out of prose would be exactly the unsourced number this system refuses
# to produce.
#
# First table: the free-text `hazard` field already carried by every entry in
# catalog/objects.json, mapped onto the four API values. Keeping the catalog as
# the source of truth stops severity drifting away from the corpus.

HAZARD_SEVERITY: dict[str, str] = {
    "high": "high",
    "site hazard": "medium",
    "low to moderate": "low",
    "entanglement": "medium",
    "treat as unidentified": "unknown",
    "navigational only": "low",
}

# Second table: object classes a detector may emit that are not catalog ids.
# Matched on normalised substrings, longest first, so "naval mine" beats "mine".
CLASS_SEVERITY: dict[str, str] = {
    # The classes the two checkpoints actually emit.
    "shipwreck": "medium",
    "aircraft wreck": "medium",
    # Not a hazard to the vessel. It is a legal and humanitarian obligation, and
    # no source states a risk level, so "unknown" keeps both the caution and the
    # honesty. The interface renders unknown with the same weight as high.
    "human remains": "unknown",
    "fish or marine life": "low",
    "unexploded ordnance": "high",
    "naval mine": "high",
    "sea mine": "high",
    "moored mine": "high",
    "bottom mine": "high",
    "drifting mine": "high",
    "ordnance": "high",
    "torpedo": "high",
    "uxo": "high",
    "mine": "high",
    "pressure vessel": "unknown",
    "gas cylinder": "unknown",
    "drum": "unknown",
    "barrel": "unknown",
    "container": "unknown",
    "derelict fishing gear": "medium",
    "fishing net": "medium",
    "ghost net": "medium",
    "net": "medium",
    "cable": "medium",
    "shipwreck": "medium",
    "wreck": "medium",
    "aircraft": "medium",
    "structural debris": "low",
    "debris": "low",
    "tyre": "low",
    "rock": "low",
    "geological": "low",
    "boulder": "low",
}

# An unidentified object gets "unknown", never "high". Asserting a risk level
# for an object nobody has identified is itself an unsourced claim. The UI is
# expected to render "unknown" with the same caution as "high".
ANOMALY_SEVERITY = "unknown"
DEFAULT_SEVERITY = "unknown"

# --- Grounding -------------------------------------------------------------

# The prompt asks for [S1], but models render citations their own way. Groq
# emits fullwidth brackets, and both providers collapse runs into [S1, S3, S6].
# Matching only the literal [S1] scored a fully cited answer as ungrounded, so
# bracket groups are found first and source numbers read out of them. A group
# with no S-number in it, such as [Detection], is simply not a citation.
CITATION_GROUP_PATTERN = r"[\[\(\u3010]([^\[\]\(\)\u3010\u3011]{0,80})[\]\)\u3011]"
CITATION_REF_PATTERN = r"S\s*(\d+)"

# Saying "the sources do not cover this" is the correct, designed behaviour, so
# it is reported separately rather than as a grounding failure. An answer can be
# fully cited and still carry one of these, and usually does: this corpus leaves
# most numeric standoff distances unstated on purpose.
#
# Regex rather than fixed strings, because the phrasing varies with the provider
# and the wording. "The provided sources do not contain" and "not specified in
# the available sources" both mean the same thing and neither matches a literal.
REFUSAL_PATTERNS = (
    r"sources?\b[^.]{0,40}?\b(?:do|does)\s+not\s+(?:contain|cover|specify|state|include|provide|give|name|list)",
    r"not\s+(?:specified|stated|named|given|published|provided|defined)\s+in\s+(?:the\s+)?(?:\w+\s+){0,2}sources?",
    r"\bis\s+not\s+(?:specified|stated|named|given|published)\b",
    r"\bnot\s+specified\b",
    r"\bno\s+(?:\w+[\s-]+){0,3}(?:procedure|distance|figure|steps?|authority|source|guidance)\s+is\s+(?:published|specified|given|stated|named|provided)",
    r"\bno\s+authoritative\s+source",
    r"\bcontains?\s+no\s+(?:\w+[\s-]+){0,3}(?:procedure|steps?|guidance)",
    r"\bnot\s+(?:covered|addressed)\s+(?:by|in)\s+the\s+sources?",
)

# Markdown emphasis is stripped before the patterns run, so bold inside a phrase
# ("not **specified** in the sources") does not hide it.
MARKDOWN_NOISE = r"[*_`]+"

# Returned verbatim when retrieval finds nothing. No model call is made, because
# there is nothing to ground an answer in.
NO_SOURCE_ANSWER = (
    "The knowledge base has no document covering that, so I will not give you a "
    "procedure for it.\n\n"
    "Universal fallback, which applies regardless: do not approach, do not touch, "
    "do not attempt recovery, maintain separation, and report the contact to the "
    "responsible maritime authority for expert assessment."
)

# --- Streaming -------------------------------------------------------------
# Server-sent events. Every frame is `data: {json}` with a `type` field, so a
# plain fetch reader handles it and no EventSource-only GET route is needed.

STREAM_MEDIA_TYPE = "text/event-stream"

# Retrieval finishes before generation starts, so the citations are already
# known when the first word is sent. Emitting them up front fills the panel
# while the answer is still arriving. Turn this off to hold everything back
# until the final frame instead.
STREAM_SOURCES_EARLY = True

# Frame names, in the order a well-behaved stream emits them:
#   meta    intent, severity, is_anomaly and the catalog matches
#   sources the citations (early, unless STREAM_SOURCES_EARLY is off)
#   delta   one piece of answer text
#   done    the complete response, including grounded, which can only be
#           computed once the whole answer exists
#   error   the stream failed partway; whatever text arrived still stands
STREAM_FRAMES = ("meta", "sources", "delta", "done", "error")

# --- Detector (wired in a later step) --------------------------------------

ENABLE_UPLOAD = os.environ.get("DEEPECHO_ENABLE_UPLOAD", "").lower() in {"1", "true", "yes"}

# Two YOLOv8 checkpoints, not one. `known` names what it recognises; `anomaly`
# carries an explicit "other" class, which is the detector saying it saw
# something and could not name it. That is the signal the anomaly path exists
# for, so both are run and their boxes merged.
DETECTOR_MODELS: dict[str, Path] = {
    "known": ROOT / os.environ.get("DEEPECHO_MODEL_KNOWN", "models/known.pt"),
    "anomaly": ROOT / os.environ.get("DEEPECHO_MODEL_ANOMALY", "models/anomaly.pt"),
}
DETECTOR_CONFIDENCE = float(os.environ.get("DEEPECHO_DETECTOR_CONF", "0.25"))
DETECTOR_IMGSZ = int(os.environ.get("DEEPECHO_DETECTOR_IMGSZ", "640"))

# Two boxes overlapping by more than this are the same contact seen by both
# models. The higher-confidence one wins and the other is kept beside it as a
# second opinion rather than thrown away.
DETECTOR_MERGE_IOU = float(os.environ.get("DEEPECHO_DETECTOR_IOU", "0.5"))
DETECTOR_SENSOR = os.environ.get("DEEPECHO_DETECTOR_SENSOR", "side scan sonar, tile upload")
DETECTOR_PLATFORM = os.environ.get("DEEPECHO_DETECTOR_PLATFORM", "operator upload")

MAX_UPLOAD_BYTES = int(os.environ.get("DEEPECHO_MAX_UPLOAD_BYTES", str(16 * 1024 * 1024)))
ACCEPTED_UPLOAD_TYPES = ("image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp")

# What the stub returns until a trained model exists. Every field is marked, and
# `notes` says so in words, because a synthetic detection that reads like a real
# one is worse than no detection at all: the whole system downstream treats a
# record as evidence.
STUB_DETECTIONS: list[dict] = [
    {
        "object_class": "unknown",
        "confidence": 0.31,
        "bbox": [412.0, 233.0, 190.0, 64.0],
        "visual_description": "regular cylindrical return, roughly 2 m long, "
                              "partially buried, hard acoustic shadow",
        "notes": "SYNTHETIC placeholder detection from the stub detector. "
                 "Not produced by a trained model and not evidence of anything.",
    },
]
