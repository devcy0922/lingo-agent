from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from lingo.config import LingoConfig


class BaseAdapter(ABC):
    def __init__(self, config: LingoConfig):
        self.config = config

    @abstractmethod
    def translate(
        self,
        source_path: Path,
        target_langs: List[str],
        output_dir: Optional[Path] = None,
        base_source_path: Optional[Path] = None,
        report_path: Optional[Path] = None,
    ) -> int:
        """번역 및 검증을 수행하고 종료 코드(0: 성공, 1: fallback, 2: QA 실패, 3: IO오류)를 반환합니다."""
        pass
