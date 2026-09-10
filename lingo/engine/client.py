from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("lingo.engine.client")


class GatewayClient:
    """보안 LLM 게이트웨이와 통신하는 Fail-Closed 클라이언트."""

    def __init__(
        self,
        gateway_url: str,
        api_key: str = "",
        timeout: float = 240.0,
        min_interval: float = 0.0,
        max_attempts: int = 4,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._last_request_at = 0.0

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _wait_for_rate_limit(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
    ) -> str:
        """단일 채팅 완성 요청을 수행하며 재시도 및 간격을 제어합니다."""
        if not self.gateway_url:
            raise RuntimeError("LLM_GATEWAY_URL이 설정되지 않았습니다.")

        url = f"{self.gateway_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self._wait_for_rate_limit()
                self._last_request_at = time.time()

                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, headers=self._headers(), json=payload)

                if resp.status_code == 429:
                    wait_time = max(10, attempt * 10)
                    logger.warning(f"Gateway 429 Rate Limit. {wait_time}초 대기 후 재시도 ({attempt}/{self.max_attempts})")
                    time.sleep(wait_time)
                    continue

                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                return content
            except Exception as e:
                last_err = e
                logger.warning(f"LLM 요청 오류 ({attempt}/{self.max_attempts}): {e}")
                if attempt < self.max_attempts:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM Gateway 호출 실패 (시도 {self.max_attempts}회 초과): {last_err}")
