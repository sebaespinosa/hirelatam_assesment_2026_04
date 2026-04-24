"""Launch classifier — OpenAI-backed structured classification.

Public surface: ``classify_launch(post_text, metadata) -> ClassificationResult``.
The Phase 5 orchestrator will expose this as the ``classify_launch`` tool; the
JSON Schema used to force structured output lives at
``CLASSIFIER_OUTPUT_SCHEMA``.

Why ``response_format`` and not tool use: for a single-tool classifier, the
Structured Outputs JSON-schema mode is a cleaner fit than function calling —
the entire response body *is* the classification, with no tool-call wrapper.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from src.classifier.prompt import load_system_prompt
from src.classifier.schema import ClassificationResult

DEFAULT_MODEL = "gpt-4o-mini"

CLASSIFIER_OUTPUT_SCHEMA: dict[str, Any] = {
    "name": "classification_result",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_launch": {"type": "boolean"},
            "confidence": {"type": "number"},
            "launch_type": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": ["product", "feature", "milestone", "program"],
                    },
                    {"type": "null"},
                ],
            },
            "reasoning": {"type": "string"},
        },
        "required": ["is_launch", "confidence", "launch_type", "reasoning"],
    },
}


class ClassifierBackend(Protocol):
    """Transport-agnostic interface; tests substitute a stub."""

    def classify(self, *, system: str, user: str) -> dict[str, Any]: ...


class OpenAIBackend:
    """Real backend. Uses OpenAI Structured Outputs (strict JSON Schema).

    Prompt caching is automatic on the provider side when the system prompt
    exceeds ~1024 tokens and stays byte-identical across calls — no flags to
    set, but do not mutate the system prompt per-call.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        if client is None:
            from openai import OpenAI  # lazy import so tests can skip the env var

            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.client = client
        self.model = model

    def classify(self, *, system: str, user: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": CLASSIFIER_OUTPUT_SCHEMA,
            },
        )
        message = response.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError(f"Model refused to classify: {refusal}")
        content = message.content
        if not content:
            raise RuntimeError(
                f"Empty content in classifier response; finish_reason="
                f"{response.choices[0].finish_reason!r}"
            )
        return json.loads(content)


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
    backend = backend or OpenAIBackend()
    raw = backend.classify(
        system=load_system_prompt(),
        user=_format_user_message(post_text, metadata or {}),
    )
    return ClassificationResult.model_validate(raw)
