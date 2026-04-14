"""Scryfall helpers for the commander workflow skeleton."""

from __future__ import annotations

import json
import random
from time import perf_counter, sleep
from pathlib import Path

import requests

from .constants import BUDGET_PRICE_FILTERS, COLOR_ORDER

ROOT = Path(__file__).resolve().parent.parent
TAGS_PATH = ROOT / "tools" / "scryfall_tags.json"


class ScryfallService:
    def __init__(
        self,
        tags_path: Path = TAGS_PATH,
        min_request_interval_seconds: float = 0.12,
    ) -> None:
        self.tags_path = tags_path
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_started_at = 0.0
        self._named_lookup_cache: dict[str, dict | None] = {}
        self._search_page_cache: dict[tuple[str, int], dict] = {}
        self._search_cards_cache: dict[tuple[str, int], list[dict]] = {}
        self._validate_query_cache: dict[
            tuple[str, int], tuple[bool, str, list[dict]]
        ] = {}

    def _respect_rate_limit(self) -> None:
        elapsed = perf_counter() - self._last_request_started_at
        if elapsed < self.min_request_interval_seconds:
            sleep(self.min_request_interval_seconds - elapsed)
        self._last_request_started_at = perf_counter()

    def _throttled_get(self, url: str, **kwargs) -> requests.Response:
        self._respect_rate_limit()
        return requests.get(url, **kwargs)

    @staticmethod
    def get_lowest_price(card: dict | None) -> str | None:
        if not card:
            return None

        prices = card.get("prices", {}) if isinstance(card.get("prices"), dict) else {}
        candidate_values: list[float] = []

        for key in ("usd", "usd_foil", "usd_etched"):
            raw_value = prices.get(key)
            if raw_value in (None, ""):
                continue
            try:
                candidate_values.append(float(raw_value))
            except (TypeError, ValueError):
                continue

        if not candidate_values:
            raw_value = card.get("usd")
            if raw_value in (None, ""):
                return None
            try:
                return f"{float(raw_value):.2f}"
            except (TypeError, ValueError):
                return str(raw_value)

        return f"{min(candidate_values):.2f}"

    @staticmethod
    def _summarize_card(card: dict) -> dict:
        return {
            "name": card.get("name"),
            "mana_cost": card.get("mana_cost"),
            "type": card.get("type_line"),
            "oracle_text": card.get("oracle_text", ""),
            "usd": ScryfallService.get_lowest_price(card),
            "set": (card.get("set") or "").upper(),
            "edhrec_rank": card.get("edhrec_rank"),
        }

    @staticmethod
    def _extract_error_message(exc: requests.RequestException) -> str:
        response = exc.response
        if response is not None:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            details = payload.get("details") or payload.get("error")
            if details:
                return str(details)
        return str(exc) or "Unknown Scryfall request error."

    def _search_cards_page(
        self,
        query: str,
        page: int = 1,
        timeout: float = 15.0,
    ) -> dict:
        cache_key = (query, page)
        cached = self._search_page_cache.get(cache_key)
        if cached is not None:
            return cached
        response = self._throttled_get(
            "https://api.scryfall.com/cards/search",
            params={
                "q": query,
                "page": page,
                "unique": "cards",
                "order": "edhrec",
                "dir": "asc",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._search_page_cache[cache_key] = payload
        return payload

    def lookup_card_by_name(self, name: str) -> dict | None:
        cache_key = name.strip().lower()
        if cache_key in self._named_lookup_cache:
            return self._named_lookup_cache[cache_key]
        try:
            response = self._throttled_get(
                "https://api.scryfall.com/cards/named",
                params={"exact": name},
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException:
            self._named_lookup_cache[cache_key] = None
            return None
        payload = response.json()
        self._named_lookup_cache[cache_key] = payload
        return payload

    def validate_commander_candidate(self, name: str) -> tuple[bool, str, dict | None]:
        card_data = self.lookup_card_by_name(name)
        if not card_data:
            return False, f'"{name}" was not found on Scryfall.', None

        if card_data.get("layout") == "art_series":
            return False, f'"{name}" is not a playable card.', card_data

        legalities = card_data.get("legalities", {})
        if legalities.get("commander") != "legal":
            return (
                False,
                f'"{card_data.get("name", name)}" is not legal in Commander.',
                card_data,
            )

        type_line = card_data.get("type_line", "")
        oracle_text = card_data.get("oracle_text", "")
        is_legendary_creature = "Legendary" in type_line and "Creature" in type_line
        can_be_commander = "can be your commander" in oracle_text.lower()

        if not (is_legendary_creature or can_be_commander):
            return (
                False,
                f'"{card_data.get("name", name)}" is legal in Commander but is not a valid commander by itself.',
                card_data,
            )

        return True, f'"{card_data.get("name", name)}" is a valid commander.', card_data

    def search_commander_candidates(self, query: str, limit: int = 10) -> list[dict]:
        try:
            response = self._throttled_get(
                "https://api.scryfall.com/cards/search",
                params={
                    "q": f"is:commander {query}",
                    "unique": "cards",
                    "order": "name",
                },
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        data = response.json()
        candidates = []
        for card in data.get("data", [])[:limit]:
            candidates.append(
                {
                    "name": card.get("name"),
                    "type_line": card.get("type_line"),
                    "oracle_text": card.get("oracle_text", ""),
                    "color_identity": card.get("color_identity", []),
                }
            )
        return candidates

    def get_random_commander_candidates(
        self,
        count: int = 8,
        max_duration_seconds: float = 5.0,
        request_timeout: float = 3.0,
        preferred_max_edhrec_rank: int = 2500,
    ) -> list[dict]:
        candidates: list[dict] = []
        fallback_candidates: list[dict] = []
        seen_names: set[str] = set()
        attempts = 0
        max_attempts = max(count * 8, 32)
        start = perf_counter()

        while (
            len(candidates) < count
            and attempts < max_attempts
            and (perf_counter() - start) < max_duration_seconds
        ):
            attempts += 1
            try:
                response = self._throttled_get(
                    "https://api.scryfall.com/cards/random",
                    params={"q": "is:commander game:paper legal:commander"},
                    timeout=request_timeout,
                )
                response.raise_for_status()
            except requests.RequestException:
                continue

            card = response.json()
            name = card.get("name")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            candidate = {
                "name": name,
                "type_line": card.get("type_line"),
                "oracle_text": card.get("oracle_text", ""),
                "color_identity": card.get("color_identity", []),
                "edhrec_rank": card.get("edhrec_rank"),
            }

            edhrec_rank = card.get("edhrec_rank")
            if isinstance(edhrec_rank, int) and edhrec_rank <= preferred_max_edhrec_rank:
                candidates.append(candidate)
            else:
                fallback_candidates.append(candidate)

        random.shuffle(candidates)
        if len(candidates) < count:
            random.shuffle(fallback_candidates)
            for candidate in fallback_candidates:
                if len(candidates) >= count:
                    break
                candidates.append(candidate)
        return candidates[:count]

    def search_cards(self, query: str, limit: int = 12) -> list[dict]:
        cache_key = (query, limit)
        cached = self._search_cards_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            all_cards: list[dict] = []
            page = 1
            has_more = True

            while has_more and len(all_cards) < limit:
                data = self._search_cards_page(query, page=page)
                page_cards = [
                    self._summarize_card(card) for card in data.get("data", [])
                ]
                all_cards.extend(page_cards)
                has_more = bool(data.get("has_more")) and len(all_cards) < limit
                page += 1
            result = all_cards[:limit]
            self._search_cards_cache[cache_key] = result
            return list(result)
        except requests.RequestException:
            return []

    def validate_search_query(
        self,
        query: str,
        preview_limit: int = 5,
    ) -> tuple[bool, str, list[dict]]:
        cache_key = (query, preview_limit)
        cached = self._validate_query_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            data = self._search_cards_page(query, page=1)
        except requests.RequestException as exc:
            result = (False, self._extract_error_message(exc), [])
            self._validate_query_cache[cache_key] = result
            return result

        preview_cards = [
            self._summarize_card(card) for card in data.get("data", [])[:preview_limit]
        ]
        if not preview_cards:
            result = (False, "Query returned no results.", [])
            self._validate_query_cache[cache_key] = result
            return result
        result = (True, "", preview_cards)
        self._validate_query_cache[cache_key] = result
        return result

    def load_tags(self) -> list[str]:
        with self.tags_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("tags", [])

    def extract_color_identity(self, card_data: dict | None) -> list[str]:
        if not card_data:
            return []
        cid = card_data.get("color_identity", [])
        return [color for color in COLOR_ORDER if color in cid]

    def is_card_within_cid(self, card_data: dict | None, deck_cid: list[str]) -> bool:
        if not card_data:
            return False
        return set(card_data.get("color_identity", [])).issubset(set(deck_cid))

    def get_budget_price_cap(self, budget_tier: str | None) -> float | None:
        price_filter = BUDGET_PRICE_FILTERS.get(budget_tier or "none")
        if not price_filter:
            return None
        try:
            _, raw_value = price_filter.split("<=", maxsplit=1)
            return float(raw_value)
        except (ValueError, TypeError):
            return None

    def is_card_within_budget(self, card_data: dict | None, budget_tier: str | None) -> bool:
        if not card_data:
            return False
        cap = self.get_budget_price_cap(budget_tier)
        if cap is None:
            return True
        raw_price = self.get_lowest_price(card_data)
        if raw_price in (None, ""):
            return False
        try:
            return float(raw_price) <= cap
        except (ValueError, TypeError):
            return False

    def build_query_for_tag(
        self,
        tag: str,
        cid: list[str],
        budget_tier: str | None,
    ) -> str:
        parts = ["game:paper", "legal:commander", f"otag:{tag}"]
        if cid:
            parts.append(f"id<={''.join(color.lower() for color in cid)}")
        price_filter = BUDGET_PRICE_FILTERS.get(budget_tier or "none")
        if price_filter:
            parts.append(price_filter)
        return " ".join(parts)

    def build_queries_for_tags(
        self,
        tags: list[str],
        cid: list[str],
        budget_tier: str | None,
    ) -> list[str]:
        return [
            self.build_query_for_tag(tag=tag, cid=cid, budget_tier=budget_tier)
            for tag in tags
        ]

    def normalize_candidate_query(
        self,
        query: str,
        cid: list[str],
        budget_tier: str | None,
    ) -> str | None:
        text = str(query or "").strip().strip('"').strip("'")
        if not text:
            return None

        text = " ".join(text.split())
        lowered = text.lower()
        prefixes: list[str] = []

        if "game:" not in lowered:
            prefixes.append("game:paper")
        if "legal:" not in lowered:
            prefixes.append("legal:commander")
        if cid and not any(
            token in lowered for token in ("id<=", "id=", "id>", "id<", "ci:", "color:")
        ):
            prefixes.append(f"id<={''.join(color.lower() for color in cid)}")

        price_filter = BUDGET_PRICE_FILTERS.get(budget_tier or "none")
        if price_filter and price_filter.lower() not in lowered and "eur<=" not in lowered:
            prefixes.append(price_filter)

        normalized = " ".join(prefixes + [text]).strip()
        return normalized or None
