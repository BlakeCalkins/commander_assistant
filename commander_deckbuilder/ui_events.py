"""Structured UI events for the local app."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .card_view_models import UICard


@dataclass
class ChatMessageEvent:
    role: Literal["assistant", "user", "system"]
    text: str
    agent_id: str | None = None


@dataclass
class PromptEvent:
    prompt_id: str
    kind: Literal["text", "number", "choice"] = "text"
    label: str = ""
    placeholder: str | None = None
    choices: list[str] = field(default_factory=list)


@dataclass
class RecommendationBatchEvent:
    batch_id: str
    agent_id: str
    title: str
    category: str
    theme_focus: str | None = None
    action_mode: Literal["add", "pick_one", "keep_or_cut", "confirm_one"] = "add"
    cards: list[UICard] = field(default_factory=list)
    allow_skip: bool = True


@dataclass
class DeckStateEvent:
    commander: str | None
    category_counts: dict[str, int]
    total_non_commander_cards: int
    decklist_preview: list[str] = field(default_factory=list)


@dataclass
class PhaseEvent:
    phase_id: str
    title: str


UIEvent = (
    ChatMessageEvent
    | PromptEvent
    | RecommendationBatchEvent
    | DeckStateEvent
    | PhaseEvent
)
