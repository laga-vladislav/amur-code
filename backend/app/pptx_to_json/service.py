from __future__ import annotations

import uuid
from typing import Any

from fastapi import UploadFile

from ..ai_generation import AiApiError
from ..models import (
    PresentationTheme,
    TemplateDocument,
    ThemeColors,
    ThemeFonts,
)
from .normalizer import normalize_with_qwen
from .parser import parse_pptx
from .schemas import RawPresentation

DEFAULT_THEME = PresentationTheme(
    fonts=ThemeFonts(heading="Inter", body="Inter"),
    colors=ThemeColors(
        background="#FFFFFF",
        text="#111827",
        primary="#2563EB",
        secondary="#64748B",
        accent="#F97316",
    ),
)


def convert_pptx_to_template(source: str | UploadFile | bytes | bytearray) -> TemplateDocument:
    raw_data = parse_pptx(source)
    RawPresentation.model_validate(raw_data)

    template_data: dict[str, Any]
    try:
        template_data = normalize_with_qwen(raw_data)
    except AiApiError:
        template_data = _generate_template_fallback(raw_data)


    return TemplateDocument.model_validate(template_data)


def _generate_template_fallback(raw_data: dict[str, Any]) -> dict[str, Any]:
    slide_size = raw_data["slideSize"]
    slides = raw_data.get("slides") or []
    total_slides = len(slides)
    layouts: list[dict[str, Any]] = []

    for slide in slides:
        slide_type = _guess_slide_type(slide, total_slides)
        elements = []
        for element in slide["elements"]:
            frame = {
                "xEmu": element["bbox"]["x"],
                "yEmu": element["bbox"]["y"],
                "wEmu": element["bbox"]["width"],
                "hEmu": element["bbox"]["height"],
                "rotate": 0,
            }
            if element["type"] == "image":
                elements.append(
                    {
                        "id": f"img_{uuid.uuid4().hex[:8]}",
                        "type": "image",
                        "contentBehavior": {"kind": "static", "readonly": True},
                        "frame": frame,
                        "assetId": None,
                        "fit": "contain",
                        "alt": element.get("text") or "Imported image",
                    }
                )
                continue

            text_value = element.get("text") or ""
            style = element.get("style", {}) or {}
            font_size = max(style.get("fontSize") or 14, 14)
            elements.append(
                {
                    "id": f"txt_{uuid.uuid4().hex[:8]}",
                    "type": "text",
                    "contentBehavior": {"kind": "static", "readonly": True},
                    "frame": frame,
                    "text": text_value,
                    "style": {
                        "fontFamily": style.get("fontFamily") or "Inter",
                        "fontSize": font_size,
                        "color": style.get("color") or DEFAULT_THEME.colors.text,
                        "align": "left",
                    },
                }
            )

        layouts.append(
            {
                "id": f"layout_{slide['index'] + 1}",
                "name": f"Slide {slide['index'] + 1}",
                "slideType": slide_type,
                "background": {"type": "color", "value": DEFAULT_THEME.colors.background},
                "elements": elements,
            }
        )

    return {
        "schemaVersion": "1.0.0",
        "documentType": "template",
        "id": "generated_template",
        "name": "Generated from PPTX",
        "slideSize": {
            "widthEmu": slide_size.get("widthEmu", 0),
            "heightEmu": slide_size.get("heightEmu", 0),
            "ratio": "custom",
        },
        "theme": DEFAULT_THEME.model_dump(),
        "layouts": layouts,
    }


def _guess_slide_type(slide: dict[str, Any], total_slides: int) -> str:
    elements = slide.get("elements", [])
    has_image = any(el["type"] == "image" for el in elements)
    has_bullet = any(el.get("isBullet") for el in elements)
    texts = [el for el in elements if el["type"] == "text" and (el.get("text") or "").strip()]
    is_last_slide = slide["index"] == total_slides - 1

    if has_image and not has_bullet:
        return "image"
    if has_bullet:
        return "bullets"
    if len(texts) == 1:
        return "conclusion" if is_last_slide else "title"
    if len(texts) <= 2 and is_last_slide:
        return "conclusion"
    return "text"
