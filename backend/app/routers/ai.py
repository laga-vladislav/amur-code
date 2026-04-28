from fastapi import APIRouter, HTTPException

from ..ai_generation import AiApiError, build_presentation, create_outline, retry_outline
from ..ai_models import (
    OutlineGenerationRequest,
    OutlineGenerationResponse,
    OutlineRetryRequest,
    PresentationBuildRequest,
)
from ..models import PresentationDocument

router = APIRouter(prefix="/api/ai/generations", tags=["ai"])


@router.post("/outline", response_model=OutlineGenerationResponse)
def outline(payload: OutlineGenerationRequest):
    try:
        return create_outline(payload)
    except AiApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/{generation_id}/outline/retry", response_model=OutlineGenerationResponse)
def retry(generation_id: str, payload: OutlineRetryRequest):
    try:
        return retry_outline(generation_id, payload)
    except AiApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/{generation_id}/presentation", response_model=PresentationDocument)
def presentation(generation_id: str, payload: PresentationBuildRequest):
    try:
        return build_presentation(generation_id, payload)
    except AiApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

