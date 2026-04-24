from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.classifier import CLASSIFIER_TOOL_SCHEMA, ClassificationResult, classify_launch
from src.classifier.prompt import load_prompt_version, load_system_prompt


class StubBackend:
    """Test double — records calls and returns a scripted response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def classify(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        return self.response


# --- ClassificationResult schema -------------------------------------------


def test_result_rejects_launch_type_when_not_a_launch() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            is_launch=False, confidence=0.9, launch_type="product", reasoning="x"
        )


def test_result_rejects_missing_launch_type_when_is_launch() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            is_launch=True, confidence=0.9, launch_type=None, reasoning="x"
        )


def test_result_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            is_launch=True, confidence=1.5, launch_type="product", reasoning="x"
        )


def test_result_rejects_empty_reasoning() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            is_launch=True, confidence=0.9, launch_type="product", reasoning=""
        )


def test_result_accepts_valid_negative() -> None:
    r = ClassificationResult(
        is_launch=False, confidence=0.95, launch_type=None, reasoning="teaser"
    )
    assert r.is_launch is False
    assert r.launch_type is None


# --- classify_launch --------------------------------------------------------


def test_classify_launch_happy_path() -> None:
    backend = StubBackend(
        {
            "is_launch": True,
            "confidence": 0.95,
            "launch_type": "product",
            "reasoning": "Launch vocabulary 'Introducing' + demo video.",
        }
    )
    result = classify_launch("Introducing Acme Rocket.", {"handle": "acme"}, backend=backend)
    assert isinstance(result, ClassificationResult)
    assert result.is_launch is True
    assert result.launch_type == "product"


def test_classify_launch_passes_metadata_into_user_message() -> None:
    backend = StubBackend(
        {
            "is_launch": False,
            "confidence": 0.9,
            "launch_type": None,
            "reasoning": "Teaser.",
        }
    )
    classify_launch("something coming soon", {"handle": "teaser"}, backend=backend)
    assert len(backend.calls) == 1
    _, user_msg = backend.calls[0]
    assert "something coming soon" in user_msg
    assert "teaser" in user_msg  # metadata handle made it into the payload


def test_classify_launch_raises_on_invalid_backend_output() -> None:
    backend = StubBackend(
        {
            "is_launch": True,
            "confidence": 0.9,
            "launch_type": None,  # invalid: required when is_launch=True
            "reasoning": "x",
        }
    )
    with pytest.raises(ValidationError):
        classify_launch("x", backend=backend)


def test_classify_launch_uses_loaded_system_prompt() -> None:
    backend = StubBackend(
        {
            "is_launch": True,
            "confidence": 0.9,
            "launch_type": "product",
            "reasoning": "x",
        }
    )
    classify_launch("Introducing X.", backend=backend)
    system_sent, _ = backend.calls[0]
    assert "You are a classifier" in system_sent
    assert "is_launch" in system_sent


# --- prompt loader ---------------------------------------------------------


def test_load_system_prompt_strips_metadata_header() -> None:
    prompt = load_system_prompt()
    # The file title and Version line should not leak into the system prompt body
    assert "# Launch Classifier" not in prompt
    assert "**Version:**" not in prompt
    # But the instruction content must be present
    assert "You are a classifier" in prompt


def test_load_prompt_version_matches_file() -> None:
    version = load_prompt_version()
    assert version == "v1"


# --- tool schema sanity ----------------------------------------------------


def test_tool_schema_enumerates_launch_types() -> None:
    enum = CLASSIFIER_TOOL_SCHEMA["input_schema"]["properties"]["launch_type"]["enum"]
    assert set(enum) == {"product", "feature", "milestone", "program", None}


def test_tool_schema_required_fields_match_model() -> None:
    required = set(CLASSIFIER_TOOL_SCHEMA["input_schema"]["required"])
    assert required == {"is_launch", "confidence", "launch_type", "reasoning"}
