"""DeepEcho chat backend. A thin FastAPI wrapper over the existing RAG engine.

Nothing here re-implements retrieval, chunking, or the grounding prompt. The
engine in rag.py stays the single source of truth for what the assistant is
allowed to say; this package only makes it reachable over HTTP and gives the
answer back as structured data instead of printed text.
"""
