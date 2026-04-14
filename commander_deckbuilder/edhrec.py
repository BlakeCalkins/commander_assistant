"""EDHREC helpers for the commander workflow."""

from __future__ import annotations

from tools.edhrec_scraper import pull_commander_card_recommendations


class EDHRECService:
    def get_commander_recommendations(self, commander_name: str) -> dict:
        return pull_commander_card_recommendations(commander_name)
