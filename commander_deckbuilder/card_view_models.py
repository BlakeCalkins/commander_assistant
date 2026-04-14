"""UI-facing card view models and transformers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import DeckCard
from .scryfall import ScryfallService


@dataclass
class UICard:
    name: str
    image_url: str | None = None
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    usd: str | None = None
    edhrec_rank: int | None = None
    source_label: str | None = None
    note: str | None = None
    category: str | None = None
    scryfall_uri: str | None = None


def ui_card_from_scryfall(
    card: dict[str, Any] | None,
    *,
    note: str | None = None,
    category: str | None = None,
    source_label: str | None = None,
) -> UICard | None:
    if not card:
        return None
    return UICard(
        name=str(card.get("name") or ""),
        image_url=ScryfallService.get_card_image_url(card),
        mana_cost=card.get("mana_cost"),
        type_line=card.get("type_line") or card.get("type"),
        oracle_text=card.get("oracle_text"),
        usd=ScryfallService.get_lowest_price(card) or card.get("usd"),
        edhrec_rank=card.get("edhrec_rank"),
        source_label=source_label,
        note=note,
        category=category,
        scryfall_uri=card.get("scryfall_uri"),
    )


def ui_card_from_summary(
    card: dict[str, Any] | None,
    *,
    note: str | None = None,
    category: str | None = None,
    source_label: str | None = None,
) -> UICard | None:
    if not card:
        return None
    return UICard(
        name=str(card.get("name") or ""),
        image_url=card.get("image_url"),
        mana_cost=card.get("mana_cost"),
        type_line=card.get("type") or card.get("type_line"),
        oracle_text=card.get("oracle_text"),
        usd=card.get("usd"),
        edhrec_rank=card.get("edhrec_rank"),
        source_label=source_label,
        note=note,
        category=category,
        scryfall_uri=card.get("scryfall_uri"),
    )


def ui_card_from_deck_card(
    card: DeckCard,
    *,
    image_url: str | None = None,
    note: str | None = None,
    source_label: str | None = None,
) -> UICard:
    return UICard(
        name=card.name,
        image_url=image_url,
        mana_cost=card.mana_cost,
        type_line=card.type_line,
        oracle_text=card.oracle_text,
        usd=card.usd,
        edhrec_rank=card.edhrec_rank,
        source_label=source_label or card.source,
        note=note,
        category=card.category,
    )
