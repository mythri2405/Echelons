"""The DeepEcho API.

One application over two engines. The shell owns uploads, persistence and
history through Supabase; the engines own detection and grounded answering. The
routers below are the seam and nothing crosses it except data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import chat, config, detect
from ..schemas import HealthResponse
from .routes import stats
from .routes.detection import router as detection_router
from .routes.hazard import router as hazard_router
from .routes.history import router as history_router
from .routes.rag import router as rag_router
from .routes.survey import router as survey_router
from .supabase_client import supabase_status

log = logging.getLogger("deepecho")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the index and the detector, in that order and never the other way.

    faiss and torch each ship their own copy of libomp, and on macOS whichever
    initialises second aborts the process. Detector inference lives in a
    subprocess for exactly that reason, so the two never share an address space.
    Warming here also moves index and weight loading off the first request.
    """
    try:
        chat.get_retriever()
        chat.get_catalog()
    except chat.EngineError as exc:
        log.warning("index not loaded at startup: %s", exc)

    if config.ENABLE_UPLOAD:
        loaded = detect.load_models()
        log.info("detector: %s", ", ".join(sorted(loaded)) or "none, using stub")

    log.info("supabase: %s", supabase_status())
    yield


app = FastAPI(
    lifespan=lifespan,
    title="deepEcho",
    description="AI-powered underwater sonar detection and grounded decision support",
    version="1.0.0",
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


@app.get("/")
def home():
    return {
        "message": "deepEcho backend is running",
        "assistant": "/chat, /chat/stream, /rag/query",
        "detection": "/detect",
        "survey": "/hazard/map, /history, /stats",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Is the index loaded, what is behind it, and is storage reachable."""
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
            detector=detector, detector_models=detector_models,
            upload_enabled=config.ENABLE_UPLOAD, storage=supabase_status(),
        )

    catalog = chat.get_catalog()
    return HealthResponse(
        status="ready",
        corpus_loaded=True,
        documents=len({c.meta.get("doc_id") for c in retriever.chunks}),
        chunks=len(retriever.chunks),
        embedder=getattr(getattr(retriever, "embedder", None), "kind", retriever.mode),
        index=getattr(getattr(retriever, "index", None), "kind", retriever.mode),
        catalog_entries=len(catalog.entries) if catalog else 0,
        catalog_space=catalog.space if catalog else None,
        provider=config.PROVIDER,
        model=config.MODEL or "provider default",
        detector=detector,
        detector_models=detector_models,
        upload_enabled=config.ENABLE_UPLOAD,
        storage=supabase_status(),
    )


app.include_router(rag_router)
app.include_router(detection_router)
app.include_router(history_router)
app.include_router(hazard_router)
app.include_router(stats.router)

# The survey hazard map. Reads pre-generated surveys off disk, so it needs no
# database, no detector and no key, and cannot fail at startup.
#
# Note for whoever tidies this up: /hazard/map above answers a similar-sounding
# question from Supabase scan rows, with severity from a detection count. This
# router answers it from a processed survey, with severity from class weight
# times confidence. They are two different models of the same idea and the
# project should eventually keep one. Nothing here touches the other.
app.include_router(survey_router)
