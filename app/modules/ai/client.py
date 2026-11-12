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

        # ENFORCE STRICTLY FREE OPENROUTER MODELS ONLY (PROTOTYPE MODE)
        # Any model that does not explicitly end with ':free' is mapped to DEFAULT_MODEL
        if not model or not str(model).endswith(":free"):
            target_model = self.DEFAULT_MODEL
        else:
            target_model = str(model)

        candidate_models = [target_model]
        for fallback in FREE_MODELS_FALLBACK:
            if fallback not in candidate_models and len(candidate_models) < 3:
                candidate_models.append(fallback)
        payload["models"] = candidate_models[:3]
        if "model" in payload:
            del payload["model"]

        # Default max_tokens to 3000 to prevent OpenRouter assuming full model context (16k) which triggers 402
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        else:
            payload["max_tokens"] = 3000

        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._send_request(payload)
            except AIRateLimitError as exc:
                last_error = exc
                if getattr(exc, "is_daily_limit", False):
                    # Daily quota for free tier exceeded on OpenRouter, do not sleep/retry
                    logger.warning("ai_daily_rate_limit_exceeded", error=str(exc))
                    raise exc
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
                err_str = str(exc).lower()
                # If credits error (402) or model not found (404), switch payload to free models immediately
                if "402" in err_str or "credits" in err_str or "404" in err_str or "afford" in err_str:
                    logger.warning("ai_credits_or_model_error_falling_back_to_free", error=str(exc))
                    if "model" in payload:
                        del payload["model"]
                    payload["models"] = FREE_MODELS_FALLBACK[:3]
                    payload["max_tokens"] = 2500

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
            err_text = resp.text.lower()
            is_daily = "free-models-per-day" in err_text or "openrouter_free_tier_daily" in err_text or "remaining\":0" in err_text
            raise AIRateLimitError(int(retry_after) if retry_after else None, is_daily_limit=is_daily)

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
            msg = choice.get("message", {})
            content = msg.get("content") or msg.get("text") or choice.get("text") or msg.get("reasoning") or ""
            usage = data.get("usage", {})
            return AIResponse(
                content=content,
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
        """Extract and resiliently repair JSON from AI response."""
        if not content:
            raise AIResponseParsingError("No content returned in AI response")
            
        import re
        text = content.strip()

        # 1. Strip markdown code fences (even if missing closing fence)
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)(?:```|$)', text)
        if fence_match:
            candidate = fence_match.group(1).strip()
            if candidate:
                text = candidate

        # 2. Find JSON boundaries
        start_brace = text.find("{")
        start_bracket = text.find("[")
        if start_brace == -1 and start_bracket == -1:
            raise AIResponseParsingError("No JSON found in AI response")

        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            start = start_brace
            end = text.rfind("}") + 1
        else:
            start = start_bracket
            end = text.rfind("]") + 1

        json_slice = text[start:end] if end > start else text[start:]

        # Direct parse attempt
        try:
            return json.loads(json_slice)
        except json.JSONDecodeError:
            pass

        # Clean single-line comments and trailing commas before braces/brackets
        cleaned = re.sub(r'//.*?\n', '\n', json_slice)
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Handle truncated JSON arrays/objects
        last_brace = cleaned.rfind("}")
        if last_brace != -1:
            truncated_attempt = cleaned[:last_brace + 1] + "\n]}"
            truncated_attempt = re.sub(r',\s*([}\]])', r'\1', truncated_attempt)
            try:
                return json.loads(truncated_attempt)
            except json.JSONDecodeError:
                pass

        # Regex fallback: extract questions blocks directly
        q_matches = re.finditer(r'\"question\"\s*:\s*\"([^\"]+)\"', text)
        extracted = []
        for q_m in q_matches:
            q_text = q_m.group(1).strip()
            if q_text:
                extracted.append({
                    "question": q_text,
                    "type": "multiple_choice",
                    "options": [],
                    "correct_answer": "",
                    "explanation": "",
                })

        if extracted:
            return {"title": "Examen generado", "questions": extracted}

        raise AIResponseParsingError(f"Could not parse valid JSON from AI output: {text[:200]}")

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
