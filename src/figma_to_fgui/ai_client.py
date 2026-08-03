from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Literal, cast

import httpx
from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError

from figma_to_fgui.models import FrozenModel
from figma_to_fgui.semantic_models import SemanticResponse

MAX_SUMMARY_NODES = 500
MAX_STRING_BYTES = 512
MAX_SUMMARY_BYTES = 128 * 1024
MAX_REQUEST_BYTES = 1_500 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_SCREENSHOT_BYTES = 1_000 * 1024

_SYSTEM_PROMPT = (
    "Classify only the supplied Figma node structure. Return a JSON object matching the semantic "
    "response schema: version=1, decisions with node_id, semantic_type, confidence, and optional "
    "fgui_name, children_roles, state_pages, reparent, risks, screenshot_recommended, "
    "screenshot_reason. Do not invent node ids."
)


class AIClientConfig(FrozenModel):
    provider: Literal["openai", "openai_compatible"]
    base_url: AnyHttpUrl
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr
    timeout_seconds: float = Field(default=20, ge=1, le=120)


class AIAnalysisError(Exception):
    """A safe, stable error that intentionally excludes remote and user-supplied content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"AI semantic analysis failed ({code})")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise AIAnalysisError("ai.request_invalid") from None


def _check_summary_value(value: object) -> None:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise AIAnalysisError("ai.request_invalid")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or len(key.encode("utf-8")) > MAX_STRING_BYTES:
                raise AIAnalysisError("ai.request_invalid")
            _check_summary_value(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        for item in value:
            _check_summary_value(item)
        return
    if value is None or isinstance(value, bool | int | float):
        return
    raise AIAnalysisError("ai.request_invalid")


def _validated_summary_json(summary: dict[str, object]) -> str:
    nodes = summary.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > MAX_SUMMARY_NODES:
        raise AIAnalysisError("ai.request_invalid")
    _check_summary_value(summary)
    encoded = _canonical_json(summary)
    if len(encoded) > MAX_SUMMARY_BYTES:
        raise AIAnalysisError("ai.request_too_large")
    return encoded.decode("utf-8")


def build_chat_completion_payload(
    model: str, summary: dict[str, object], screenshot: bytes | None = None
) -> dict[str, object]:
    """Create the smallest compatible chat-completions request for structured semantics."""
    if not model or len(model) > 120:
        raise AIAnalysisError("ai.request_invalid")
    summary_json = _validated_summary_json(summary)
    user_content: str | list[dict[str, object]] = summary_json
    if screenshot is not None:
        if len(screenshot) > MAX_SCREENSHOT_BYTES:
            raise AIAnalysisError("ai.screenshot_too_large")
        user_content = [
            {"type": "text", "text": summary_json},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii")
                },
            },
        ]
    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    if len(_canonical_json(payload)) > MAX_REQUEST_BYTES:
        raise AIAnalysisError("ai.request_too_large")
    return payload


def _extract_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AIAnalysisError("ai.response_schema")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise AIAnalysisError("ai.response_schema")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise AIAnalysisError("ai.response_schema")
    return cast(str, message["content"])


class OpenAICompatibleSemanticClient:
    def __init__(
        self,
        config: AIClientConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.http = httpx.Client(
            base_url=str(config.base_url),
            transport=transport,
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,
        )

    def close(self) -> None:
        self.http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Accept": "application/json",
        }

    def analyze(self, summary: dict[str, object], screenshot: bytes | None = None) -> SemanticResponse:
        payload = build_chat_completion_payload(self.config.model, summary, screenshot)
        try:
            with self.http.stream(
                "POST", "/chat/completions", json=payload, headers=self._headers()
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise AIAnalysisError("ai.http_status")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise AIAnalysisError("ai.response_too_large")
        except AIAnalysisError:
            raise
        except httpx.TimeoutException:
            raise AIAnalysisError("ai.timeout") from None
        except httpx.HTTPError:
            raise AIAnalysisError("ai.transport") from None

        try:
            response_payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AIAnalysisError("ai.response_json") from None
        try:
            return SemanticResponse.model_validate_json(_extract_content(response_payload))
        except AIAnalysisError:
            raise
        except (ValidationError, ValueError, TypeError, UnicodeDecodeError):
            raise AIAnalysisError("ai.response_validation") from None
