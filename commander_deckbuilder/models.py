"""Dataclasses for workflow state and agent prompt payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .constants import ALL_DECK_CATEGORIES


@dataclass
class DeckCard:
    name: str
    category: str
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    usd: str | None = None
    set_code: str | None = None
    edhrec_rank: int | None = None
    source_query: str | None = None
    source: str = "manual"

    def to_export_line(self, is_commander: bool = False) -> str:
        return f"1 {self.name}{' *CMDR*' if is_commander else ''}"


@dataclass
class AgentPrompt:
    agent_id: str
    agent_name: str
    system_prompt: str
    user_prompt: str
    expected_output: str


@dataclass
class A1TurnResult:
    assistant_message: str
    candidate_commander: str | None = None
    commander_search_query: str | None = None
    random_commander_request: bool = False
    done: bool = False


@dataclass
class A2TurnResult:
    assistant_message: str
    synergy_themes: list[str] = field(default_factory=list)
    budget_tier: str | None = None
    category_queue: list[str] = field(default_factory=list)
    done: bool = False


@dataclass
class A3TagPrepResult:
    category_plans: dict[str, "A3CategoryPlan"] = field(default_factory=dict)
    synergy_theme_plans: dict[str, "A3CategoryPlan"] = field(default_factory=dict)


@dataclass
class A3CategoryPlan:
    tags: list[str] = field(default_factory=list)
    search_intents: list[str] = field(default_factory=list)
    candidate_queries: list[str] = field(default_factory=list)
    validated_preview_cards: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class A4TurnResult:
    assistant_message: str
    recommended_card_names: list[str] = field(default_factory=list)
    brief_recommendation_notes: list[str] = field(default_factory=list)


@dataclass
class A5TurnResult:
    assistant_message: str
    recommended_utility_land_names: list[str] = field(default_factory=list)
    proposed_target_land_count: int | None = None
    utility_land_names: list[str] = field(default_factory=list)
    dual_land_names: list[str] = field(default_factory=list)
    tri_land_names: list[str] = field(default_factory=list)
    fetch_land_names: list[str] = field(default_factory=list)
    basic_land_counts: dict[str, int] = field(default_factory=dict)
    done: bool = False


@dataclass
class A6TurnResult:
    assistant_message: str
    recommendations_by_category: dict[str, list[str]] = field(default_factory=dict)
    cuts_by_category: dict[str, list[str]] = field(default_factory=dict)
    brief_notes_by_category: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class AgentUsageReport:
    call_index: int
    agent_id: str
    agent_name: str
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_usd: float


@dataclass
class SearchPlan:
    category: str
    selected_tags: list[str] = field(default_factory=list)
    search_intents: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    recommended_cards: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeckState:
    commander: str | None = None
    cid: list[str] = field(default_factory=list)
    budget_tier: str | None = None
    synergy_themes: list[str] = field(default_factory=list)
    category_queue: list[str] = field(default_factory=list)
    category_tags: dict[str, A3CategoryPlan] = field(default_factory=dict)
    synergy_theme_plans: dict[str, A3CategoryPlan] = field(default_factory=dict)
    decklist: dict[str, list[DeckCard]] = field(
        default_factory=lambda: {category: [] for category in ALL_DECK_CATEGORIES}
    )
    card_count: int = 1
    search_history: list[SearchPlan] = field(default_factory=list)

    def add_card(self, card: DeckCard) -> None:
        cards = self.decklist.setdefault(card.category, [])
        is_basic_land = (
            card.category == "lands"
            and "basic" in (card.type_line or "").lower()
        )
        if not is_basic_land and any(existing.name.lower() == card.name.lower() for existing in cards):
            return
        cards.append(card)
        if card.category != "commander":
            self.card_count += 1

    def has_card(self, card_name: str) -> bool:
        lowered = card_name.lower()
        return any(
            existing.name.lower() == lowered
            for cards in self.decklist.values()
            for existing in cards
        )

    def total_non_commander_cards(self) -> int:
        return sum(
            len(cards)
            for category, cards in self.decklist.items()
            if category != "commander"
        )

    def remaining_slots(self) -> int:
        return max(0, 99 - self.total_non_commander_cards())

    def category_counts(self) -> dict[str, int]:
        return {category: len(cards) for category, cards in self.decklist.items()}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decklist"] = {
            category: [asdict(card) for card in cards]
            for category, cards in self.decklist.items()
        }
        return data
