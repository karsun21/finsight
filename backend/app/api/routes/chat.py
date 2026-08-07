from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.rag import llm
from app.rag.retrieval import aggregate_facts, semantic_search
from app.rag.router import route
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    decision = route(request.question)
    rows = aggregate_facts(db) if decision == "aggregate" else semantic_search(db, request.question)
    return ChatResponse(
        answer=llm.answer(request.question, rows),
        route=decision,
        rows_used=len(rows),
    )
