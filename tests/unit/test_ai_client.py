from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from figma_to_fgui.ai_client import (
    AIAnalysisError,
    AIClientConfig,
    OpenAICompatibleSemanticClient,
    build_chat_completion_payload,
)


def _config() -> AIClientConfig:
    return AIClientConfig(
        provider="openai_compatible",
        base_url="https://ai.example.test/v1",
        model="semantic-model",
        api_key=SecretStr("secret-value"),
    )


def _valid_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "version": 1,
                            "decisions": [
                                {
                                    "node_id": "button",
                                    "semantic_type": "Button",
                                    "confidence": 0.9,
                                }
                            ],
                        }
                    )
                }
            }
        ]
    }


def test_client_uses_bearer_token_without_exposing_it() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_valid_response())

    client = OpenAICompatibleSemanticClient(_config(), transport=httpx.MockTransport(handler))

    result = client.analyze({"version": 1, "nodes": []})

    assert result.version == 1
    assert requests[0].headers["Authorization"] == "Bearer secret-value"
    body = json.loads(requests[0].content)
    assert body["model"] == "semantic-model"
    assert requests[0].url.path == "/v1/chat/completions"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_failures_raise_redacted_error(status: int) -> None:
    client = OpenAICompatibleSemanticClient(
        _config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="server included secret-value")
        ),
    )

    with pytest.raises(AIAnalysisError) as error:
        client.analyze({"version": 1, "nodes": []})

    assert error.value.code == "ai.http_status"
    assert "secret-value" not in str(error.value)


def test_transport_and_invalid_response_fail_with_stable_redacted_codes() -> None:
    transport_client = OpenAICompatibleSemanticClient(
        _config(),
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("secret-value"))),
    )
    response_client = OpenAICompatibleSemanticClient(
        _config(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not json secret-value")),
    )

    with pytest.raises(AIAnalysisError, match="ai.transport") as transport_error:
        transport_client.analyze({"version": 1, "nodes": []})
    with pytest.raises(AIAnalysisError, match="ai.response_json") as response_error:
        response_client.analyze({"version": 1, "nodes": []})

    assert "secret-value" not in str(transport_error.value)
    assert "secret-value" not in str(response_error.value)


def test_client_rejects_oversized_summary_response_and_screenshot() -> None:
    client = OpenAICompatibleSemanticClient(
        _config(), transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 300_000))
    )

    with pytest.raises(AIAnalysisError, match="ai.request_invalid"):
        client.analyze({"nodes": ["x" * 1_000]})
    with pytest.raises(AIAnalysisError, match="ai.response_too_large"):
        client.analyze({"version": 1, "nodes": []})
    with pytest.raises(AIAnalysisError, match="ai.screenshot_too_large"):
        client.analyze({"version": 1, "nodes": []}, screenshot=b"x" * 2_000_001)


def test_payload_is_minimal_and_only_embeds_screenshot_when_present() -> None:
    without_screenshot = build_chat_completion_payload("model", {"version": 1, "nodes": []})
    with_screenshot = build_chat_completion_payload("model", {"version": 1, "nodes": []}, b"png")

    assert without_screenshot["messages"][1]["content"] == '{"nodes":[],"version":1}'
    assert without_screenshot["response_format"] == {"type": "json_object"}
    assert isinstance(with_screenshot["messages"][1]["content"], list)
