"""AI generation orchestration for outlines, decks, and generated assets."""

from __future__ import annotations

import base64
import json
import os
import random
import time
import uuid
from typing import Any
from urllib import error, parse, request

from pydantic import ValidationError

from .ai_models import (
    GenerationBasis,
    ImagePolicy,
    LayoutGenerationBasis,
    OutlineGenerationRequest,
    OutlineGenerationResponse,
    OutlineRetryRequest,
    OutlineSlide,
    PresentationBuildRequest,
    PresentationOutline,
    StyleGenerationBasis,
)
from .models import (
    Asset,
    BackgroundColor,
    LayoutDocument,
    PresentationDocument,
    PresentationTheme,
    SlideDocument,
    SlideSize,
    TemplateDocument,
    ThemeColors,
    ThemeFonts,
)
from .storage import (
    get_generation,
    get_template,
    save_generation,
    save_presentation,
    store_asset,
)


class AiApiError(Exception):
    def __init__(self, status_code: int, detail: str | dict[str, Any]):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


ALLOWED_SLIDE_TYPES = {"title", "text", "image", "bullets", "conclusion"}
MOCK_IMAGE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)

STYLE_THEMES: dict[str, PresentationTheme] = {
    "business": PresentationTheme(
        fonts=ThemeFonts(heading="Inter", body="Inter"),
        colors=ThemeColors(
            background="#0C1016",
            text="#F4F5F7",
            primary="#FFB547",
            secondary="#5A8FF0",
            accent="#38D2A4",
        ),
    ),
    "friendly": PresentationTheme(
        fonts=ThemeFonts(heading="Inter", body="Inter"),
        colors=ThemeColors(
            background="#F7F2EA",
            text="#20242C",
            primary="#2F80ED",
            secondary="#F2994A",
            accent="#27AE60",
        ),
    ),
    "academic": PresentationTheme(
        fonts=ThemeFonts(heading="Inter", body="Inter"),
        colors=ThemeColors(
            background="#F8FAFC",
            text="#102033",
            primary="#1D4ED8",
            secondary="#475569",
            accent="#0F766E",
        ),
    ),
    "promo": PresentationTheme(
        fonts=ThemeFonts(heading="Inter", body="Inter"),
        colors=ThemeColors(
            background="#101014",
            text="#FFFFFF",
            primary="#EF5D4A",
            secondary="#FFB547",
            accent="#5A8FF0",
        ),
    ),
}


def create_outline(payload: OutlineGenerationRequest) -> OutlineGenerationResponse:
    _validate_basis(payload.basis)
    outline = _mock_outline(payload) if _mock_enabled() else _generate_outline(payload)
    generation_id = _new_id("gen")
    _save_record(
        generation_id,
        {
            "id": generation_id,
            "status": "outline_ready",
            "request": payload.model_dump(mode="json"),
            "outline": outline.model_dump(mode="json"),
            "createdAt": _now_ms(),
            "updatedAt": _now_ms(),
        },
    )
    return OutlineGenerationResponse(generationId=generation_id, outline=outline)


def retry_outline(generation_id: str, payload: OutlineRetryRequest) -> OutlineGenerationResponse:
    record = _load_record(generation_id)
    source_request = OutlineGenerationRequest.model_validate(record["request"])
    _validate_basis(source_request.basis)

    if _mock_enabled():
        outline = _mock_outline(source_request, feedback=payload.feedback)
    else:
        llm_payload = {
            "task": "presentation_outline_retry",
            "prompt": source_request.prompt,
            "slideCount": source_request.slideCount,
            "language": source_request.language,
            "basis": source_request.basis.model_dump(mode="json"),
            "previousOutline": payload.outline.model_dump(mode="json"),
            "feedback": payload.feedback,
            "requiredJsonSchema": _outline_schema_hint(),
        }
        raw = _call_qwen_json(llm_payload, max_new_tokens=1536)
        outline = _normalize_outline(raw, source_request)

    record["status"] = "outline_ready"
    record["outline"] = outline.model_dump(mode="json")
    record["updatedAt"] = _now_ms()
    _save_record(generation_id, record)
    return OutlineGenerationResponse(generationId=generation_id, outline=outline)


