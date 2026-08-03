from __future__ import annotations

import json
from typing import Literal

import httpx

from figma_to_fgui.semantic_config import (
    ConfiguredSemanticAnalyzer,
    build_semantic_analyzer,
    load_semantic_service_settings,
)

FakeAIScenario = Literal["structure_success", "screenshot_success", "ai_failure"]


def build_fake_semantic_analyzer(scenario: FakeAIScenario) -> ConfiguredSemanticAnalyzer:
    def respond(request: httpx.Request) -> httpx.Response:
        if scenario == "ai_failure":
            return httpx.Response(500, text="private fake model response")
        payload = json.loads(request.content)
        content = payload["messages"][1]["content"]
        wants_screenshot = scenario == "screenshot_success" and isinstance(content, str)
        result = {
            "version": 1,
            "decisions": [],
            "screenshot_recommended": wants_screenshot,
            "screenshot_reason": "Visual grouping needs confirmation." if wants_screenshot else None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(result)}}]},
        )

    analyzer = build_semantic_analyzer(
        load_semantic_service_settings(
            {
                "AI_SEMANTIC_ENABLED": "true",
                "AI_SEMANTIC_PROVIDER": "openai_compatible",
                "AI_SEMANTIC_BASE_URL": "https://fake-ai.example.test/v1",
                "AI_SEMANTIC_MODEL": "fake-semantic-model",
                "AI_SEMANTIC_API_KEY": "fake-test-key",
                "AI_SEMANTIC_TIMEOUT_SECONDS": "2",
                "AI_SEMANTIC_CONFIDENCE_THRESHOLD": "0.75",
            }
        ),
        transport=httpx.MockTransport(respond),
    )
    if analyzer is None:
        raise RuntimeError("fake AI analyzer was unexpectedly disabled")
    return analyzer
