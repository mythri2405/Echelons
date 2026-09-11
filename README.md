# DeepEcho RAG assistant

The detection model answers *what's there*. This answers *what does it mean, and
what do I do*, grounded only in the curated corpus under `kb/`.

Two ways in. `rag.py` is the command-line engine and answers one question at a
time. The chat application in `backend/` and `frontend/` wraps the same engine
in a conversation, with follow-ups that keep context and citations an operator
can open. See [The chat application](#the-chat-application).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env               # then paste your keys into .env
.venv/bin/python rag.py index
```

Keys live in `.env`, which is gitignored. Only the provider you actually use
needs one.

```
GEMINI_API_KEY=...                 # free key: https://aistudio.google.com/apikey
GROQ_API_KEY=...                   # free key: https://console.groq.com/keys
DEEPECHO_PROVIDER=gemini           # gemini | groq
```

`.env` is read at startup by a few lines of stdlib, so there is no extra
dependency. A variable already exported in your shell wins over the file, which
makes a one-off override easy:

```bash
DEEPECHO_PROVIDER=groq python3 rag.py ask "..."
```

The whole pipeline runs on free tiers. Retrieval is local by default and costs
nothing at all; generation is Gemini Flash.

`--no-llm` on any command shows the retrieved sources without calling any model,
so the pipeline is demonstrable before a key exists. With no dependencies
installed at all, `index` falls back to exact sparse retrieval and still runs.

## Providers

The grounding rules live in one system prompt shared by every backend, so
switching provider changes the cost and the latency, never what the assistant is
allowed to say.

| `--provider` | Default model | Key |
|---|---|---|
| `gemini` (default) | `gemini-3.8-flash` | `GEMINI_API_KEY` |
| `groq` | `openai/gpt-oss-120b` | `GROQ_API_KEY` |

```bash
python3 rag.py ask "..." --provider groq
python3 rag.py ask "..." --model gemini-3.5-flash
export DEEPECHO_PROVIDER=groq      # or set the default for the session
```

Temperature is 0 everywhere. This is grounded extraction from retrieved text,
not composition, and sampling only invites drift away from the sources.

Gemini's free tier returns 503 under load, often enough to hit one mid-demo.
The client is configured with the SDK's own retry: five attempts, exponential
backoff with jitter, on 408, 429 and 5xx. If it still fails, `gemini-2.5-flash`
answers in about a second and is the fastest fallback.

Groq is the one to reach for if a Gemini safety filter trips on ordnance
content, and it is also the honest route to the sovereign and on-premises pitch,
since the same open weights can run on your own hardware later with no change
above this seam. List what your account can actually reach with
`client.models.list()`; the model literals baked into the SDK are not a
guarantee of access.

## Embeddings

Four embedders, and the index layer does not care which you use.

| `--embedder` | Cost | Notes |
|---|---|---|
| `tfidf-dense` (default) | free, local, offline | no fidelity loss, dimension is the vocabulary size |
| `sentence-transformers` | free, local, offline | 384-d semantic vectors, used automatically when installed |
| `gemini` | free tier, network | `gemini-embedding-001` at 768-d, a call per query |
| `random-projection` | free, local, offline | fixed dimensions, lossy, measured below |

`--embedder gemini` uses the retrieval task types the model expects, embedding
documents and queries differently, and renormalises because truncated Gemini
embeddings are not unit length. It is opt-in rather than automatic: making every
index build and every query hit a rate-limited network service is not a good
default for a demo you need to run on stage.

## The four functions

```bash
python3 rag.py explain --detection detection.json
python3 rag.py ask "what is the disposal procedure for unexploded ordnance?"
python3 rag.py anomaly --describe "cylindrical, 2 m, partially buried, hard shadow"
python3 rag.py report --detection detection.json
```

`search` and `match` expose the two retrieval halves on their own, and `bench`
measures the index:

```bash
python3 rag.py search "who do I report a mine to" -k 5
python3 rag.py match --describe "large structure, debris scatter" --top 3
python3 rag.py bench --ef 8 16 32 64 128
```

## Retrieval

`kb/*.md` are split on `##` headings and packed into ~900 character chunks with
overlap. Each chunk becomes a TF-IDF vector over unigrams and bigrams, L2
normalised, and is stored in a **FAISS HNSW index** under inner product, which on
unit vectors is cosine. HNSW is a navigable small-world graph: a query descends
coarse layers and refines, so cost grows with log(n) instead of n. The same code
path serves this 37-chunk corpus and a corpus of millions.

Build parameters are `M=32`, `efConstruction=200`; `efSearch` defaults to 64 and
is the query-time recall dial (`--ef-search`).

### Layers, and what is swappable

| Layer | Default | Alternatives |
|---|---|---|
| Embedder | `tfidf-dense` | `sentence-transformers`, `random-projection` |
| Index | `faiss-hnsw` | `exact` (brute force), sparse stdlib fallback |
| Metric | cosine | pearson, set at index time |

Nothing above couples to anything below it. Installing `sentence-transformers`
switches the embedder to 384-dimensional semantic vectors automatically, and the
index code does not change.

### HNSW is approximate, so it is measured

`bench` runs the query set against both the HNSW index and exact brute-force
search over the identical vectors, and reports how often the approximate index
returns what exact search returns.

```
 efSearch   recall@k   top-1 agree
        8      1.000       10/10
       64      1.000       10/10
```

Recall is 1.000 at every `efSearch` on this corpus, which is what a graph index
does when the corpus is smaller than the candidate list. The number matters as
the corpus grows. On a safety corpus a missed neighbour can be the standoff
distance document, so raise `efSearch` until recall is 1.000 and keep it there.

### On the default embedder

`tfidf-dense` uses the vocabulary size as the dimension, so cosine in the index
is exactly the cosine of the sparse representation and nothing is traded away for
speed. `random-projection` gives fixed dimensions instead, and it is lossy.
Measured on this corpus against the exact ranking:

| dim | agreement@6 | top-1 |
|---|---|---|
| 512 | 0.567 | 8/10 |
| 1024 | 0.633 | 9/10 |
| 2048 | 0.700 | 10/10 |

That is why it is opt-in. Past roughly tens of thousands of vocabulary terms,
move to `sentence-transformers` rather than to projection.

### Cosine and Pearson

Cosine is the default and the right choice: vectors are L2 normalised, so the
inner product is the cosine and length has no vote. Pearson is cosine on
mean-centred vectors, so `index --metric pearson` centres each vector before
normalising and the whole index becomes a Pearson index. Metric is a property of
the index, not of the query. On this corpus the two rank almost identically,
which is expected for sparse TF-IDF where the mean sits near zero. Pearson earns
its keep against dense embeddings carrying a per-dimension bias.

### Diversity

At most two chunks per source document are kept, after over-fetching four times
`k`, so one verbose document cannot crowd out the protocol or reporting document
that the answer also needs.

## Anomalies

An unclassified detection has no label, so there is no protocol to look up by
name. The anomaly path makes three separate moves and keeps them separate.

**Retrieve the generic protocol.** The unknown-object procedure comes out of
`kb/` like any other answer: treat as potentially hazardous, hold separation, do
not disturb, report, log for expert review.

**Rank the nearest known objects.** `catalog/objects.json` holds known object
classes. Each carries a descriptor, the hazard class, what would confirm it,
what would rule it out, and the `kb/` document that governs it, so a match keeps
the citation chain intact. Matching runs in one of two spaces:

- **embedding** when the detection record carries an `embedding` array and every
  catalog entry carries one too. This is the real path, and it uses your
  detection model's own space.
- **descriptor** otherwise, matching the operator's description against the
  entry text. Weaker, but it runs today without a trained embedding head.

The two are never mixed. A detection embedding against a descriptor-only catalog
is an error, not a silent fallback, and a catalog where only some entries carry
embeddings is rejected at index time.

**Generate an honest answer.** The model gets the protocol and the ranked
matches, and is held to saying "unidentified" first, presenting matches only as
ranked possibilities with their discriminators, and naming the escalation.

### The scores are not percentages

A cosine similarity of 0.78 is not "78% similar", and rendering it as a
percentage makes a ranking read as a confidence to an operator on deck. Matches
are printed as similarity scores with a rank, labelled in the prompt as "NOT a
probability, NOT a confidence, NOT an identification", and the model is
forbidden from converting one into a percentage or treating a higher score as
making an identity more likely true.

Similarity ranks candidates against each other. It says nothing about whether
the right answer is in the catalog at all.

## The guardrails

The system prompt is the safety-critical part of this system.

- Answer only from the `SOURCES` block. The model's own recollection is
  inadmissible.
- Cite `[S1]` after every distance, timing, procedure step and authority name.
- If the sources do not cover it, say so, then give only the universal fallback:
  do not approach, do not touch, do not recover, hold separation, report.
- Never invent a standoff distance, a disposal step, or a contact detail. A
  missing number is "not specified in the sources".
- Flag any citation whose document is marked `status: PLACEHOLDER`.

For an unclassified object, four more:

- Never state or imply an identity. Say "unidentified" first.
- Present nearest matches as possibilities, always with what would confirm and
  what would rule each one out. Never "this is a" or "likely a".
- Never convert a similarity score into a probability, a confidence, or a
  percentage.
- Escalate to a qualified human expert, and say the object stays unidentified
  until that expert rules.

No document in `kb/` is a placeholder any more. All seven are written from real
publications, carry `status: verified`, and name the file in `sources/` they came
from. The rule stays in the prompt because the index still warns on a
`PLACEHOLDER` document and the assistant must flag one if it ever appears.

What the corpus deliberately still lacks is numbers. Most of these publications
do not state a universal standoff distance, and none of them names an Indian
authority for an ordnance report. Ask for either and the assistant says so
rather than inventing one. That is the system working, not a gap to paper over.

## Adding real sources

Drop a `.md` or `.txt` file in `kb/` with front matter, then re-index.

```yaml
---
title: Underwater UXO Handling
authority: <issuing body>
source_url: <url>
source_file: sources/<the file it was written from>
doc_type: safety procedure
status: verified
retrieved: 2026-09-10
---
```

Put the publication itself in `sources/` and add a row to `sources/PROVENANCE.md`.
Nothing in `sources/` is indexed; it is evidence, and it is what lets any quote
in an answer be traced back to a real document. The chat interface links it: a
citation whose document names a `source_file` opens the original PDF.

`python3 rag.py index` prints a warning listing every document still marked
`PLACEHOLDER`.

Catalog entries in `catalog/objects.json` follow the same discipline. Every
entry cites the `kb/` document that governs it and carries its own `status`, and
`length_m` is deliberately `null` throughout: a fabricated size range would be
read as evidence by an operator.

## The chat application

The CLI answers one question and exits. The chat application is the same engine
with a conversation around it: one input box, follow-ups that keep context, and
citations an operator can open.

```
backend/     FastAPI. Wraps rag.py. Never edits it.
  config.py         every knob: paths, retrieval, severity, detector classes
  schemas.py        pydantic request and response models
  chat.py           the seam: routing, history, retrieval, citations, grounding
  detect.py         sonar tile in, detection records out
  detector_worker.py the models, in their own process
  main.py           routes only
frontend/    One Vite app: the dashboard, with the assistant as a page in it.
  src/pages/Assistant.jsx    the route
  src/assistant/             the chat, self-contained
    components/              ChatWindow, MessageBubble, CitationPanel, Composer
    config/theme.ts          every colour, font and spacing value
    config/copy.ts           every string the operator reads
    config/settings.ts       API base URL and feature flags
    lib/api.ts               the only module that talks to the backend
    assistant.css            scoped under .dq-assistant
eval/        forty cases and the runner
```

The chat stylesheet is scoped under a single root class. The dashboard and the
chat both defined `.status-dot` and both defined `.app`, and an unscoped merge
would have quietly restyled the sidebar.

Retrieval, chunking, the system prompt and the corpus are untouched by all of
it. `rag.py` gained one thing: a `stream()` method beside each provider's
`complete()`, so an answer can be delivered as it is written.

### Running it

Three commands, all local.

```bash
.venv/bin/pip install -r requirements-server.txt
DEEPECHO_ENABLE_UPLOAD=1 .venv/bin/python -m uvicorn backend.main:app --port 8000

cd frontend && npm install && npm run dev      # http://localhost:5173
```

The assistant is the last item in the sidebar. Do not run `npm run build` while
`npm run dev` is running; they share a build directory and the dev server starts
returning 500.

Set `DEEPECHO_PROVIDER=groq` in `.env` for the demo. Gemini's free tier returns
503 under load often enough to hit one mid-answer, and Groq answers in about a
second.

### Setting up on another machine

A fresh clone is missing three things by design: the vector index, the API keys,
and the detector dependencies. All three are one command each.

```bash
git clone https://github.com/mythri2405/Echelons.git
cd Echelons
git checkout dashboard

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-server.txt
.venv/bin/pip install -r requirements-detector.txt   # only for tile upload

cp .env.example .env        # then put a key in it, see below
.venv/bin/python rag.py index

cd frontend && npm install && cd ..
```

Then two terminals:

```bash
DEEPECHO_ENABLE_UPLOAD=1 .venv/bin/python -m uvicorn backend.main:app --port 8000
cd frontend && npm run dev
```

Open `http://localhost:5173` and pick Assistant in the sidebar.

**The index is not in the repo.** `index.faiss`, `index.json` and `vectors.npy`
are built from `kb/` and are gitignored, because a stale committed index that
disagrees with the corpus is worse than no index. `rag.py index` rebuilds them
in about a second and prints what it indexed.

**Keys are not in the repo either.** `.env` is gitignored and always should be.
A free Groq key from https://console.groq.com/keys is enough, and Groq is the
one to use: it answers in about a second where Gemini's free tier returns 503
under load. Put `GROQ_API_KEY=...` and `DEEPECHO_PROVIDER=groq` in `.env`.

**The models and the sources are in the repo.** `models/known.pt` and
`models/anomaly.pt` are committed, and so are the publications in `sources/`, so
citations resolve to real files on a fresh clone.

**Without a key**, retrieval still works and can be demonstrated:
`python3 rag.py search "who do I report a mine to" -k 5` needs no network at all.

### Endpoints

| Route | What it does |
|---|---|
| `POST /chat` | One turn, answered whole |
| `POST /chat/stream` | The same turn, streamed as server-sent events |
| `POST /detect` | A sonar tile in, detection records out. Behind `DEEPECHO_ENABLE_UPLOAD` |
| `GET /health` | Index status, corpus size, provider, detector state |
| `GET /sources/...` | The original publications, read-only |

The streaming route emits `data: {json}` frames typed `meta`, `sources`,
`delta`, `done` and `error`. Retrieval finishes before generation starts, so the
citations go out before the first word and the panel fills while the answer is
still arriving. `grounded` can only be known once the whole answer exists, so it
rides in the `done` frame alone. That frame is validated against the same model
`POST /chat` returns, so the two cannot drift apart.

### What the interface has to show

Four states must never look like a confident answer, and each is rendered
differently from one.

- **Ungrounded.** The answer carries no citation that resolves. Marked
  unverified, with an instruction to confirm manually.
- **Partly outside the references.** The answer is cited but declines to fill a
  gap. Marked as such, because a missing standoff distance is unavailable, not
  omitted.
- **Unidentified object.** Nearest known objects are listed as possibilities
  with what would confirm and what would rule each one out, under a heading
  saying nothing below identifies anything. Similarity is shown as a score and
  never as a percentage.
- **Placeholder detection.** While the detector is a stub, every record it
  produces is labelled synthetic wherever it appears.

### Evaluation

Forty cases in `eval/cases.jsonl`, run by `eval/run.py`, checked mechanically.

```bash
python3 eval/run.py                      # in-process, no server needed
python3 eval/run.py --url http://127.0.0.1:8000
python3 eval/run.py --category refusal --verbose
python3 eval/run.py --repeat 3           # generation is not deterministic
```

Nothing in the suite asks a model to grade another model. A suite whose purpose
is evidence cannot rest on the same machinery it is testing, so every check is a
regex, a set membership, or a string lookup against the text that was actually
retrieved. The exit code is 1 on any failure, so it can gate a commit.

| Category | Cases | What it holds the assistant to |
|---|---|---|
| refusal | 8 | The corpus is silent, so the answer says so and gives only the fallback |
| grounding | 7 | The corpus does cover it, and the answer cites it |
| anomaly | 6 | Never an identity, never a similarity rendered as a percentage |
| routing | 6 | The four intents resolve without the operator picking one |
| coverage | 4 | A class with no governing document is flagged, not answered around |
| authority | 5 | A body is named only where a source connects it to that hazard |
| detector | 4 | Severity is looked up from the table, not read out of prose |

Two checks run on every case whether it asks for them or not.

**Citations resolve.** Every `[Sn]` in the answer must point at a source that was
really retrieved. A marker past the end of the list means the model numbered
something it was never given.

**No invented numbers.** Every quantity carrying a unit is extracted from the
answer and must appear in the retrieved text. A standoff distance, a depth or a
delay that no source stated is the exact failure this system exists to prevent,
and it is detectable without judgement. Citation markers and ordered-list
numbering are stripped first, or `[S3]` and `3.` become quantities.

The suite earned its place on its first run by finding a real bug: the engine
read `label` while the API spoke `object_class`, and the mapping lived only in
the HTTP layer. Anything calling the engine directly had its classified contacts
silently treated as anomalies. `_prepare_turn` now normalises the field itself.

### The detector

Two YOLOv8 checkpoints, both run over every tile.

| Checkpoint | Base | Dataset | Classes |
|---|---|---|---|
| `models/known.pt` | yolov8s | SCTD | aircraft, human, ship |
| `models/anomaly.pt` | yolov8n | sonar_detect | aircraft, fish, other, shipwreck |

Both, because they disagree usefully. The anomaly model has an explicit `other`
class, which is the detector saying it saw something and could not name it, and
that is the signal the unidentified-object path exists for. Where both find the
same box, the more confident call leads and the other is recorded beside it as a
second opinion, because a disagreement between two models is information an
operator should see rather than a tie for the software to settle quietly.

Inference runs in a subprocess. faiss and torch each bundle their own libomp,
and on macOS the second to initialise aborts the process. The documented
workaround is a flag whose own description says it may silently produce
incorrect results, which is not a trade this system should make, so the two
libraries are kept in separate processes instead. `backend/detector_worker.py`
loads the weights once and stays up.

### Per-class confidence floors

Measured across seven public side-scan tiles, six of them wrecks and none of
them containing a human:

| class | n | min | max | note |
|---|---|---|---|---|
| ship | 8 | 0.318 | 0.829 | the workhorse class, behaves well |
| other | 3 | 0.359 | 0.545 | the anomaly model's "I cannot name it" |
| shipwreck | 1 | 0.843 | 0.843 | |
| human | 1 | 0.463 | 0.463 | fired on debris beside a wreck, a false positive |
| aircraft | 1 | 0.322 | 0.322 | fired on a wreck, a false positive |

Both false positives came from `known.pt` and both sat below 0.5, while the
correct ship calls clustered higher. `CLASS_CONFIDENCE_FLOOR` in
`backend/config.py` sets a floor per class from that, and from consequence:
"human remains" is the highest-consequence claim in the vocabulary, it is a
legal and humanitarian assertion, and no document in the corpus supports any
procedure for it. It gets the strictest floor at 0.75.

A class below its floor is **downgraded, never dropped**. Deleting the box would
hide a contact from the operator, which is worse than reporting one without a
name. The contact becomes `unknown`, routes to the unidentified-object protocol,
and carries a `downgraded_from` note recording exactly what the model called it
and why that call was not taken at face value. Nothing is hidden and nothing is
asserted.

One observation per false-positive class is not a fitted threshold. These are
precautionary, and the right next step is to retune them against a labelled
validation set.

### The vocabulary gap

The detector recognises aircraft, human remains, fish and ships. The corpus is
about ordnance, wrecks, debris and unidentified objects. Those lists only
partly overlap, and pretending otherwise is how a body becomes a mine.

`CLASS_COVERAGE` in `backend/config.py` records which detected classes the
corpus actually has a document for. A class marked `False` puts a note in the
prompt telling the model to say plainly that no reference covers it, and sets
`coverage_gap` on the response so the interface can show it. Only `shipwreck`
and the unknown class are covered today. An aircraft wreck, a fish shoal and
human remains are not, and the assistant says so instead of answering from a
document about something else.

Filling that gap is a corpus job, not a code job. The most valuable additions
are a document on wrecks containing human remains and the reporting obligation
that attaches to them, and an Indian procedure for reporting suspected ordnance.
