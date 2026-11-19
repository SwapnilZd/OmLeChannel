"""Template dataclass — lives here to avoid circular imports between __init__ and template modules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Template:
    name: str
    fill_prompt: Callable[[dict], str]
    validate: Callable[[dict], dict]
    render: Callable[[dict, str, str, str], str]
