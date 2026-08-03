from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal, cast

import httpx
from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator

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

    @field_validator("base_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("AI base URL must use HTTPS")
        return value


class AIReasonCode(StrEnum):
    DISABLED = "ai.disabled"
    HTTP_STATUS = "ai.http_status"
    INTERNAL = "ai.internal"
    REQUEST_INVALID = "ai.request_invalid"
    REQUEST_TOO_LARGE = "ai.request_too_large"
    RESPONSE_JSON = "ai.response_json"
    RESPONSE_SCHEMA = "ai.response_schema"
    RESPONSE_TOO_LARGE = "ai.response_too_large"
    RESPONSE_VALIDATION = "ai.response_validation"
    SCREENSHOT_TOO_LARGE = "ai.screenshot_too_large"
    TIMEOUT = "ai.timeout"
    TRANSPORT = "ai.transport"


class AIAnalysisError(Exception):
    """A safe, stable error that intentionally excludes remote and user-supplied content."""

    def __init__(self, code: AIReasonCode) -> None:
        self.code = code if isinstance(code, AIReasonCode) else AIReasonCode.INTERNAL
        super().__init__(f"AI semantic analysis failed ({self.code})")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise AIAnalysisError(AIReasonCode.REQUEST_INVALID) from None


def _check_summary_value(value: object) -> None:
    if isinstance(value, str):
        try:
            encoded_length = len(value.encode("utf-8"))
        except UnicodeError:
            raise AIAnalysisError(AIReasonCode.REQUEST_INVALID) from None
        if encoded_length > MAX_STRING_BYTES:
            raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)
            try:
                encoded_key_length = len(key.encode("utf-8"))
            except UnicodeError:
                raise AIAnalysisError(AIReasonCode.REQUEST_INVALID) from None
            if encoded_key_length > MAX_STRING_BYTES:
                raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)
            _check_summary_value(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        for item in value:
            _check_summary_value(item)
        return
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)


def _validated_summary_json(summary: dict[str, object]) -> str:
    nodes = summary.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > MAX_SUMMARY_NODES:
        raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)
    _check_summary_value(summary)
    encoded = _canonical_json(summary)
    if len(encoded) > MAX_SUMMARY_BYTES:
        raise AIAnalysisError(AIReasonCode.REQUEST_TOO_LARGE)
    return encoded.decode("utf-8")


def build_chat_completion_payload(
    model: str, summary: dict[str, object], screenshot: bytes | None = None
) -> dict[str, object]:
    """Create the smallest compatible chat-completions request for structured semantics."""
    if not model or len(model) > 120:
        raise AIAnalysisError(AIReasonCode.REQUEST_INVALID)
    summary_json = _validated_summary_json(summary)
    user_content: str | list[dict[str, object]] = summary_json
    if screenshot is not None:
        if len(screenshot) > MAX_SCREENSHOT_BYTES:
            raise AIAnalysisError(AIReasonCode.SCREENSHOT_TOO_LARGE)
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
        raise AIAnalysisError(AIReasonCode.REQUEST_TOO_LARGE)
    return payload


def _extract_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AIAnalysisError(AIReasonCode.RESPONSE_SCHEMA)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise AIAnalysisError(AIReasonCode.RESPONSE_SCHEMA)
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise AIAnalysisError(AIReasonCode.RESPONSE_SCHEMA)
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
                    raise AIAnalysisError(AIReasonCode.HTTP_STATUS)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise AIAnalysisError(AIReasonCode.RESPONSE_TOO_LARGE)
        except AIAnalysisError:
            raise
        except httpx.TimeoutException:
            raise AIAnalysisError(AIReasonCode.TIMEOUT) from None
        except httpx.HTTPError:
            raise AIAnalysisError(AIReasonCode.TRANSPORT) from None
        except (ValueError, UnicodeError):
            raise AIAnalysisError(AIReasonCode.TRANSPORT) from None

        try:
            response_payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise AIAnalysisError(AIReasonCode.RESPONSE_JSON) from None
        try:
            return SemanticResponse.model_validate_json(_extract_content(response_payload))
        except AIAnalysisError:
            raise
        except (ValidationError, ValueError, TypeError, UnicodeDecodeError):
            raise AIAnalysisError(AIReasonCode.RESPONSE_VALIDATION) from None
