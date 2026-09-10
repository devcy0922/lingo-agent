from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

PathKey = Tuple[str, ...]
JsonObject = Dict[str, Any]


@dataclass
class GlossaryTerm:
    term: str
    translations: Dict[str, str] = field(default_factory=dict)
    forbidden: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ToneConfig:
    style: str = "general"          # general, technical, friendly, formal
    formality: str = "polite"        # polite (경어체), plain (평어체), direct
    guidelines: List[str] = field(default_factory=list)


@dataclass
class ProfileConfig:
    name: str = "default"
    parent: Optional[str] = None
    tone: ToneConfig = field(default_factory=ToneConfig)
    terms: Dict[str, GlossaryTerm] = field(default_factory=dict)
    key_scoped_rules: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    prohibited_phrases: List[str] = field(default_factory=list)


@dataclass
class QADimensionScore:
    dimension: str
    score: int
    critique: str = ""


@dataclass
class KeyQAResult:
    key: str
    scores: Dict[str, int] = field(default_factory=dict)
    critiques: Dict[str, str] = field(default_factory=dict)
    passed: bool = True
    critical_error: bool = False


@dataclass
class BatchQAResult:
    key_results: Dict[str, KeyQAResult] = field(default_factory=dict)
    passed: bool = True
    advisory_only: bool = False
    average_score: float = 0.0
