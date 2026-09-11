"""Request and response models.

This is the one place the loose dict the CLI passes around becomes a validated
object. Two things matter here and are easy to get wrong:

* `object_class` is the API's name for what rag.py calls `label`. The mapping
  happens on the way in, so the engine keeps seeing the vocabulary it was
  written for.
* Absent fields are dropped, never sent as null. rag.render_detection() writes
  every key of the record straight into the prompt, and report mode is under
  instruction to write "NOT PROVIDED" for anything missing. A key arriving as
  None would satisfy that instruction with the word "None" instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config  # noqa: F401  puts the repository root on sys.path

import rag

Role = Literal["user", "assistant"]
Intent = Literal["question", "explain", "anomaly", "report"]
Severity = Literal["low", "medium", "high", "unknown"]


class Turn(BaseModel):
    """One message of conversation history, as the client replays it."""

    role: Role
    content: str


class DetectionRecord(BaseModel):
    """What the detector saw. Every field optional; nothing is invented.

    Extra keys are allowed and passed through to the prompt untouched, so a
    detector that emits a field this schema has never heard of does not lose it.
    """

    model_config = ConfigDict(extra="allow")

    object_class: str | None = None
    label: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    bbox: list[float] | None = None
    depth_m: float | None = None
    timestamp: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    sensor: str | None = None
    platform: str | None = None
    notes: str | None = None
    visual_description: str | None = None
    embedding: list[float] | None = None
    detector_model: str | None = None
    detector_class: str | None = None
    second_opinion: str | None = None
    # Set when the detector's class was below the confidence this system
    # requires for that class. The original call is kept, never erased.
    downgraded_from: str | None = None

    @field_validator("bbox")
    @classmethod
    def _four_numbers(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and len(v) != 4:
            raise ValueError("bbox must be [x, y, w, h]")
        return v

    @property
    def resolved_class(self) -> str | None:
        return self.object_class or self.label

    def to_engine_record(self) -> dict[str, Any]:
        """The dict shape rag.py expects: `label`, no nulls, extras preserved."""
        record = self.model_dump(exclude_none=True)
        label = record.pop("object_class", None) or record.get("label")
        if label:
            record["label"] = label
        return record


class Source(BaseModel):
    """One retrieved chunk, rendered for the citation panel.

    `n` is the number the model cited as [Sn]. It is assigned by enumerating the
    exact hit list the prompt was built from, so the marker in the answer text
    always resolves to the right entry here.
    """

    n: int
    id: str
    title: str
    section: str | None = None
    snippet: str
    authority: str | None = None
    status: str | None = None
    doc_id: str | None = None
    path: str | None = None
    score: float
    pdf_url: str | None = None


class Match(BaseModel):
    """A nearest known object. A ranking hint, never an identification."""

    rank: int
    id: str
    name: str
    object_class: str
    hazard: str
    similarity: float
    confirms: str
    rules_out: str
    source: str
    status: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[Turn] = Field(default_factory=list)
    detection_record: DetectionRecord | None = None
    # Escape hatches for testing. Omitted, everything comes from config.py.
    intent: Intent | None = None
    provider: str | None = None
    model: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str | None) -> str | None:
        """Reject an unknown provider here rather than mid-stream.

        Once a streaming response has opened, the status line is already sent
        and a bad provider can only be reported as an error frame. Catching it
        at validation keeps it a plain 422.
        """
        if v is not None and v not in rag.PROVIDERS:
            raise ValueError(f"unknown provider; choose from {', '.join(sorted(rag.PROVIDERS))}")
        return v


class ChatResponse(BaseModel):
    answer: str
    intent: Intent
    object_class: str | None = None
    confidence: float | None = None
    is_anomaly: bool = False
    severity: Severity = "unknown"
    grounded: bool = False
    sources: list[Source] = Field(default_factory=list)

    # Additive, beyond the core contract.
    # `refusal` separates the two reasons an answer can be ungrounded: the
    # corpus genuinely has no authority for this (correct behaviour, worth
    # wording differently), versus retrieval simply missing.
    refusal: bool = False
    # True when the detector named a class the corpus has no document about.
    # Different from `refusal`: this is known before the model is called.
    coverage_gap: bool = False
    matches: list[Match] = Field(default_factory=list)
    query: str = ""
    provider: str = ""
    model: str = ""


class DetectResponse(BaseModel):
    """What came back from a tile.

    `stub` is not decoration. While it is true the records are synthetic, and
    every surface that shows them is expected to say so.
    """

    stub: bool
    models: list[str]
    filename: str
    bytes: int
    detections: list[DetectionRecord] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ready", "degraded"]
    corpus_loaded: bool
    documents: int
    chunks: int
    embedder: str
    index: str
    catalog_entries: int
    catalog_space: str | None = None
    provider: str
    model: str
    detector: Literal["stub", "loaded", "disabled"]
    detector_models: list[str] = Field(default_factory=list)
    # "connected", or the reason it is not. Absent storage costs history, not
    # the assistant, so this is reported rather than fatal.
    storage: str = "unconfigured"
    upload_enabled: bool
