"""Launch classifier — Anthropic-backed structured classification.

Public surface: ``classify_launch(post_text, metadata) -> ClassificationResult``.
The agent orchestrator (Phase 5) exposes this function as the
``classify_launch`` tool; that tool's JSON schema is ``CLASSIFIER_TOOL_SCHEMA``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from src.classifier.prompt import load_system_prompt
from src.classifier.schema import ClassificationResult

DEFAULT_MODEL = "claude-haiku-4-5"
_TOOL_NAME = "record_classification"

CLASSIFIER_TOOL_SCHEMA: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": (
        "Record the classification of a social media post against the launch "
        "definition in docs/launch_definition.md."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_launch": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "launch_type": {
                "type": ["string", "null"],
                "enum": ["product", "feature", "milestone", "program", None],
            },
            "reasoning": {"type": "string", "minLength": 1},
        },
        "required": ["is_launch", "confidence", "launch_type", "reasoning"],
    },
}


class ClassifierBackend(Protocol):
    """Transport-agnostic interface; tests substitute a stub."""

    def classify(self, *, system: str, user: str) -> dict[str, Any]: ...


class AnthropicBackend:
    """Real backend. Calls Claude with forced ``tool_use`` + prompt caching."""

    def __init__(
        self,
        *,
        client: Any = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 512,
    ) -> None:
        if client is None:
            from anthropic import Anthropic  # lazy import so tests can skip the env var

            client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def classify(self, *, system: str, user: str) -> dict[str, Any]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[CLASSIFIER_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": user}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return dict(block.input)
        raise RuntimeError(
            f"Model did not call {_TOOL_NAME}; stop_reason={response.stop_reason}"
        )


def _format_user_message(post_text: str, metadata: dict[str, Any]) -> str:
    payload = {"post_text": post_text, "metadata": metadata}
    return "Classify this post:\n\n" + json.dumps(payload, indent=2, ensure_ascii=False)


def classify_launch(
    post_text: str,
    metadata: dict[str, Any] | None = None,
    *,
    backend: ClassifierBackend | None = None,
) -> ClassificationResult:
    """Classify a post against the launch definition.

    Tests pass a stub ``backend`` to avoid real API calls. The orchestrator
    in Phase 5 will wrap this function as the ``classify_launch`` tool.
    """
    backend = backend or AnthropicBackend()
    raw = backend.classify(
        system=load_system_prompt(),
        user=_format_user_message(post_text, metadata or {}),
    )
    return ClassificationResult.model_validate(raw)
