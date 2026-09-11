# The DeepEcho backend.
#
# Two build profiles, chosen at build time, because torch is 583 MB on disk and
# 165 MB resident and most deployments do not need it:
#
#   --build-arg PROFILE=serve    the assistant, the corpus, and pre-generated
#                                surveys. No torch. Roughly 250 MB.
#   --build-arg PROFILE=full     adds the YOLOv8 checkpoints and survey
#                                processing. Roughly 1.2 GB.
#
# Serve is the default. On a 512 MB instance it is the only one that fits.

FROM python:3.13-slim AS base

ARG PROFILE=serve
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEEPECHO_HOST=0.0.0.0

WORKDIR /app

# libgomp is faiss's OpenMP runtime. On the full profile torch brings its own,
# which is why detector inference runs in a subprocess: the two cannot
# initialise in one address space. See backend/detector_worker.py.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-server.txt requirements-survey.txt requirements-detector.txt ./
RUN pip install -r requirements.txt -r requirements-server.txt -r requirements-survey.txt \
 && if [ "$PROFILE" = "full" ]; then pip install -r requirements-detector.txt; fi

# The corpus and its sources first: they change least, so the layer caches.
COPY rag.py ./
COPY kb/ ./kb/
COPY catalog/ ./catalog/
COPY sources/ ./sources/

# The index is built here rather than committed. A stale index that disagrees
# with the corpus is worse than no index, and building takes about a second.
RUN python rag.py index

COPY backend/ ./backend/
COPY data/ ./data/
COPY samples/ ./samples/
COPY hazard_*.py survey_preparation.py run_survey.py ./
COPY vendor/ ./vendor/

# The checkpoints are 27 MB and only the full profile can use them.
COPY models/ ./models/

EXPOSE 8000

# Render and most hosts inject PORT. Falling back to 8000 keeps `docker run`
# working with no environment at all.
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