def build_presentation(
    generation_id: str, payload: PresentationBuildRequest
) -> PresentationDocument:
    record = _load_record(generation_id)
    if record.get("status") != "outline_ready":
        raise AiApiError(409, "Generation is not ready for presentation build")

    source_request = OutlineGenerationRequest.model_validate(record["request"])
    _validate_basis(source_request.basis)

    outline = payload.outline
    if not outline.slides:
        raise AiApiError(422, "Approved outline must contain at least one slide")

    content_outline = (
        _mock_content(source_request, outline)
        if _mock_enabled()
        else _generate_slide_content(source_request, outline)
    )
    doc = _build_document(source_request.basis, content_outline, payload.imagePolicy)
    saved = save_presentation(doc)

    record["status"] = "presentation_ready"
    record["approvedOutline"] = outline.model_dump(mode="json")
    record["contentOutline"] = content_outline.model_dump(mode="json")
    record["presentationId"] = saved.id
    record["updatedAt"] = _now_ms()
    _save_record(generation_id, record)
    return saved


def _generate_outline(payload: OutlineGenerationRequest) -> PresentationOutline:
    llm_payload = {
        "task": "presentation_outline",
        "prompt": payload.prompt,
        "slideCount": payload.slideCount,
        "language": payload.language,
        "basis": payload.basis.model_dump(mode="json"),
        "requiredJsonSchema": _outline_schema_hint(),
    }
    raw = _call_qwen_json(llm_payload, max_new_tokens=1536)
    return _normalize_outline(raw, payload)


def _generate_slide_content(
    source_request: OutlineGenerationRequest, outline: PresentationOutline
) -> PresentationOutline:
    llm_payload = {
        "task": "presentation_slide_content",
        "prompt": source_request.prompt,
        "outline": outline.model_dump(mode="json"),
        "basis": source_request.basis.model_dump(mode="json"),
        "requiredJsonSchema": _outline_schema_hint(include_content=True),
    }
    raw = _call_qwen_json(llm_payload, max_new_tokens=4096)
    return _normalize_outline(raw, source_request, fallback_outline=outline)


