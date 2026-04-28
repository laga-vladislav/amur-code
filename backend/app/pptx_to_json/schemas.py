from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ElementTypeT = Literal["text", "image", "unknown"]


class RawBBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class RawStyle(BaseModel):
    fontSize: int | None = None
    fontFamily: str | None = None
    bold: bool = False
    color: str | None = None


class RawElement(BaseModel):
    type: ElementTypeT
    text: str | None = None
    bbox: RawBBox
    style: RawStyle = Field(default_factory=RawStyle)
    isBullet: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class RawSlide(BaseModel):
    index: int
    elements: list[RawElement] = Field(default_factory=list)


class RawPresentation(BaseModel):
    slideSize: dict[str, int]
    slides: list[RawSlide] = Field(default_factory=list)
