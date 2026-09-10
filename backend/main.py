"""FastAPI app and routes. Thin by design.

Routes validate, delegate to chat.py, and serialise. Any behaviour beyond that
belongs in chat.py, and any constant belongs in config.py.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import chat, config, detect
from .schemas import ChatRequest, ChatResponse, HealthResponse

log = logging.getLogger("deepecho")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm both engines, in this order, and never the other way round.

    faiss and torch each ship their own copy of libomp. On macOS, whichever
    initialises second aborts the process with OMP Error #15. Loading the FAISS
    index first and the detector second is stable; the reverse kills the worker
    on the first request. The documented alternative, KMP_DUPLICATE_LIB_OK, is
    the vendor's own "unsafe, unsupported, may silently produce incorrect
    results" flag, and silently incorrect is the last thing this system wants.

    Warming here also moves index and weight loading off the first request,
    which used to cost several seconds.
    """
    try:
        chat.get_retriever()
        chat.get_catalog()
    except chat.EngineError as exc:
        log.warning("index not loaded at startup: %s", exc)

    if config.ENABLE_UPLOAD:
        loaded = detect.load_models()
        log.info("detector models loaded: %s", ", ".join(sorted(loaded)) or "none, using stub")

    yield


app = FastAPI(
    lifespan=lifespan,
    title="DeepEcho assistant",
    description="Grounded decision support for side-scan sonar detections.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The publications the corpus was written from, served read-only so a citation
# can open the document behind it. This is what makes a claim checkable rather
# than merely attributed.
if config.SOURCES_DIR.is_dir():
    app.mount(config.SOURCES_MOUNT, StaticFiles(directory=config.SOURCES_DIR), name="sources")


# The whole upload path is behind one flag. Off, the route does not exist at
# all, and /health says so, so the interface hides the control rather than
# offering something that will fail.
if config.ENABLE_UPLOAD:
    app.include_router(detect.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Is the index loaded and what is behind it? The UI shows this on boot."""
    detector = "disabled"
    detector_models: list[str] = []
    if config.ENABLE_UPLOAD:
        loaded = detect.load_models()
        detector_models = sorted(loaded)
        detector = "loaded" if loaded else "stub"

    try:
        retriever = chat.get_retriever()
    except chat.EngineError:
        return HealthResponse(
            status="degraded", corpus_loaded=False, documents=0, chunks=0,
            embedder="none", index="none", catalog_entries=0, catalog_space=None,
            provider=config.PROVIDER, model=config.MODEL or "provider default",
            detector=detector, upload_enabled=config.ENABLE_UPLOAD,
        )

    catalog = chat.get_catalog()
    embedder = getattr(retriever, "embedder", None)
    index = getattr(retriever, "index", None)

    return HealthResponse(
        status="ready",
        corpus_loaded=True,
        documents=len({c.meta.get("doc_id") for c in retriever.chunks}),
        chunks=len(retriever.chunks),
        embedder=getattr(embedder, "kind", retriever.mode),
        index=getattr(index, "kind", retriever.mode),
        catalog_entries=len(catalog.entries) if catalog else 0,
        catalog_space=catalog.space if catalog else None,
        provider=config.PROVIDER,
        model=config.MODEL or "provider default",
        detector=detector,
        detector_models=detector_models,
        upload_enabled=config.ENABLE_UPLOAD,
    )


@app.post("/chat", response_model=ChatResponse)
def post_chat(request: ChatRequest) -> ChatResponse:
    """One conversational turn, answered from the corpus and nothing else."""
    record = request.detection_record.to_engine_record() if request.detection_record else None
    try:
        result = chat.answer(
            request.message,
            history=[turn.model_dump() for turn in request.history],
            detection=record,
            intent=request.intent,
            provider=request.provider,
            model=request.model,
        )
    except chat.EngineError as exc:
        # Usually the upstream provider refusing a free-tier request rather than
        # anything wrong here, so the detail is logged and passed through intact.
        log.warning("engine error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(**result)


def _sse(frames: Iterator[dict]) -> Iterator[str]:
    """Serialise frames as server-sent events.

    The done frame is passed through ChatResponse on the way out. That is not
    ceremony: it makes the streamed final payload the same validated object the
    non-streaming route returns, so the two can never drift into disagreeing
    about what an answer looks like.
    """
    for frame in frames:
        if frame.get("type") == "done":
            payload = {"type": "done",
                       **ChatResponse(**{k: v for k, v in frame.items() if k != "type"}).model_dump()}
        else:
            payload = frame
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def post_chat_stream(request: ChatRequest) -> StreamingResponse:
    """The same turn as /chat, delivered as it is written.

    Frames arrive as `data: {json}` with a `type`: meta, then sources, then one
    delta per piece of text, then done. Retrieval has already finished when the
    first frame goes out, so the citation panel fills before the answer starts.
    `grounded` is only in the done frame, because it cannot be known until the
    whole answer exists.

    Anything that fails before the stream opens is a real HTTP error. Anything
    that fails after it is an error frame, because the status line has already
    been sent.
    """
    record = request.detection_record.to_engine_record() if request.detection_record else None
    try:
        frames = chat.answer_stream(
            request.message,
            history=[turn.model_dump() for turn in request.history],
            detection=record,
            intent=request.intent,
            provider=request.provider,
            model=request.model,
        )
    except chat.EngineError as exc:
        log.warning("engine error before stream: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return StreamingResponse(
        _sse(frames),
        media_type=config.STREAM_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache",
                 "Connection": "keep-alive",
                 # nginx and friends buffer by default, which silently turns a
                 # stream back into one slow response.
                 "X-Accel-Buffering": "no"},
    )
