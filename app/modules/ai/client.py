"""
Async AI client with retry logic, exponential backoff, timeout handling.
Communicates with OpenRouter API using httpx.
"""
import json
import time
from typing import Any, AsyncGenerator, Optional

import httpx
import structlog

from app.core.config import settings
from app.core.exceptions import (
    AIServiceError,
    AITimeoutError,
    AIRateLimitError,
    AIResponseParsingError,
)

logger = structlog.get_logger(__name__)

# Cost per 1K tokens by model
COST_PER_1K_TOKENS = {
    "openrouter/free": {"input": 0.0, "output": 0.0},
    "liquid/lfm-2.5-2.6b:free": {"input": 0.0, "output": 0.0},
    "liquid/lfm-3-1.7b:free": {"input": 0.0, "output": 0.0},
    "nvidia/nemotron-3-ultra-550b-a55b:free": {"input": 0.0, "output": 0.0},
    "nvidia/nemotron-3.5-lightning:free": {"input": 0.0, "output": 0.0},
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {"input": 0.0, "output": 0.0},
    "baidu/ernie-5.5-flash-preview:free": {"input": 0.0, "output": 0.0},
    "deepseek/deepseek-v4-flash:free": {"input": 0.0, "output": 0.0},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

FREE_MODELS_FALLBACK = [
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "baidu/ernie-5.5-flash-preview:free",
]


class AIResponse:
    """Structured AI response."""

    def __init__(
        self,
        content: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        finish_reason: str = "stop",
    ):
        self.content = content
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.finish_reason = finish_reason

    @property
    def estimated_cost(self) -> float:
        rates = COST_PER_1K_TOKENS.get(self.model, {"input": 0.005, "output": 0.015})
        return (
            self.input_tokens / 1000 * rates["input"]
            + self.output_tokens / 1000 * rates["output"]
        )


class AIClient:
    """
    Enterprise async AI client:
    - Exponential backoff with jitter
    - Configurable retry count
    - Timeout handling
    - Rate limit detection
    - Response validation
    - Streaming support
    """

    DEFAULT_MODEL = "liquid/lfm-2.5-2.6b:free"
    DEFAULT_TIMEOUT = 60
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 2  # seconds

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.api_url = api_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Main Chat Method ─────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
    ) -> AIResponse:
        """
        Send a chat completion request with automatic retries.
        Automatically leverages fallback models for free tier to prevent 404/rate-limit downtime.
        """
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }

        # Handle free tier models with OpenRouter models array (up to 3 items)
        if model.endswith(":free") or model in ("openrouter/free", "default") or "deepseek" in model:
            target_model = (
                self.DEFAULT_MODEL
                if "deepseek" in model or model in ("openrouter/free", "default")
                else model
            )
            candidate_models = [target_model]
            for fallback in FREE_MODELS_FALLBACK:
                if fallback not in candidate_models and len(candidate_models) < 3:
                    candidate_models.append(fallback)
            payload["models"] = candidate_models[:3]
        else:
            payload["model"] = model

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._send_request(payload)
            except AIRateLimitError as exc:
                last_error = exc
                delay = self._backoff_delay(attempt, base=5)
                logger.warning(
                    "ai_rate_limited",
                    attempt=attempt + 1,
                    retry_after=delay,
                )
                await self._sleep(delay)
            except AITimeoutError as exc:
                last_error = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "ai_timeout",
                    attempt=attempt + 1,
                    retry_after=delay,
                )
                await self._sleep(delay)
            except AIServiceError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "ai_error_retrying",
                        attempt=attempt + 1,
                        error=str(exc),
                        retry_after=delay,
                    )
                    await self._sleep(delay)

        raise last_error or AIServiceError("AI request failed after all retries")

    # ── JSON Chat ────────────────────────────────────────────────────────

    async def chat_json(
        self,
        messages: list[dict],
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Chat and parse the response as JSON."""
        response = await self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json_response(response.content), response

    # ── Internal ─────────────────────────────────────────────────────────

    async def _send_request(self, payload: dict) -> AIResponse:
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = await client.post(self.api_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise AITimeoutError()
        except httpx.ConnectError as exc:
            raise AIServiceError(f"Cannot connect to AI service: {exc}")

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise AIRateLimitError(int(retry_after) if retry_after else None)

        if resp.status_code >= 500:
            raise AIServiceError(
                f"AI service returned {resp.status_code}",
                details=resp.text[:500],
            )

        if resp.status_code >= 400:
            raise AIServiceError(
                f"AI request failed ({resp.status_code}): {resp.text[:300]}"
            )

        data = resp.json()

        if "error" in data:
            raise AIServiceError(f"AI returned error: {data['error']}")

        try:
            choice = data["choices"][0]
            usage = data.get("usage", {})
            return AIResponse(
                content=choice.get("message", {}).get("content") or "",
                model=data.get("model") or payload.get("model") or (payload.get("models") or ["unknown"])[0],
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=choice.get("finish_reason", "stop"),
            )
        except (KeyError, IndexError) as exc:
            raise AIResponseParsingError(
                f"Unexpected AI response structure: {exc}"
            )

    @staticmethod
    def _parse_json_response(content: Optional[str]) -> dict:
        """Extract JSON from AI response, handling markdown code fences."""
        if not content:
            raise AIResponseParsingError("No content returned in AI response")
            
        text = content.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # Remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Find JSON boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            # Try array
            start = text.find("[")
            end = text.rfind("]") + 1

        if start == -1 or end == 0:
            raise AIResponseParsingError(f"No JSON found in AI response")

        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            raise AIResponseParsingError(f"Invalid JSON in AI response: {exc}")

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 2) -> float:
        """Exponential backoff with jitter."""
        import random

        return min(base * (2**attempt) + random.uniform(0, 1), 60)

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)


# Global singleton
ai_client = AIClient()
