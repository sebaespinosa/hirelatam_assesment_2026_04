"""Load the versioned classifier system prompt from `prompts/launch_classifier.md`."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "launch_classifier.md"
PROMPT_NAME = "launch_classifier"

_SYSTEM_PROMPT_MARKER = "## System Prompt"
_VERSION_RE = re.compile(r"\*\*Version:\*\*\s*(\S+)")


@cache
def load_prompt_file() -> str:
    return PROMPT_PATH.read_text()


def load_system_prompt() -> str:
    """Return the prompt body that should be sent as the ``system`` message.

    Strips the file header (title + YAML-ish metadata) so only the instruction
    content below ``## System Prompt`` is sent to the model.
    """
    content = load_prompt_file()
    idx = content.find(_SYSTEM_PROMPT_MARKER)
    if idx == -1:
        return content.strip()
    body = content[idx + len(_SYSTEM_PROMPT_MARKER) :]
    return body.strip()


def load_prompt_version() -> str:
    content = load_prompt_file()
    match = _VERSION_RE.search(content)
    return match.group(1) if match else "unknown"
