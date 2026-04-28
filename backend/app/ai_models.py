"""Models for the internal AI generation API."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .models import SlideTypeT


StyleIdT = Literal["business", "friendly", "academic", "promo"]


class LayoutGenerationBasis(BaseModel):
    kind: Literal["layout"]
    templateId: str
    layoutIds: Optional[list[str]] = None

    model_config = ConfigDict(extra="forbid")


class StyleGenerationBasis(BaseModel):
    kind: Literal["style"]
    styleId: StyleIdT

    model_config = ConfigDict(extra="forbid")


GenerationBasis = Annotated[
    Union[LayoutGenerationBasis, StyleGenerationBasis],
    Field(discriminator="kind"),
]


class OutlineSlide(BaseModel):
    order: int
    title: str
    purpose: str = ""
    keyPoints: list[str] = Field(default_factory=list)
    visualIntent: Optional[str] = None
    needsImage: bool = False
    slideType: Optional[SlideTypeT] = None
    imagePrompt: Optional[str] = None
    speakerNotes: Optional[str] = None


class PresentationOutline(BaseModel):
    title: str
    audience: Optional[str] = None
    goal: Optional[str] = None
    slides: list[OutlineSlide] = Field(default_factory=list)


class OutlineGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    slideCount: int = Field(ge=1, le=40)
    language: str = "ru"
    basis: GenerationBasis


class OutlineRetryRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)
    outline: PresentationOutline


class OutlineGenerationResponse(BaseModel):
    generationId: str
    status: Literal["outline_ready"] = "outline_ready"
    outline: PresentationOutline


class ImagePolicy(BaseModel):
    generateImages: bool = True
    imageType: Literal["png", "bmp", "gif", "tiff", "jpeg"] = "png"


class PresentationBuildRequest(BaseModel):
    outline: PresentationOutline
    imagePolicy: ImagePolicy = Field(default_factory=ImagePolicy)
