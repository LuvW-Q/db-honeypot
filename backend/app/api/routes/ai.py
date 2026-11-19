"""AI 只读辅助接口（可选增强，默认关闭）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import RODB
from app.api.errors import ApiError
from app.services.ai_assistant import AiDisabledError, answer_question

router = APIRouter()


class AiAskRequest(BaseModel):
    """AI 提问请求。"""

    question: str = Field(min_length=1, max_length=200, description="自然语言只读问题")


@router.post("/ai/ask")
async def ask(payload: AiAskRequest, db: RODB) -> dict:
    """回答自然语言只读问题；功能关闭时返回 503。"""
    try:
        return await answer_question(db, payload.question)
    except AiDisabledError as exc:
        raise ApiError("SERVICE_UNAVAILABLE", str(exc)) from exc
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc)) from exc
