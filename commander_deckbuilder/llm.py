"""OpenAI-backed helpers for running workflow agents."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from openai import OpenAI

from model_usage import print_usage, summarize_usage

from .models import (
    A3CategoryPlan,
    A4TurnResult,
    A5TurnResult,
    A6TurnResult,
    A1TurnResult,
    A2TurnResult,
    A3TagPrepResult,
    AgentPrompt,
    AgentUsageReport,
)


DEFAULT_MODEL = os.getenv("COMMANDER_AGENT_MODEL", "gpt-5-mini")


class AgentRunner:
    def __init__(self, model: str = DEFAULT_MODEL, echo_usage: bool = False) -> None:
        self.client = OpenAI()
        self.model = model
        self.echo_usage = echo_usage
        self.usage_history: list[AgentUsageReport] = []

    def run_prompt(self, prompt: AgentPrompt) -> dict[str, Any]:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)
        return self._parse_json_response(response.output_text)

    def _create_response(self, prompt: AgentPrompt):
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt.system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{prompt.user_prompt}\n\n"
                        f"Expected output contract:\n{prompt.expected_output}"
                    ),
                },
            ],
        )
        return response

    def run_a1_turn(self, prompt: AgentPrompt) -> A1TurnResult:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)

        try:
            payload = self._parse_json_response(response.output_text)
        except ValueError:
            return A1TurnResult(
                assistant_message=response.output_text.strip(),
                candidate_commander=None,
                done=False,
            )

        return A1TurnResult(
            assistant_message=str(payload.get("assistant_message", "")).strip(),
            candidate_commander=self._normalize_optional_string(
                payload.get("candidate_commander")
            ),
            commander_search_query=self._normalize_optional_string(
                payload.get("commander_search_query")
            ),
            random_commander_request=bool(payload.get("random_commander_request", False)),
            done=bool(payload.get("done", False)),
        )

    def run_a2_turn(self, prompt: AgentPrompt) -> A2TurnResult:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)

        try:
            payload = self._parse_json_response(response.output_text)
        except ValueError:
            return A2TurnResult(
                assistant_message=response.output_text.strip(),
                synergy_themes=[],
                budget_tier=None,
                category_queue=[],
                done=False,
            )

        return A2TurnResult(
            assistant_message=str(payload.get("assistant_message", "")).strip(),
            synergy_themes=self._normalize_string_list(payload.get("synergy_themes")),
            budget_tier=self._normalize_optional_string(payload.get("budget_tier")),
            category_queue=self._normalize_string_list(payload.get("category_queue")),
            done=bool(payload.get("done", False)),
        )

    def run_a3_tag_prep(self, prompt: AgentPrompt) -> A3TagPrepResult:
        payload = self.run_prompt(prompt)
        raw_mapping = payload.get("category_plans", payload.get("category_tags", {}))
        raw_theme_mapping = payload.get("synergy_theme_plans", {})
        normalized: dict[str, A3CategoryPlan] = {}
        if isinstance(raw_mapping, dict):
            for key, value in raw_mapping.items():
                category = str(key).strip().lower()
                if not isinstance(value, dict):
                    continue
                normalized[category] = A3CategoryPlan(
                    tags=self._normalize_string_list(value.get("tags")),
                    search_intents=self._normalize_string_list(value.get("search_intents")),
                    candidate_queries=self._normalize_string_list(
                        value.get("candidate_queries")
                    ),
                )
        normalized_theme_plans: dict[str, A3CategoryPlan] = {}
        if isinstance(raw_theme_mapping, dict):
            for key, value in raw_theme_mapping.items():
                theme = str(key).strip()
                if not theme or not isinstance(value, dict):
                    continue
                normalized_theme_plans[theme] = A3CategoryPlan(
                    tags=self._normalize_string_list(value.get("tags")),
                    search_intents=self._normalize_string_list(value.get("search_intents")),
                    candidate_queries=self._normalize_string_list(
                        value.get("candidate_queries")
                    ),
                )
        return A3TagPrepResult(
            category_plans=normalized,
            synergy_theme_plans=normalized_theme_plans,
        )

    def run_a4_turn(self, prompt: AgentPrompt) -> A4TurnResult:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)

        try:
            payload = self._parse_json_response(response.output_text)
        except ValueError:
            return A4TurnResult(
                assistant_message=response.output_text.strip(),
                recommended_card_names=[],
                brief_recommendation_notes=[],
            )

        return A4TurnResult(
            assistant_message=str(payload.get("assistant_message", "")).strip(),
            recommended_card_names=self._normalize_string_list(
                payload.get("recommended_card_names")
            ),
            brief_recommendation_notes=self._normalize_string_list(
                payload.get("brief_recommendation_notes")
            ),
        )

    def run_a5_turn(self, prompt: AgentPrompt) -> A5TurnResult:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)

        try:
            payload = self._parse_json_response(response.output_text)
        except ValueError:
            return A5TurnResult(
                assistant_message=response.output_text.strip(),
                done=False,
            )

        basic_counts: dict[str, int] = {}
        raw_basic_counts = payload.get("basic_land_counts", {})
        if isinstance(raw_basic_counts, dict):
            for key, value in raw_basic_counts.items():
                try:
                    basic_counts[str(key).strip()] = max(0, int(value))
                except (TypeError, ValueError):
                    continue

        proposed_count = payload.get("proposed_target_land_count")
        try:
            normalized_proposed_count = (
                None if proposed_count is None else int(proposed_count)
            )
        except (TypeError, ValueError):
            normalized_proposed_count = None

        return A5TurnResult(
            assistant_message=str(payload.get("assistant_message", "")).strip(),
            recommended_utility_land_names=self._normalize_string_list(
                payload.get("recommended_utility_land_names")
            ),
            proposed_target_land_count=normalized_proposed_count,
            utility_land_names=self._normalize_string_list(payload.get("utility_land_names")),
            dual_land_names=self._normalize_string_list(payload.get("dual_land_names")),
            tri_land_names=self._normalize_string_list(payload.get("tri_land_names")),
            fetch_land_names=self._normalize_string_list(payload.get("fetch_land_names")),
            basic_land_counts=basic_counts,
            done=bool(payload.get("done", False)),
        )

    def run_a6_turn(self, prompt: AgentPrompt) -> A6TurnResult:
        response = self._create_response(prompt)
        self._record_usage(prompt, response.usage)

        try:
            payload = self._parse_json_response(response.output_text)
        except ValueError:
            return A6TurnResult(
                assistant_message=response.output_text.strip(),
                recommendations_by_category={},
                brief_notes_by_category={},
            )

        recommendations_by_category: dict[str, list[str]] = {}
        raw_recommendations = payload.get("recommendations_by_category", {})
        if isinstance(raw_recommendations, dict):
            for key, value in raw_recommendations.items():
                category = str(key).strip().lower()
                recommendations_by_category[category] = self._normalize_string_list(value)

        cuts_by_category: dict[str, list[str]] = {}
        raw_cuts = payload.get("cuts_by_category", {})
        if isinstance(raw_cuts, dict):
            for key, value in raw_cuts.items():
                category = str(key).strip().lower()
                cuts_by_category[category] = self._normalize_string_list(value)

        brief_notes_by_category: dict[str, list[str]] = {}
        raw_notes = payload.get("brief_notes_by_category", {})
        if isinstance(raw_notes, dict):
            for key, value in raw_notes.items():
                category = str(key).strip().lower()
                brief_notes_by_category[category] = self._normalize_string_list(value)

        return A6TurnResult(
            assistant_message=str(payload.get("assistant_message", "")).strip(),
            recommendations_by_category=recommendations_by_category,
            cuts_by_category=cuts_by_category,
            brief_notes_by_category=brief_notes_by_category,
        )

    def get_usage_history(self) -> list[AgentUsageReport]:
        return list(self.usage_history)

    def get_usage_history_summary(self) -> list[dict[str, float | int | str]]:
        return [
            {
                "call_index": item.call_index,
                "agent_id": item.agent_id,
                "agent_name": item.agent_name,
                "model": item.model,
                "input_tokens": item.input_tokens,
                "cached_tokens": item.cached_tokens,
                "output_tokens": item.output_tokens,
                "reasoning_tokens": item.reasoning_tokens,
                "cost_usd": item.cost_usd,
            }
            for item in self.usage_history
        ]

    def get_total_usage_summary(self) -> dict[str, float | int | str]:
        if not self.usage_history:
            return {
                "model": self.model,
                "input_tokens": 0,
                "cached_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cost_usd": 0.0,
            }
        return {
            "model": self.model,
            "input_tokens": sum(item.input_tokens for item in self.usage_history),
            "cached_tokens": sum(item.cached_tokens for item in self.usage_history),
            "output_tokens": sum(item.output_tokens for item in self.usage_history),
            "reasoning_tokens": sum(item.reasoning_tokens for item in self.usage_history),
            "cost_usd": sum(item.cost_usd for item in self.usage_history),
        }

    def get_agent_usage_summary(self, agent_id: str) -> dict[str, float | int | str]:
        items = [item for item in self.usage_history if item.agent_id == agent_id]
        if not items:
            return {
                "agent_id": agent_id,
                "model": self.model,
                "call_count": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cost_usd": 0.0,
            }

        return {
            "agent_id": agent_id,
            "model": items[0].model,
            "call_count": len(items),
            "input_tokens": sum(item.input_tokens for item in items),
            "cached_tokens": sum(item.cached_tokens for item in items),
            "output_tokens": sum(item.output_tokens for item in items),
            "reasoning_tokens": sum(item.reasoning_tokens for item in items),
            "cost_usd": sum(item.cost_usd for item in items),
        }

    def _record_usage(self, prompt: AgentPrompt, usage: Any) -> None:
        summary = summarize_usage(self.model, usage)
        report = AgentUsageReport(
            call_index=len(self.usage_history) + 1,
            agent_id=prompt.agent_id,
            agent_name=prompt.agent_name,
            model=self.model,
            input_tokens=int(summary["input_tokens"]),
            cached_tokens=int(summary["cached_tokens"]),
            output_tokens=int(summary["output_tokens"]),
            reasoning_tokens=int(summary["reasoning_tokens"]),
            cost_usd=float(summary["cost_usd"]),
        )
        self.usage_history.append(report)

        if self.echo_usage:
            print(f"[Usage] {prompt.agent_id} {prompt.agent_name}", file=sys.stderr)
            print_usage(self.model, usage, file=sys.stderr)

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = str(value).split(",")
        return [str(item).strip() for item in items if str(item).strip()]

    @staticmethod
    def _parse_json_response(raw_text: str) -> dict[str, Any]:
        sanitized_raw = AgentRunner._strip_json_comments(raw_text)
        try:
            parsed = json.loads(sanitized_raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        for candidate in reversed(AgentRunner._extract_json_objects(raw_text)):
            sanitized_candidate = AgentRunner._strip_json_comments(candidate)
            try:
                parsed = json.loads(sanitized_candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        raise ValueError(f"Model did not return valid JSON: {raw_text}")

    @staticmethod
    def _extract_json_objects(raw_text: str) -> list[str]:
        objects: list[str] = []
        depth = 0
        start_index: int | None = None
        in_string = False
        escape = False

        for index, char in enumerate(raw_text):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                if depth == 0:
                    start_index = index
                depth += 1
            elif char == "}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start_index is not None:
                    objects.append(raw_text[start_index : index + 1])
                    start_index = None

        return objects

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        result: list[str] = []
        in_string = False
        escape = False
        index = 0
        length = len(text)

        while index < length:
            char = text[index]

            if in_string:
                result.append(char)
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                index += 1
                continue

            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue

            if char == "/" and index + 1 < length:
                next_char = text[index + 1]
                if next_char == "/":
                    index += 2
                    while index < length and text[index] not in "\r\n":
                        index += 1
                    continue
                if next_char == "*":
                    index += 2
                    while index + 1 < length and not (
                        text[index] == "*" and text[index + 1] == "/"
                    ):
                        index += 1
                    index = min(index + 2, length)
                    continue

            result.append(char)
            index += 1

        return "".join(result)
