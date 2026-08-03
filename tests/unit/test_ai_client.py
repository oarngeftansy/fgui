from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from figma_to_fgui.ai_client import (
    MAX_SUMMARY_DEPTH,
    AIAnalysisError,
    AIClientConfig,
    AIReasonCode,
    OpenAICompatibleSemanticClient,
    build_chat_completion_payload,
)


def _config(provider: str = "openai_compatible") -> AIClientConfig:
    return AIClientConfig(
        provider=provider,
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


@pytest.mark.parametrize("bad_string", ["\ud800", "prefix\udfff"])
@pytest.mark.parametrize("location", ["key", "value"])
def test_payload_rejects_isolated_surrogates_with_stable_error(
    bad_string: str, location: str
) -> None:
    node = {bad_string: "safe"} if location == "key" else {"name": bad_string}

    with pytest.raises(AIAnalysisError) as error:
        build_chat_completion_payload("model", {"nodes": [node]})

    assert error.value.code is AIReasonCode.REQUEST_INVALID
    assert bad_string not in str(error.value)


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_payload_rejects_non_finite_numbers(non_finite: float) -> None:
    with pytest.raises(AIAnalysisError) as error:
        build_chat_completion_payload("model", {"nodes": [{"x": non_finite}]})

    assert error.value.code is AIReasonCode.REQUEST_INVALID


def test_config_rejects_plain_http_before_sending_the_key() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(ValidationError):
        config = AIClientConfig(
            provider="openai",
            base_url="http://ai.example.test/v1",
            model="model",
            api_key=SecretStr("must-not-be-sent"),
        )
        OpenAICompatibleSemanticClient(
            config,
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200)
            ),
        )

    assert requests == []


@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_supported_providers_use_the_compatible_endpoint(provider: str) -> None:
    requests: list[httpx.Request] = []
    client = OpenAICompatibleSemanticClient(
        _config(provider),
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=_valid_response())
        ),
    )

    assert client.analyze({"nodes": []}).version == 1
    assert requests[0].url.path == "/v1/chat/completions"


def test_timeout_has_a_stable_reason_code() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=request)

    client = OpenAICompatibleSemanticClient(_config(), transport=httpx.MockTransport(timeout))

    with pytest.raises(AIAnalysisError) as error:
        client.analyze({"nodes": []})

    assert error.value.code is AIReasonCode.TIMEOUT
    assert "private timeout details" not in str(error.value)


def test_invalid_semantic_response_schema_has_a_stable_reason_code() -> None:
    remote = {"choices": [{"message": {"content": '{"version":1,"decisions":[{}]}'}}]}
    client = OpenAICompatibleSemanticClient(
        _config(), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=remote))
    )

    with pytest.raises(AIAnalysisError) as error:
        client.analyze({"nodes": []})

    assert error.value.code is AIReasonCode.RESPONSE_VALIDATION


@pytest.mark.parametrize("exception", [ValueError("private value"), UnicodeError("private unicode")])
def test_transport_value_errors_are_redacted(exception: Exception) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise exception

    client = OpenAICompatibleSemanticClient(_config(), transport=httpx.MockTransport(fail))

    with pytest.raises(AIAnalysisError) as error:
        client.analyze({"nodes": []})

    assert error.value.code is AIReasonCode.TRANSPORT
    assert "private" not in str(error.value)


@pytest.mark.parametrize("container_type", ["dict", "list"])
def test_payload_rejects_self_referential_containers(container_type: str) -> None:
    if container_type == "dict":
        cycle: dict[str, object] | list[object] = {}
        cycle["self"] = cycle
        summary = {"nodes": [cycle]}
    else:
        cycle = []
        cycle.append(cycle)
        summary = {"nodes": cycle}

    with pytest.raises(AIAnalysisError) as error:
        build_chat_completion_payload("model", summary)

    assert error.value.code is AIReasonCode.REQUEST_INVALID
    assert "cycle" not in str(error.value).lower()


def test_payload_rejects_summary_beyond_explicit_depth_limit() -> None:
    nested: object = "leaf"
    for _ in range(MAX_SUMMARY_DEPTH + 1):
        nested = {"child": nested}

    with pytest.raises(AIAnalysisError) as error:
        build_chat_completion_payload("model", {"nodes": [nested]})

    assert error.value.code is AIReasonCode.REQUEST_INVALID


def test_overdeep_response_json_has_a_stable_redacted_reason() -> None:
    overdeep_json = "[" * 5_000 + '"private response"' + "]" * 5_000
    assert len(overdeep_json.encode("utf-8")) < 256 * 1024
    client = OpenAICompatibleSemanticClient(
        _config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=overdeep_json.encode("utf-8"))
        ),
    )

    with pytest.raises(AIAnalysisError) as error:
        client.analyze({"nodes": []})

    assert error.value.code is AIReasonCode.RESPONSE_JSON
    assert "private response" not in str(error.value)
