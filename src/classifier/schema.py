from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LaunchType = Literal["product", "feature", "milestone", "program"]


class ClassificationResult(BaseModel):
    """Output of the launch classifier.

    Mirrors the schema documented in `docs/launch_definition.md` §6 and the
    tool schema used in `AnthropicBackend`. `launch_type` must be non-null iff
    `is_launch` is true — enforced below.
    """

    model_config = ConfigDict(extra="forbid")

    is_launch: bool
    confidence: float = Field(ge=0.0, le=1.0)
    launch_type: LaunchType | None
    reasoning: str = Field(min_length=1)

    @model_validator(mode="after")
    def _launch_type_matches_is_launch(self) -> ClassificationResult:
        if self.is_launch and self.launch_type is None:
            raise ValueError("launch_type must be set when is_launch is true")
        if not self.is_launch and self.launch_type is not None:
            raise ValueError("launch_type must be null when is_launch is false")
        return self
