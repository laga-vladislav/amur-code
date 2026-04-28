from fastapi import APIRouter, File, HTTPException, UploadFile

from ..ai_generation import AiApiError, build_presentation, create_outline, retry_outline
from ..models import PresentationDocument, TemplateDocument
from ..ai_models import (
    OutlineGenerationRequest,
    OutlineGenerationResponse,
    OutlineRetryRequest,
    PresentationBuildRequest,
)
from ..pptx_to_json.service import convert_pptx_to_template

from ..validation import validate_template
from ..storage import get_template, list_templates, save_template

router = APIRouter(prefix="/api/ai/generations", tags=["ai"])


@router.post("/import-pptx", response_model=TemplateDocument)
def import_pptx(file: UploadFile = File(...)):
    try:
        validate_template_ = convert_pptx_to_template(file)
    except AiApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    
    issues = validate_template(validate_template_)
    blocking = [i for i in issues if i.get("level") == "error"]
    if blocking:
        raise HTTPException(status_code=422, detail={"issues": blocking})
    return save_template(validate_template_)


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

