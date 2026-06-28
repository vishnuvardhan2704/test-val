"""Thin wrapper around a Groq-hosted OpenAI-compatible chat completion API."""
import json
from openai import OpenAI, APIStatusError, RateLimitError

from app.config import GROQ_API_KEY, GROQ_MODEL

_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
    max_retries=0,
)


def _ensure_api_key() -> None:
    if not GROQ_API_KEY:
        raise QuotaExceededError(
            "GROQ_API_KEY is not set. Add it in backend/.env before starting the backend."
        )


class QuotaExceededError(Exception):
    """Raised when the Groq quota/rate limit has been exhausted."""


def _extract_text(response) -> str:
    return (response.choices[0].message.content or "").strip()


def _normalize_api_errors(exc: Exception) -> None:
    if isinstance(exc, RateLimitError):
        raise QuotaExceededError(str(exc)) from exc
    if isinstance(exc, APIStatusError) and exc.status_code == 429:
        raise QuotaExceededError(str(exc)) from exc
    raise exc


def generate_text(prompt: str) -> str:
    _ensure_api_key()
    try:
        response = _client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_text(response)
    except Exception as exc:  # OpenAI SDK raises specialized subclasses at runtime
        _normalize_api_errors(exc)


def generate_json(prompt: str) -> dict:
    _ensure_api_key()
    try:
        response = _client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(response)
        return json.loads(text)
    except Exception as exc:  # OpenAI SDK raises specialized subclasses at runtime
        _normalize_api_errors(exc)