def _call_qwen_json(payload: dict[str, Any], max_new_tokens: int) -> dict[str, Any]:
    token = os.getenv("RT_AI_TOKEN")
    if not token:
        raise AiApiError(401, "RT_AI_TOKEN is not configured")

    base_url = os.getenv("RT_AI_BASE_URL", "https://ai.rt.ru/api/1.0").rstrip("/")
    model = os.getenv("RT_AI_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    timeout = float(os.getenv("RT_AI_TIMEOUT_SECONDS", "90"))
    user_text = _qwen_user_text(payload)
    body = {
        "uuid": str(uuid.uuid4()),
        "chat": {
            "model": model,
            "user_message": user_text,
            "contents": [{"type": "text", "text": user_text}],
            "message_template": "<s>{role}\n{content}</s>",
            "response_template": "<s>bot\n",
            "system_prompt": (
                "Ты проектируешь презентации. Возвращай строго валидный JSON "
                "без Markdown и без пояснений."
            ),
            "max_new_tokens": max_new_tokens,
            "no_repeat_ngram_size": 15,
            "repetition_penalty": 1.1,
            "temperature": 0.2,
            "top_k": 40,
            "top_p": 0.9,
            "chat_history": [],
        },
    }
    data = _request_json(
        f"{base_url}/llama/chat",
        "POST",
        token,
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout,
    )
    try:
        content = data[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiApiError(502, "Qwen response does not contain message.content") from exc
    return _extract_json(content)


def _qwen_user_text(payload: dict[str, Any]) -> str:
    return (
        "Сгенерируй данные для презентации по входному JSON.\n"
        "Ответ должен быть только валидным JSON-объектом без Markdown, без комментариев "
        "и без текста вокруг JSON.\n"
        "Формат ответа:\n"
        "{\n"
        '  "title": "string",\n'
        '  "audience": "string",\n'
        '  "goal": "string",\n'
        '  "slides": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "title": "string",\n'
        '      "purpose": "string",\n'
        '      "keyPoints": ["string"],\n'
        '      "visualIntent": "string",\n'
        '      "needsImage": false,\n'
        '      "slideType": "title|text|image|bullets|conclusion",\n'
        '      "imagePrompt": "string",\n'
        '      "speakerNotes": "string"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Входной JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _request_json(
    url: str, method: str, token: str, data: bytes | None, timeout: float
) -> Any:
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        external_detail = _read_http_error(exc)
        if exc.code in {401, 403}:
            raise AiApiError(
                401,
                f"External AI service rejected RT_AI_TOKEN: {external_detail}",
            ) from exc
        raise AiApiError(
            502,
            f"External AI service returned HTTP {exc.code}: {external_detail}",
        ) from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AiApiError(502, f"External AI service request failed: {exc}") from exc


def _read_http_error(exc: error.HTTPError) -> str:
    try:
        body = exc.read(2000).decode("utf-8", "replace").strip()
    except Exception:
        body = ""
    return body or exc.reason or "empty response body"


def _extract_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    for start, end in (("{", "}"), ("[", "]")):
        first = text.find(start)
        last = text.rfind(end)
        if first >= 0 and last > first:
            fragment = text[first : last + 1]
            try:
                parsed = json.loads(fragment)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                return {"slides": parsed}
            if isinstance(parsed, dict):
                return parsed

    raise AiApiError(502, "Qwen response is not valid JSON")


def _normalize_outline(
    raw: dict[str, Any],
    source_request: OutlineGenerationRequest,
    fallback_outline: PresentationOutline | None = None,
) -> PresentationOutline:
    data = raw.get("outline", raw)
    if isinstance(data, list):
        data = {"slides": data}
    if not isinstance(data, dict):
        raise AiApiError(502, "Qwen JSON must be an object")

    fallback_title = (
        fallback_outline.title
        if fallback_outline
        else _title_from_prompt(source_request.prompt)
    )
    slides_raw = data.get("slides") or []
    if not isinstance(slides_raw, list) or not slides_raw:
        raise AiApiError(502, "Qwen JSON must contain a non-empty slides array")

    slides: list[OutlineSlide] = []
    previous = {s.order: s for s in (fallback_outline.slides if fallback_outline else [])}
    for idx, item in enumerate(slides_raw, start=1):
        if not isinstance(item, dict):
            item = {"title": str(item)}
        fallback_slide = previous.get(idx)
        key_points = _coerce_str_list(
            item.get("keyPoints")
            or item.get("points")
            or item.get("bullets")
            or item.get(" тезисы")
            or (fallback_slide.keyPoints if fallback_slide else [])
        )
        slide_type = item.get("slideType") or (fallback_slide.slideType if fallback_slide else None)
        if slide_type not in ALLOWED_SLIDE_TYPES:
            slide_type = None
        visual_intent = (
            item.get("visualIntent")
            or item.get("visual")
            or item.get("imageDescription")
            or (fallback_slide.visualIntent if fallback_slide else None)
        )
        image_prompt = (
            item.get("imagePrompt")
            or item.get("visualPrompt")
            or visual_intent
            or (fallback_slide.imagePrompt if fallback_slide else None)
        )
        needs_image = bool(
            item.get("needsImage")
            or item.get("needImage")
            or slide_type == "image"
            or (fallback_slide.needsImage if fallback_slide else False)
        )
        slides.append(
            OutlineSlide(
                order=int(item.get("order") or idx),
                title=str(item.get("title") or (fallback_slide.title if fallback_slide else f"Слайд {idx}")),
                purpose=str(item.get("purpose") or (fallback_slide.purpose if fallback_slide else "")),
                keyPoints=key_points,
                visualIntent=str(visual_intent) if visual_intent else None,
                needsImage=needs_image,
                slideType=slide_type,
                imagePrompt=str(image_prompt) if image_prompt else None,
                speakerNotes=item.get("speakerNotes") or item.get("notes"),
            )
        )

    return PresentationOutline(
        title=str(data.get("title") or fallback_title),
        audience=data.get("audience") or (fallback_outline.audience if fallback_outline else None),
        goal=data.get("goal") or (fallback_outline.goal if fallback_outline else None),
        slides=slides[: source_request.slideCount],
    )


def _build_document(
    basis: GenerationBasis, outline: PresentationOutline, image_policy: ImagePolicy
) -> PresentationDocument:
    assets_by_order: dict[int, Asset] = {}
    if image_policy.generateImages:
        for slide in outline.slides:
            if slide.needsImage or slide.slideType == "image":
                image_prompt = slide.imagePrompt or slide.visualIntent
                if not image_prompt:
                    image_prompt = f"{outline.title}. {slide.title}. {slide.purpose}"
                assets_by_order[slide.order] = _generate_image_asset(
                    image_prompt, image_policy.imageType
                )

    if isinstance(basis, LayoutGenerationBasis):
        template = get_template(basis.templateId)
        if not template:
            raise AiApiError(422, f"Template not found: {basis.templateId}")
        doc = _build_layout_document(template, basis, outline, assets_by_order)
    elif isinstance(basis, StyleGenerationBasis):
        doc = _build_style_document(basis, outline, assets_by_order)
    else:
        raise AiApiError(422, "Unsupported generation basis")

    doc.meta = {
        **(doc.meta or {}),
        "generation": {
            "basis": basis.model_dump(mode="json"),
            "outline": outline.model_dump(mode="json"),
            "imagePolicy": image_policy.model_dump(mode="json"),
        },
    }
    return doc


def _build_layout_document(
    template: TemplateDocument,
    basis: LayoutGenerationBasis,
    outline: PresentationOutline,
    assets_by_order: dict[int, Asset],
) -> PresentationDocument:
    doc = PresentationDocument(
        schemaVersion="1.0.0",
        documentType="presentation",
        id=_new_id("pres"),
        name=outline.title,
        templateId=template.id,
        slideSize=template.slideSize.model_copy(deep=True),
        theme=template.theme.model_copy(deep=True),
        slides=[],
        assets=[a.model_copy(deep=True) for a in template.assets],
    )
    doc.assets.extend(assets_by_order.values())
    for idx, slide_outline in enumerate(outline.slides):
        layout = _pick_layout(template, basis, slide_outline, idx, len(outline.slides))
        doc.slides.append(
            _slide_from_layout(layout, slide_outline, outline, assets_by_order.get(slide_outline.order))
        )
    return doc


def _pick_layout(
    template: TemplateDocument,
    basis: LayoutGenerationBasis,
    slide: OutlineSlide,
    idx: int,
    total: int,
) -> LayoutDocument:
    layouts = template.layouts
    if basis.layoutIds:
        allowed = set(basis.layoutIds)
        filtered = [layout for layout in layouts if layout.id in allowed]
        if filtered:
            layouts = filtered

    wanted = slide.slideType
    if not wanted:
        if idx == 0:
            wanted = "title"
        elif idx == total - 1:
            wanted = "conclusion"
        elif slide.needsImage:
            wanted = "image"
        elif len(slide.keyPoints) >= 2:
            wanted = "bullets"
        else:
            wanted = "text"

    return (
        next((layout for layout in layouts if layout.slideType == wanted), None)
        or next((layout for layout in layouts if layout.slideType == "text"), None)
        or layouts[0]
    )


def _slide_from_layout(
    layout: LayoutDocument,
    slide_outline: OutlineSlide,
    outline: PresentationOutline,
    asset: Asset | None,
) -> SlideDocument:
    elements: list[dict[str, Any]] = []
    for element in layout.elements:
        payload = element.model_dump(mode="json", by_alias=True)
        source_id = payload["id"]
        payload["id"] = _new_id("el")
        behavior = payload.get("contentBehavior") or {}
        fill_role = behavior.get("fillRole") or payload.get("role")
        if behavior.get("kind") == "placeholder":
            payload["sourcePlaceholderId"] = source_id
            payload["contentBehavior"] = {
                "kind": "generated",
                "readonly": False,
                "fillRole": fill_role,
            }
        if payload["type"] == "text":
            payload["text"] = _text_for_role(fill_role, slide_outline, outline)
        elif payload["type"] == "image":
            if asset:
                payload["assetId"] = asset.id
                payload["generation"] = {
                    "prompt": slide_outline.imagePrompt
                    or slide_outline.visualIntent
                    or slide_outline.title,
                    "model": "stable-diffusion",
                }
            else:
                payload["placeholder"] = slide_outline.visualIntent or "Изображение"
        elements.append(payload)

    return SlideDocument.model_validate(
        {
            "id": _new_id("slide"),
            "name": slide_outline.title,
            "slideType": slide_outline.slideType or layout.slideType,
            "layoutId": layout.id,
            "background": layout.background.model_dump(mode="json", by_alias=True),
            "elements": elements,
            "notes": slide_outline.speakerNotes or slide_outline.purpose,
            "meta": {"outlineOrder": slide_outline.order},
        }
    )


def _build_style_document(
    basis: StyleGenerationBasis,
    outline: PresentationOutline,
    assets_by_order: dict[int, Asset],
) -> PresentationDocument:
    theme = STYLE_THEMES[basis.styleId].model_copy(deep=True)
    doc = PresentationDocument(
        schemaVersion="1.0.0",
        documentType="presentation",
        id=_new_id("pres"),
        name=outline.title,
        slideSize=SlideSize(widthEmu=12192000, heightEmu=6858000, ratio="16:9"),
        theme=theme,
        slides=[],
        assets=list(assets_by_order.values()),
    )
    for idx, slide_outline in enumerate(outline.slides):
        doc.slides.append(
            _style_slide(slide_outline, outline, theme, assets_by_order.get(slide_outline.order), idx)
        )
    return doc


def _style_slide(
    slide_outline: OutlineSlide,
    outline: PresentationOutline,
    theme: PresentationTheme,
    asset: Asset | None,
    idx: int,
) -> SlideDocument:
    is_title = idx == 0 or slide_outline.slideType == "title"
    is_image = bool(asset)
    background = BackgroundColor(type="color", value=theme.colors.background)
    elements: list[dict[str, Any]] = []

    if is_title:
        elements.append(
            _text_element(
                "title",
                outline.title,
                914400,
                2200000,
                10363200,
                1200000,
                56,
                700,
                theme.colors.text,
            )
        )
        subtitle = slide_outline.purpose or outline.goal or outline.audience or ""
        if subtitle:
            elements.append(
                _text_element(
                    "subtitle",
                    subtitle,
                    914400,
                    3600000,
                    10363200,
                    800000,
                    28,
                    400,
                    theme.colors.secondary,
                )
            )
    else:
        title_w = 5200000 if is_image else 10363200
        body_w = 5200000 if is_image else 10363200
        elements.append(
            _text_element(
                "title",
                slide_outline.title,
                914400,
                700000,
                title_w,
                800000,
                38,
                700,
                theme.colors.text,
            )
        )
        role = "bulletList" if slide_outline.keyPoints else "body"
        elements.append(
            _text_element(
                role,
                _text_for_role(role, slide_outline, outline),
                914400,
                1750000,
                body_w,
                4300000,
                24,
                400,
                theme.colors.text,
            )
        )
        if is_image and asset:
            elements.append(
                _image_element(
                    asset,
                    6700000,
                    1450000,
                    4572000,
                    4300000,
                    slide_outline.imagePrompt or slide_outline.visualIntent or slide_outline.title,
                )
            )

    return SlideDocument(
        id=_new_id("slide"),
        name=slide_outline.title,
        slideType=slide_outline.slideType or ("title" if is_title else "image" if is_image else "bullets"),
        background=background,
        elements=elements,
        notes=slide_outline.speakerNotes or slide_outline.purpose,
        meta={"outlineOrder": slide_outline.order},
    )


def _text_element(
    role: str,
    text: str,
    x: int,
    y: int,
    w: int,
    h: int,
    font_size: int,
    font_weight: int,
    color: str,
) -> dict[str, Any]:
    return {
        "id": _new_id("el"),
        "type": "text",
        "role": role,
        "contentBehavior": {"kind": "generated", "readonly": False, "fillRole": role},
        "text": text,
        "frame": {"xEmu": x, "yEmu": y, "wEmu": w, "hEmu": h, "rotate": 0},
        "style": {
            "fontFamily": "Inter",
            "fontSize": font_size,
            "fontWeight": font_weight,
            "color": color,
            "align": "left",
            "lineHeight": 1.35,
        },
        "zIndex": 10,
        "locked": False,
        "visible": True,
    }


def _image_element(
    asset: Asset, x: int, y: int, w: int, h: int, prompt: str
) -> dict[str, Any]:
    return {
        "id": _new_id("el"),
        "type": "image",
        "role": "image",
        "contentBehavior": {"kind": "generated", "readonly": False, "fillRole": "image"},
        "assetId": asset.id,
        "fit": "cover",
        "frame": {"xEmu": x, "yEmu": y, "wEmu": w, "hEmu": h, "rotate": 0},
        "generation": {"prompt": prompt, "model": "stable-diffusion"},
        "zIndex": 9,
        "locked": False,
        "visible": True,
    }


def _generate_image_asset(prompt: str, image_type: str) -> Asset:
    if _mock_enabled():
        asset = store_asset(MOCK_IMAGE_PNG, f"generated_{uuid.uuid4().hex[:8]}.png", "image/png")
        asset.meta = {"mock": True, "prompt": prompt}
        return asset

    token = os.getenv("RT_AI_TOKEN")
    if not token:
        raise AiApiError(401, "RT_AI_TOKEN is not configured")

    base_url = os.getenv("RT_AI_BASE_URL", "https://ai.rt.ru/api/1.0").rstrip("/")
    timeout = float(os.getenv("RT_AI_TIMEOUT_SECONDS", "90"))
    body = {
        "uuid": str(uuid.uuid4()),
        "sdImage": {
            "request": prompt,
            "seed": random.randint(1, 2147483647),
            "translate": False,
        },
    }
    response_payload = _request_json(
        f"{base_url}/sd/img",
        "POST",
        token,
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout,
    )
    try:
        message_id = response_payload[0]["message"]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiApiError(502, "Stable Diffusion response does not contain message.id") from exc

    query = parse.urlencode(
        {"id": message_id, "serviceType": "sd", "imageType": image_type}
    )
    download_url = f"{base_url}/download?{query}"
    req = request.Request(
        download_url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            file_bytes = resp.read()
    except error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise AiApiError(401, "External AI service rejected RT_AI_TOKEN") from exc
        raise AiApiError(502, f"Image download returned HTTP {exc.code}") from exc
    except (error.URLError, TimeoutError) as exc:
        raise AiApiError(502, f"Image download failed: {exc}") from exc

    mime_type = "image/jpeg" if image_type == "jpeg" else f"image/{image_type}"
    asset = store_asset(file_bytes, f"generated_{message_id}.{image_type}", mime_type)
    asset.meta = {"prompt": prompt, "externalMessageId": message_id}
    return asset


def _text_for_role(
    role: str | None, slide: OutlineSlide, outline: PresentationOutline
) -> str:
    if role == "title":
        return slide.title
    if role == "subtitle":
        return slide.purpose or outline.goal or outline.audience or ""
    if role == "bulletList":
        points = slide.keyPoints or ([slide.purpose] if slide.purpose else [])
        return "\n".join(f"• {point}" for point in points)
    if role == "caption":
        return slide.visualIntent or ""
    if role == "slideNumber":
        return str(slide.order)

    parts: list[str] = []
    if slide.purpose:
        parts.append(slide.purpose)
    if slide.keyPoints:
        parts.extend(f"• {point}" for point in slide.keyPoints)
    return "\n".join(parts) or slide.title


def _validate_basis(basis: GenerationBasis) -> None:
    if isinstance(basis, LayoutGenerationBasis):
        template = get_template(basis.templateId)
        if not template:
            raise AiApiError(422, f"Template not found: {basis.templateId}")
        if basis.layoutIds:
            known = {layout.id for layout in template.layouts}
            unknown = [layout_id for layout_id in basis.layoutIds if layout_id not in known]
            if unknown:
                raise AiApiError(422, {"unknownLayoutIds": unknown})
    elif isinstance(basis, StyleGenerationBasis):
        if basis.styleId not in STYLE_THEMES:
            raise AiApiError(422, f"Unknown styleId: {basis.styleId}")


def _mock_outline(
    payload: OutlineGenerationRequest, feedback: str | None = None
) -> PresentationOutline:
    title = _title_from_prompt(payload.prompt)
    slides: list[OutlineSlide] = []
    for idx in range(1, payload.slideCount + 1):
        if idx == 1:
            slide_type = "title"
            slide_title = title
            points = ["Контекст", "Цель презентации"]
        elif idx == payload.slideCount:
            slide_type = "conclusion"
            slide_title = "Итоги и следующий шаг"
            points = ["Главный вывод", "Решение или действие"]
        elif idx % 4 == 0:
            slide_type = "image"
            slide_title = f"Визуальный акцент {idx}"
            points = ["Ключевой образ", "Поддерживающий тезис"]
        else:
            slide_type = "bullets"
            slide_title = f"Раздел {idx}"
            points = ["Тезис 1", "Тезис 2", "Тезис 3"]
        if feedback:
            points.append(f"Учтено: {feedback[:80]}")
        slides.append(
            OutlineSlide(
                order=idx,
                title=slide_title,
                purpose=f"Раскрыть часть темы: {title}",
                keyPoints=points,
                visualIntent=f"Чистая презентационная графика по теме: {slide_title}",
                needsImage=slide_type == "image",
                slideType=slide_type,
            )
        )
    return PresentationOutline(
        title=title,
        audience="Целевая аудитория из запроса",
        goal="Собрать понятную и редактируемую презентацию",
        slides=slides,
    )


def _mock_content(
    source_request: OutlineGenerationRequest, outline: PresentationOutline
) -> PresentationOutline:
    slides: list[OutlineSlide] = []
    for slide in outline.slides:
        points = slide.keyPoints or [
            f"Связать с запросом: {source_request.prompt[:80]}",
            "Сформулировать вывод коротко",
        ]
        slides.append(slide.model_copy(update={"keyPoints": points}))
    return outline.model_copy(update={"slides": slides})


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" -•") for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _outline_schema_hint(include_content: bool = False) -> dict[str, Any]:
    slide_content_note = (
        "keyPoints should contain final slide text, not only headings"
        if include_content
        else "keyPoints should contain short outline bullets"
    )
    return {
        "title": "string",
        "audience": "string",
        "goal": "string",
        "slides": [
            {
                "order": "number",
                "title": "string",
                "purpose": "string",
                "keyPoints": slide_content_note,
                "visualIntent": "string",
                "needsImage": "boolean",
                "slideType": "title|text|image|bullets|conclusion",
                "imagePrompt": "string",
                "speakerNotes": "string",
            }
        ],
    }


def _title_from_prompt(prompt: str) -> str:
    first_line = prompt.splitlines()[0].strip()
    title = first_line.split(".")[0].strip()
    return title[:80] or "Новая презентация"


def _mock_enabled() -> bool:
    return os.getenv("RT_AI_MOCK", "").lower() in {"1", "true", "yes", "on"}


def _load_record(generation_id: str) -> dict[str, Any]:
    record = get_generation(generation_id)
    if not record:
        raise AiApiError(404, "Generation not found")
    return record


def _save_record(generation_id: str, record: dict[str, Any]) -> None:
    try:
        save_generation(generation_id, record)
    except ValidationError as exc:
        raise AiApiError(500, str(exc)) from exc


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_ms() -> int:
    return int(time.time() * 1000)
