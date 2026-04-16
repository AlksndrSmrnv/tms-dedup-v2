"""Pydantic модели предметной области.

Модели используются для:
- валидации входных данных (CSV/JSON из TMS),
- сериализации промежуточных артефактов (dataset.jsonl, candidate_pairs.jsonl),
- валидации JSON-ответов Qwen CLI (согласно схемам в .qwen/skills/.../schemas/).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Базовые сущности
# --------------------------------------------------------------------------- #


class TestItem(BaseModel):
    """Один тест из TMS в уже нормализованном виде."""

    model_config = ConfigDict(frozen=False)

    test_id: str
    title: str
    full_section_path: str
    section_path_parts: list[str] = Field(default_factory=list)
    title_norm: str = ""
    title_tokens: list[str] = Field(default_factory=list)
    section_tokens: list[str] = Field(default_factory=list)

    @field_validator("test_id", mode="before")
    @classmethod
    def _id_to_str(cls, v: object) -> str:
        # TMS часто отдаёт id числом — приводим к строке для консистентности.
        return str(v) if v is not None else ""


# --------------------------------------------------------------------------- #
# Классификация секций (оси sibling-групп)
# --------------------------------------------------------------------------- #


class AxisType(str, Enum):
    BUSINESS_VARIANT = "BUSINESS_VARIANT"
    FEATURE_GROUP = "FEATURE_GROUP"
    TECH_GROUP = "TECH_GROUP"
    UNKNOWN = "UNKNOWN"


class SectionValue(BaseModel):
    section_name: str
    normalized_value: str = ""


class SectionAxis(BaseModel):
    """Гипотеза об оси для группы sibling-секций одного parent-узла."""

    parent_section: str
    axis_type: AxisType = AxisType.UNKNOWN
    dimension_name: str = ""
    confidence: float = 0.0
    reason: str = ""
    section_values: list[SectionValue] = Field(default_factory=list)

    # --- служебные поля для Python-эвристик (Qwen их может игнорировать) --- #
    child_name_overlap: float = 0.0
    title_pattern_overlap: float = 0.0
    variant_token_hits: int = 0
    tech_token_hits: int = 0
    child_count: int = 0


# --------------------------------------------------------------------------- #
# Кандидатные пары и вердикты
# --------------------------------------------------------------------------- #


class Verdict(str, Enum):
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    RELATED_NOT_DUPLICATE = "RELATED_NOT_DUPLICATE"
    NOT_DUPLICATE = "NOT_DUPLICATE"


SectionRelation = Literal[
    "same_section",
    "same_feature_group",
    "cross_feature_group",
    "cross_business_variant",
    "unknown",
]


class ScoreBreakdown(BaseModel):
    tfidf_char: float = 0.0
    tfidf_word: float = 0.0
    token_set_ratio: float = 0.0  # нормализовано в 0..1
    partial_ratio: float = 0.0  # нормализовано в 0..1
    similarity: float = 0.0
    variant_conflict: bool = False
    variant_conflict_tokens: list[str] = Field(default_factory=list)
    same_section: bool = False
    same_parent_section: bool = False
    cross_business_variant: bool = False
    section_relation: SectionRelation = "unknown"


class CandidatePair(BaseModel):
    """Одна кандидатная пара тестов с авто-вердиктом и объяснением."""

    test_a_id: str
    test_b_id: str
    test_a_title: str
    test_b_title: str
    test_a_section: str
    test_b_section: str

    score: ScoreBreakdown
    auto_verdict: Verdict
    auto_confidence: float
    explanation: str

    needs_qwen_review: bool = False
    review_reason: str = ""


class PairReview(BaseModel):
    """Ответ Qwen CLI по одной паре — схема совпадает с pair_review.schema.json."""

    test_a_id: str
    test_b_id: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    same_base_intent: bool = False
    different_dimensions: list[str] = Field(default_factory=list)
    section_relation: SectionRelation = "unknown"
    explanation: str = ""


class SectionAxisReview(BaseModel):
    """Ответ Qwen CLI по одной sibling-группе — схема совпадает
    с section_axis.schema.json. Те же поля, что и в SectionAxis, но без
    служебной статистики Python."""

    parent_section: str
    axis_type: AxisType
    dimension_name: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    section_values: list[SectionValue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Финальные структуры отчётов
# --------------------------------------------------------------------------- #


class FinalPairRecord(BaseModel):
    """Итоговая строка отчёта по паре (auto + Qwen review, где есть)."""

    test_a_id: str
    test_b_id: str
    test_a_title: str
    test_b_title: str
    test_a_section: str
    test_b_section: str
    verdict: Verdict
    confidence: float
    source: Literal["auto", "qwen"] = "auto"
    section_relation: SectionRelation = "unknown"
    different_dimensions: list[str] = Field(default_factory=list)
    explanation: str = ""
    similarity: float = 0.0


__all__ = [
    "TestItem",
    "AxisType",
    "SectionValue",
    "SectionAxis",
    "Verdict",
    "SectionRelation",
    "ScoreBreakdown",
    "CandidatePair",
    "PairReview",
    "SectionAxisReview",
    "FinalPairRecord",
]
