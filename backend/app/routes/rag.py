from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class RAGQuery(BaseModel):
    query: str


@router.post("/rag/query")
def rag_query(request: RAGQuery):
    return {
        "query": request.query,
        "status": "not_implemented",
        "message": "RAG pipeline is not integrated yet."
    }