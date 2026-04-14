"""CLI workflow implementation for the Commander deck-building skeleton."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from pprint import pformat
import re

from .agents import (
    build_tag_prep_prompt,
    build_completion_prompt,
    build_completion_prompt_with_candidates,
    build_export_prompt,
    build_intake_prompt,
    build_lands_final_prompt,
    build_lands_intake_prompt,
    build_search_ranking_prompt,
    build_strategy_prompt_with_context,
)
from .constants import ALL_DECK_CATEGORIES, BUDGET_TIER_LABELS, CATEGORY_ORDER
from .edhrec import EDHRECService
from .llm import AgentRunner
from .models import AgentPrompt, DeckCard, DeckState, SearchPlan
from .models import A3CategoryPlan
from .scryfall import ScryfallService
from .agents import build_edhrec_opening_prompt

ROOT = Path(__file__).resolve().parent.parent
A5_EXAMPLES_PATH = ROOT / "docs" / "a5_landbase_examples.md"
DECKLIST_OUTPUT_PATH = ROOT / "decklist.txt"


class CommanderDeckWorkflow:
    def __init__(
        self,
        scryfall: ScryfallService | None = None,
        edhrec: EDHRECService | None = None,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.scryfall = scryfall or ScryfallService()
        self.edhrec = edhrec or EDHRECService()
        self.agent_runner = agent_runner or AgentRunner()
        self.state = DeckState()

    def run(self) -> DeckState:
        print("Commander Deckbuilding AI Skeleton")
        print("Workflow source: commander_deckbuilding_flow.md")
        print("A1, A2, silent A3, A4, and A5 are model-backed. A6-A7 are still stubbed.\n")

        if self.choose_start_mode() == "a5":
            self.run_a5_only_mode()
            return self.state

        self.phase_1_commander_selection()
        self.phase_2_strategy_planning()
        self.phase_3_tag_preparation()
        self.phase_4_edhrec_opening_recommendations()
        self.phase_4_card_discovery_loop()

        if self.choose_next_step() == "full":
            self.phase_5_lands()
            if self.choose_post_lands_step() == "full":
                self.phase_6_batch_completion()

        self.phase_7_export()
        return self.state

    def choose_start_mode(self) -> str:
        choice = input(
            "Start mode: [A] full workflow, [B] skip to A5 lands testing: "
        ).strip().lower()
        return "a5" if choice in {"b", "a5", "skip", "skip to a5"} else "full"

    def run_a5_only_mode(self) -> None:
        print("\n=== Direct A5 Testing Mode ===")
        self._prompt_a5_test_commander()
        for category in ALL_DECK_CATEGORIES:
            if category != "commander":
                self.state.decklist[category] = []
        self.state.search_history = []
        self.state.card_count = len(self.state.decklist["commander"])
        commander_cid = list(self.state.cid)
        self.state.cid = self._prompt_color_identity(commander_cid)
        self.state.budget_tier = self._prompt_budget_tier()
        self.state.synergy_themes = self._prompt_synergy_themes()
        print(
            "Configured A5 test state: "
            f"commander={self.state.commander or 'None'}, "
            f"CID={''.join(self.state.cid) or 'C'}, "
            f"budget={self.state.budget_tier}, "
            f"themes={self.state.synergy_themes or ['None']}"
        )
        self.phase_5_lands()

    def phase_1_commander_selection(self) -> None:
        print("=== Commander Selection (A1) ===")

        conversation: list[dict[str, str]] = []
        validation_feedback: str | None = None
        search_feedback: str | None = None
        pending_candidate_commander: str | None = None

        while True:
            prompt = build_intake_prompt(
                conversation=conversation,
                validation_feedback=validation_feedback,
                search_feedback=search_feedback,
            )
            turn = self.agent_runner.run_a1_turn(prompt)

            if turn.assistant_message:
                print(f"A1: {turn.assistant_message}")
                conversation.append({"role": "assistant", "content": turn.assistant_message})

            if turn.random_commander_request and not (
                search_feedback and search_feedback.startswith("Random commander pool from Scryfall:")
            ):
                candidates = self.scryfall.get_random_commander_candidates(count=8)
                search_feedback = self._format_random_commander_feedback(candidates)
                validation_feedback = None
                pending_candidate_commander = None
                continue

            if turn.commander_search_query:
                candidates = self.scryfall.search_commander_candidates(
                    turn.commander_search_query
                )
                search_feedback = self._format_commander_search_feedback(
                    turn.commander_search_query,
                    candidates,
                )
                validation_feedback = None
                pending_candidate_commander = None
                continue

            if turn.candidate_commander and turn.done:
                is_valid, message, card_data = self.scryfall.validate_commander_candidate(
                    turn.candidate_commander
                )
                if is_valid and card_data:
                    self._finalize_confirmed_commander(
                        card_data,
                        fallback_name=turn.candidate_commander,
                    )
                    return

                validation_feedback = message
                search_feedback = None
                pending_candidate_commander = None
                continue

            if turn.candidate_commander and not turn.done:
                pending_candidate_commander = turn.candidate_commander
                validation_feedback = None

            validation_feedback = None
            user_message = self._ask_non_empty("You: ")
            if pending_candidate_commander and self._is_affirmative(user_message):
                is_valid, message, card_data = self.scryfall.validate_commander_candidate(
                    pending_candidate_commander
                )
                if is_valid and card_data:
                    self._finalize_confirmed_commander(
                        card_data,
                        fallback_name=pending_candidate_commander,
                    )
                    return
                validation_feedback = message
                search_feedback = None
                pending_candidate_commander = None
                continue
            conversation.append({"role": "user", "content": user_message})

    def phase_2_strategy_planning(self) -> None:
        print("\n=== Strategy Planning (A2) ===")

        conversation: list[dict[str, str]] = []
        validation_feedback: str | None = None

        while True:
            prompt = build_strategy_prompt_with_context(
                state=self.state,
                conversation=conversation,
                validation_feedback=validation_feedback,
            )
            turn = self.agent_runner.run_a2_turn(prompt)

            if turn.assistant_message:
                print(f"A2: {turn.assistant_message}")
                conversation.append({"role": "assistant", "content": turn.assistant_message})

            if turn.done:
                ok, message, cleaned = self._validate_a2_submission(
                    turn.synergy_themes,
                    turn.budget_tier,
                    turn.category_queue,
                )
                if ok:
                    self.state.synergy_themes = cleaned["synergy_themes"]
                    self.state.budget_tier = cleaned["budget_tier"]
                    self.state.category_queue = cleaned["category_queue"]
                    print(
                        "Confirmed strategy: "
                        f"themes={self.state.synergy_themes}, "
                        f"budget={self.state.budget_tier}, "
                        f"categories={self.state.category_queue}"
                    )
                    self._show_agent_usage_summary("A2", "Strategy Agent")
                    return

                validation_feedback = message
                continue

            validation_feedback = None
            user_message = self._ask_non_empty("You: ")
            conversation.append({"role": "user", "content": user_message})

    def phase_3_tag_preparation(self) -> None:
        all_tags = self.scryfall.load_tags()
        attempts = 0
        validation_feedback: str | None = None

        while attempts < 2:
            attempts += 1
            prompt = build_tag_prep_prompt(
                self.state,
                all_tags,
                validation_feedback=validation_feedback,
            )
            result = self.agent_runner.run_a3_tag_prep(prompt)
            ok, message, cleaned, cleaned_theme_plans = self._validate_a3_category_plans(
                result.category_plans,
                result.synergy_theme_plans,
                all_tags,
            )
            if ok:
                self.state.category_tags = cleaned
                self.state.synergy_theme_plans = cleaned_theme_plans
                print("\nPrepared search plans by category:")
                for category in self.state.category_queue:
                    plan = self.state.category_tags.get(category, A3CategoryPlan())
                    print(f"  {category}:")
                    print(f"    tags: {plan.tags}")
                    print(f"    intents: {plan.search_intents}")
                    print(f"    queries: {plan.candidate_queries}")
                if self.state.synergy_theme_plans:
                    print("\nPrepared synergy search plans by theme:")
                    for theme, plan in self.state.synergy_theme_plans.items():
                        print(f"  {theme}:")
                        print(f"    tags: {plan.tags}")
                        print(f"    intents: {plan.search_intents}")
                        print(f"    queries: {plan.candidate_queries}")
                if message:
                    print("\nA3 query validation notes:")
                    print(message)
                self._show_agent_usage_summary("A3", "Tag Prep Agent")
                return

            validation_feedback = message

        self.state.category_tags = {
            category: A3CategoryPlan() for category in self.state.category_queue
        }
        self.state.synergy_theme_plans = {}
        print("\nA3 tag preparation did not return valid search plans. Continuing with empty plans.")
        self._show_agent_usage_summary("A3", "Tag Prep Agent")

    def phase_4_edhrec_opening_recommendations(self) -> None:
        print("\n=== EDHREC Opening Recommendations (A4) ===")
        if not self.state.commander:
            print("Skipping EDHREC opening recommendations: commander is not set.")
            return

        try:
            data = self.edhrec.get_commander_recommendations(self.state.commander)
        except Exception as exc:
            print(f"Skipping EDHREC opening recommendations: {exc}")
            return

        candidate_pool = self._build_edhrec_candidate_pool(data)
        target_recommendation_count = self._determine_edhrec_target_count(len(candidate_pool))
        if not candidate_pool or not target_recommendation_count:
            print("No usable EDHREC recommendations were available.")
            return

        prompt = build_edhrec_opening_prompt(
            self.state,
            data.get("url", ""),
            self._build_edhrec_candidate_pool_summary(candidate_pool),
            self._current_deck_names(),
            target_recommendation_count,
        )
        turn = self.agent_runner.run_a4_turn(prompt)
        recommended_cards = self._resolve_a4_recommendations(
            candidate_pool,
            turn.recommended_card_names,
            target_recommendation_count,
        )
        note_lookup = self._pair_notes_with_names(
            turn.recommended_card_names,
            turn.brief_recommendation_notes,
        )

        if turn.assistant_message:
            print(f"A4: {turn.assistant_message}")

        if recommended_cards:
            print("EDHREC recommendations:")
            for index, card in enumerate(recommended_cards, start=1):
                note = note_lookup.get(card.get("name", "").lower(), "")
                note_suffix = f" | {note}" if note else ""
                source = card.get("edhrec_source", "edhrec")
                synergy = card.get("edhrec_synergy")
                synergy_suffix = f" | Synergy {synergy}" if synergy is not None else ""
                print(
                    f"  {index}. {card.get('name')} | ${card.get('usd') or '?'} | "
                    f"{source}{synergy_suffix} | Decks {card.get('edhrec_num_decks')}{note_suffix}"
                )
        else:
            print("No usable EDHREC recommendations were returned by A4.")

        self._add_cards_for_category("synergy", recommended_cards, source_query="edhrec-opening")

    def phase_4_card_discovery_loop(self) -> None:
        for category in self.state.category_queue:
            print(f"\n=== Category: {category} ===")
            self._run_category_search(category)
        self._show_agent_usage_summary("A4", "Recommendation Agent")

    def choose_next_step(self) -> str:
        print("\nPhase 4 complete.")
        choice = input("Choose next step: [A] full completion, [B] export now: ").strip().lower()
        return "full" if choice in {"a", "full"} else "export"

    def choose_post_lands_step(self) -> str:
        print("\nPhase 5 complete.")
        choice = input("Choose next step: [A] run A6 completion, [B] export now: ").strip().lower()
        return "full" if choice in {"a", "full"} else "export"

    def phase_5_lands(self) -> None:
        print("\n=== Lands ===")
        utility_candidates = self._build_utility_land_candidates()
        color_pip_counts = self._calculate_color_pip_counts()
        average_mana_value = self._calculate_average_mana_value()
        example_reference = self._load_a5_examples_reference()

        intake_prompt = build_lands_intake_prompt(
            state=self.state,
            utility_candidates=self._summarize_land_candidates(utility_candidates),
            average_mana_value=average_mana_value,
            example_reference=example_reference,
        )
        intake_turn = self.agent_runner.run_a5_turn(intake_prompt)
        if intake_turn.assistant_message:
            print(f"A5: {intake_turn.assistant_message}")
        if intake_turn.recommended_utility_land_names:
            print("Utility land recommendations:")
            for name in intake_turn.recommended_utility_land_names:
                card = next(
                    (candidate for candidate in utility_candidates if candidate.get("name", "").lower() == name.lower()),
                    None,
                )
                price = card.get("usd") if card else None
                print(f"  - {name}{f' | ${price}' if price else ''}")

        selected_utility_land_names = self._collect_a5_utility_selection(
            utility_candidates,
            intake_turn.recommended_utility_land_names,
        )
        confirmed_target_land_count = self._confirm_target_land_count(
            intake_turn.proposed_target_land_count or 37,
            average_mana_value,
        )

        dual_candidates_by_pair = self._build_dual_land_candidates_by_pair()
        tri_candidates = self._build_tri_land_candidates()
        fetch_candidates = self._build_fetch_land_candidates()

        final_prompt = build_lands_final_prompt(
            state=self.state,
            selected_utility_land_names=selected_utility_land_names,
            confirmed_target_land_count=confirmed_target_land_count,
            utility_candidates=self._summarize_land_candidates(utility_candidates),
            dual_candidates_by_pair={
                pair: self._summarize_land_candidates(cards)
                for pair, cards in dual_candidates_by_pair.items()
            },
            tri_candidates=self._summarize_land_candidates(tri_candidates),
            fetch_candidates=self._summarize_land_candidates(fetch_candidates),
            color_pip_counts=color_pip_counts,
            average_mana_value=average_mana_value,
            example_reference=example_reference,
        )
        final_turn = self.agent_runner.run_a5_turn(final_prompt)
        if final_turn.assistant_message:
            print(f"A5: {final_turn.assistant_message}")

        land_cards = self._finalize_a5_land_package(
            selected_utility_land_names=selected_utility_land_names,
            target_land_count=confirmed_target_land_count,
            utility_candidates=utility_candidates,
            dual_candidates_by_pair=dual_candidates_by_pair,
            tri_candidates=tri_candidates,
            fetch_candidates=fetch_candidates,
            final_turn=final_turn,
            color_pip_counts=color_pip_counts,
        )
        self._replace_lands_decklist(land_cards)
        self._print_final_landbase(land_cards)
        self._show_agent_usage_summary("A5", "Lands Agent")

    def phase_6_batch_completion(self) -> None:
        print("\n=== Batch Completion ===")
        remaining_slots = self.state.remaining_slots()
        overfull_count = max(0, self.state.total_non_commander_cards() - 99)
        print(f"Remaining non-commander slots: {remaining_slots}")
        if remaining_slots <= 0 and overfull_count <= 0:
            print("Deck is already exactly at 99 non-commander cards.")
            return

        mode = "cut" if overfull_count > 0 else "add"
        target_fill_counts = (
            {}
            if mode == "cut"
            else self._determine_a6_target_fill_counts(remaining_slots)
        )
        target_cut_counts = (
            self._determine_a6_target_cut_counts(overfull_count)
            if mode == "cut"
            else {}
        )
        candidate_pools_by_category = (
            {}
            if mode == "cut"
            else self._build_a6_candidate_pools(target_fill_counts)
        )
        current_deck_summary_by_category = self._build_a6_current_deck_summary()

        if mode == "add" and not any(candidate_pools_by_category.values()):
            print("No usable completion candidates were available.")
            return
        if mode == "cut" and not any(current_deck_summary_by_category.values()):
            print("No removable non-commander cards were available.")
            return

        prompt = build_completion_prompt_with_candidates(
            state=self.state,
            mode=mode,
            target_fill_counts=target_fill_counts,
            target_cut_counts=target_cut_counts,
            current_deck_summary_by_category=current_deck_summary_by_category,
            candidate_pools_by_category={
                category: self._build_candidate_pool_summary(pool)
                for category, pool in candidate_pools_by_category.items()
            },
            current_deck_names=self._current_deck_names(),
        )
        turn = self.agent_runner.run_a6_turn(prompt)

        if turn.assistant_message:
            print(f"A6: {turn.assistant_message}")

        if mode == "add":
            resolved_by_category = self._resolve_a6_recommendations(
                candidate_pools_by_category,
                turn.recommendations_by_category,
                target_fill_counts,
            )
            total_recommended = self._print_a6_grouped_cards(
                "recommendations",
                resolved_by_category,
                turn.recommendations_by_category,
                turn.brief_notes_by_category,
            )
            if not total_recommended:
                print("A6 did not return any usable completion recommendations.")
                return

            removed_names = {
                name.lower() for name in self._read_card_name_lines(
                    "Enter recommended cards to remove before adding, one per line. Press Enter on a blank line to keep all.\nRemove card: "
                )
            }
            for category, cards in resolved_by_category.items():
                filtered_cards = [
                    card for card in cards if str(card.get("name", "")).lower() not in removed_names
                ]
                self._add_resolved_cards(category, filtered_cards, source_query="a6-completion")
        else:
            cuts_by_category = self._resolve_a6_cuts(
                current_deck_summary_by_category,
                turn.cuts_by_category,
                target_cut_counts,
            )
            total_cuts = self._print_a6_grouped_cards(
                "cuts",
                cuts_by_category,
                turn.cuts_by_category,
                turn.brief_notes_by_category,
            )
            if not total_cuts:
                print("A6 did not return any usable cut recommendations.")
                return

            kept_names = {
                name.lower() for name in self._read_card_name_lines(
                    "Enter recommended cut cards to keep instead of removing, one per line. Press Enter on a blank line to accept all cuts.\nKeep card: "
                )
            }
            cut_names = [
                str(card.get("name", "")).lower()
                for cards in cuts_by_category.values()
                for card in cards
                if str(card.get("name", "")).lower() not in kept_names
            ]
            self._remove_cards_by_name(cut_names)

        self._write_decklist_snapshot()
        self._show_agent_usage_summary("A6", "Completion Agent")

    def phase_7_export(self) -> None:
        print("\n=== Export ===")
        self._show_agent_stub(build_export_prompt(self.state))
        print(self.export_decklist())

        notes = self.validate_deck()
        if notes:
            print("Validation notes:")
            for note in notes:
                print(f"  - {note}")

        usage_summary = self.agent_runner.get_total_usage_summary()
        if usage_summary["input_tokens"] or usage_summary["output_tokens"]:
            print("\nLLM usage summary:")
            print(
                f"  Model: {usage_summary['model']} | "
                f"Input: {usage_summary['input_tokens']} | "
                f"Cached: {usage_summary['cached_tokens']} | "
                f"Output: {usage_summary['output_tokens']} | "
                f"Reasoning: {usage_summary['reasoning_tokens']} | "
                f"Cost: ${usage_summary['cost_usd']:.6f}"
            )
            self._maybe_show_usage_details()

    def export_decklist(self) -> str:
        lines = []
        for commander in self.state.decklist.get("commander", []):
            lines.append(commander.to_export_line(is_commander=True))

        for category in ALL_DECK_CATEGORIES:
            if category == "commander":
                continue
            for card in self.state.decklist.get(category, []):
                lines.append(card.to_export_line())

        return "\n".join(
            [
                "# Deck Summary",
                f"Commander: {self.state.commander or 'UNKNOWN'}",
                f"Themes: {', '.join(self.state.synergy_themes) or 'None'}",
                f"Color identity: {''.join(self.state.cid) or 'Unknown'}",
                f"Non-commander cards: {self.state.total_non_commander_cards()}",
                "",
                "# Decklist",
                *lines,
            ]
        )

    def validate_deck(self) -> list[str]:
        notes: list[str] = []
        total = self.state.total_non_commander_cards()
        if total != 99:
            notes.append(f"Deck has {total} non-commander cards; a finished EDH deck should have 99.")
        if not self.state.commander:
            notes.append("Commander is not set.")
        return notes

    def _run_category_search(self, category: str) -> None:
        if category == "synergy" and self.state.synergy_themes:
            for index, theme in enumerate(self.state.synergy_themes, start=1):
                theme_plan = self.state.synergy_theme_plans.get(
                    theme,
                    self.state.category_tags.get(category, A3CategoryPlan()),
                )
                selected_tags, search_intents, queries, aggregated, candidate_pool = (
                    self._collect_category_search_results_from_plan(theme_plan, category=category)
                )
                print(f"\nSynergy theme {index}: {theme}")
                self._run_category_search_round(
                    category,
                    theme_focus=theme,
                    selected_tags=selected_tags,
                    search_intents=search_intents,
                    queries=queries,
                    aggregated=aggregated,
                    candidate_pool=candidate_pool,
                )
            return

        selected_tags, search_intents, queries, aggregated, candidate_pool = (
            self._collect_category_search_results(category)
        )
        self._run_category_search_round(
            category,
            theme_focus=None,
            selected_tags=selected_tags,
            search_intents=search_intents,
            queries=queries,
            aggregated=aggregated,
            candidate_pool=candidate_pool,
        )

    def _collect_category_search_results(
        self,
        category: str,
    ) -> tuple[list[str], list[str], list[str], list[dict], list[dict]]:
        return self._collect_category_search_results_from_plan(
            self.state.category_tags.get(category, A3CategoryPlan()),
            category=category,
        )

    def _collect_category_search_results_from_plan(
        self,
        category_plan: A3CategoryPlan,
        category: str = "other",
    ) -> tuple[list[str], list[str], list[str], list[dict], list[dict]]:
        selected_tags = category_plan.tags
        search_intents = category_plan.search_intents
        tag_queries = self.scryfall.build_queries_for_tags(
            tags=selected_tags,
            cid=self.state.cid,
            budget_tier=self.state.budget_tier,
        )
        prepared_queries = [
            normalized
            for query in category_plan.candidate_queries
            if (
                normalized := self.scryfall.normalize_candidate_query(
                    query=query,
                    cid=self.state.cid,
                    budget_tier=self.state.budget_tier,
                )
            )
        ]
        queries = self._dedupe_preserve_order(prepared_queries + tag_queries)

        aggregated: list[dict] = []
        candidate_pool: list[dict] = []
        for card in category_plan.validated_preview_cards:
            if self.state.has_card(card.get("name", "")):
                continue
            if any(existing.get("name") == card.get("name") for existing in aggregated):
                continue
            aggregated.append(card)
            if any(existing.get("name") == card.get("name") for existing in candidate_pool):
                continue
            candidate_pool.append(card)

        query_trim_limit = self._determine_query_trim_limit(category)
        for query in queries:
            cards = self.scryfall.search_cards(query, limit=10)
            query_pool = self._trim_query_results(cards, limit=query_trim_limit)
            for card in cards:
                if self.state.has_card(card.get("name", "")):
                    continue
                if any(existing.get("name") == card.get("name") for existing in aggregated):
                    continue
                aggregated.append(card)
            for card in query_pool:
                if self.state.has_card(card.get("name", "")):
                    continue
                if any(existing.get("name") == card.get("name") for existing in candidate_pool):
                    continue
                candidate_pool.append(card)

        return selected_tags, search_intents, queries, aggregated, candidate_pool

    def _run_category_search_round(
        self,
        category: str,
        theme_focus: str | None,
        selected_tags: list[str],
        search_intents: list[str],
        queries: list[str],
        aggregated: list[dict],
        candidate_pool: list[dict],
    ) -> None:

        target_recommendation_count = self._determine_target_recommendation_count(
            category,
            len(candidate_pool),
        )
        candidate_pool_summary = self._build_candidate_pool_summary(candidate_pool)
        current_deck_names = self._current_deck_names()

        if not candidate_pool or not target_recommendation_count:
            self.state.search_history.append(
                SearchPlan(
                    category=category,
                    selected_tags=selected_tags,
                    search_intents=search_intents,
                    queries=queries,
                    recommended_cards=[],
                )
            )
            print("No usable live Scryfall results were available for this category.")
            if selected_tags:
                print(f"Prepared tags for {category}: {selected_tags}")
            if search_intents:
                print(f"Prepared search intents for {category}: {search_intents}")
            if queries:
                print("Queries run for this category:")
                for query in queries:
                    print(f"  - {query}")
            return

        prompt = build_search_ranking_prompt(
            self.state,
            category,
            theme_focus,
            selected_tags,
            search_intents,
            queries,
            candidate_pool_summary,
            current_deck_names,
            target_recommendation_count,
        )
        turn = self.agent_runner.run_a4_turn(prompt)
        recommended_cards = self._resolve_a4_recommendations(
            candidate_pool,
            turn.recommended_card_names,
            target_recommendation_count,
        )
        note_lookup = self._pair_notes_with_names(
            turn.recommended_card_names,
            turn.brief_recommendation_notes,
        )

        self.state.search_history.append(
            SearchPlan(
                category=category if not theme_focus else f"{category}:{theme_focus}",
                selected_tags=selected_tags,
                search_intents=search_intents,
                queries=queries,
                recommended_cards=recommended_cards,
            )
        )

        if turn.assistant_message:
            print(f"A4: {turn.assistant_message}")

        if recommended_cards:
            print("Recommended cards:")
            for index, card in enumerate(recommended_cards, start=1):
                note = note_lookup.get(card.get("name", "").lower(), "")
                note_suffix = f" | {note}" if note else ""
                print(
                    f"  {index}. {card.get('name')} | {card.get('type')} | "
                    f"${card.get('usd') or '?'} | EDHREC {card.get('edhrec_rank')}{note_suffix}"
                )
        else:
            print("No usable live Scryfall results were available for this category.")

        if selected_tags:
            print(f"Prepared tags for {category}: {selected_tags}")
        if search_intents:
            print(f"Prepared search intents for {category}: {search_intents}")
        if queries:
            print("Queries run for this category:")
            for query in queries:
                print(f"  - {query}")

        if candidate_pool and len(candidate_pool) != len(aggregated):
            print(
                f"Candidate pool trimmed for A4: {len(candidate_pool)} of {len(aggregated)} "
                "deduped live results."
            )

        self._add_cards_for_category(
            category,
            recommended_cards,
            queries[0] if queries else None,
        )

    def _add_cards_for_category(
        self,
        category: str,
        search_results: list[dict],
        source_query: str | None,
    ) -> None:
        print("Enter card names to add for this category, one per line. Press Enter on a blank line to finish.")
        names = self._read_card_name_lines("Add card: ")
        result_lookup = {card.get("name", "").lower(): card for card in search_results}

        for name in names:
            if self.state.has_card(name):
                continue

            card_data = result_lookup.get(name.lower())
            if not card_data or "mana_cost" not in card_data:
                card_data = self.scryfall.lookup_card_by_name(name)
            if card_data and self.state.cid and not self.scryfall.is_card_within_cid(card_data, self.state.cid):
                print(f"  Skipped {name}: outside commander color identity.")
                continue

            self.state.add_card(
                DeckCard(
                    name=name if not card_data else card_data.get("name", name),
                    category=category,
                    mana_cost=None if not card_data else card_data.get("mana_cost"),
                    type_line=None if not card_data else card_data.get("type_line"),
                    oracle_text=None if not card_data else card_data.get("oracle_text"),
                    usd=None if not card_data else self.scryfall.get_lowest_price(card_data),
                    set_code=None if not card_data else card_data.get("set"),
                    edhrec_rank=None if not card_data else card_data.get("edhrec_rank"),
                    source_query=source_query,
                )
            )

    def _add_resolved_cards(
        self,
        category: str,
        cards: list[dict],
        source_query: str | None,
    ) -> None:
        for card in cards:
            name = str(card.get("name") or "").strip()
            if not name or self.state.has_card(name):
                continue
            self.state.add_card(
                DeckCard(
                    name=name,
                    category=category,
                    mana_cost=card.get("mana_cost"),
                    type_line=card.get("type"),
                    oracle_text=card.get("oracle_text"),
                    usd=card.get("usd"),
                    set_code=card.get("set"),
                    edhrec_rank=card.get("edhrec_rank"),
                    source_query=source_query,
                    source="a6",
                )
            )

    def _remove_cards_by_name(self, lowered_names: list[str]) -> None:
        removal_set = {name.lower() for name in lowered_names if name}
        if not removal_set:
            return
        removed_count = 0
        for category, cards in self.state.decklist.items():
            if category == "commander":
                continue
            kept_cards: list[DeckCard] = []
            for card in cards:
                if card.name.lower() in removal_set:
                    removed_count += 1
                    continue
                kept_cards.append(card)
            self.state.decklist[category] = kept_cards
        self.state.card_count = max(1, self.state.card_count - removed_count)

    def _write_decklist_snapshot(self) -> None:
        DECKLIST_OUTPUT_PATH.write_text(self.export_decklist(), encoding="utf-8")
        print(f"Decklist snapshot written to {DECKLIST_OUTPUT_PATH}")

    def _show_agent_stub(self, prompt: AgentPrompt) -> None:
        print(f"[Stubbed {prompt.agent_id}: {prompt.agent_name}]")
        print(pformat(prompt.__dict__, sort_dicts=False))

    def _finalize_confirmed_commander(
        self,
        card_data: dict,
        fallback_name: str,
    ) -> None:
        self.state.commander = card_data.get("name", fallback_name)
        self.state.cid = self.scryfall.extract_color_identity(card_data)
        self.state.decklist["commander"] = [
            DeckCard(
                name=self.state.commander,
                category="commander",
                mana_cost=card_data.get("mana_cost"),
                type_line=card_data.get("type_line"),
                oracle_text=card_data.get("oracle_text"),
                usd=self.scryfall.get_lowest_price(card_data),
                set_code=card_data.get("set"),
                edhrec_rank=card_data.get("edhrec_rank"),
                source="a1-confirmed",
            )
        ]
        self.state.card_count = 1
        print(
            f"Confirmed commander: {self.state.commander} "
            f"[{''.join(self.state.cid) or 'C'}]"
        )
        self._show_agent_usage_summary("A1", "Intake Agent")

    def _current_deck_names(self) -> list[str]:
        names: list[str] = []
        for cards in self.state.decklist.values():
            for card in cards:
                if card.name not in names:
                    names.append(card.name)
        return names

    def _build_edhrec_candidate_pool(self, data: dict) -> list[dict]:
        pool: list[dict] = []
        seen_names: set[str] = set()
        current_names = {name.lower() for name in self._current_deck_names()}

        for source_key, source_label in (
            ("high_synergy_cards", "high_synergy"),
            ("top_cards", "top_cards"),
        ):
            for card in data.get(source_key, []):
                name = str(card.get("name") or "").strip()
                lowered = name.lower()
                if not name or lowered in seen_names or lowered in current_names:
                    continue
                scryfall_card = self.scryfall.lookup_card_by_name(name)
                if not scryfall_card:
                    continue
                if self.state.cid and not self.scryfall.is_card_within_cid(
                    scryfall_card,
                    self.state.cid,
                ):
                    continue
                if not self.scryfall.is_card_within_budget(
                    scryfall_card,
                    self.state.budget_tier,
                ):
                    continue
                seen_names.add(lowered)
                pool.append(
                    {
                        "name": scryfall_card.get("name", name),
                        "edhrec_source": source_label,
                        "edhrec_num_decks": card.get("num_decks"),
                        "edhrec_synergy": card.get("synergy"),
                        "mana_cost": scryfall_card.get("mana_cost"),
                        "type": scryfall_card.get("type_line"),
                        "oracle_text": scryfall_card.get("oracle_text", ""),
                        "usd": self.scryfall.get_lowest_price(scryfall_card),
                        "set": scryfall_card.get("set"),
                        "edhrec_rank": scryfall_card.get("edhrec_rank"),
                    }
                )
        return pool

    @staticmethod
    def _build_edhrec_candidate_pool_summary(
        candidate_pool: list[dict],
    ) -> list[dict[str, str | int | None]]:
        return [
            {
                "name": str(card.get("name") or ""),
                "source": str(card.get("edhrec_source") or ""),
                "num_decks": card.get("edhrec_num_decks"),
                "synergy": card.get("edhrec_synergy"),
                "mana_cost": card.get("mana_cost"),
                "type": card.get("type"),
                "usd": card.get("usd"),
            }
            for card in candidate_pool
        ]

    @staticmethod
    def _trim_query_results(cards: list[dict], limit: int = 6) -> list[dict]:
        return cards[:limit]

    @staticmethod
    def _determine_target_recommendation_count(category: str, candidate_count: int) -> int:
        if candidate_count <= 0:
            return 0
        if category == "draw":
            if candidate_count <= 15:
                return candidate_count
            if candidate_count <= 25:
                return 15
            if candidate_count <= 40:
                return 16
            return 18
        if candidate_count <= 8:
            return min(6, candidate_count)
        if candidate_count <= 20:
            return 10
        if candidate_count <= 40:
            return 14
        return 18

    @staticmethod
    def _determine_query_trim_limit(category: str) -> int:
        return 12 if category == "synergy" else 8

    @staticmethod
    def _determine_edhrec_target_count(candidate_count: int) -> int:
        if candidate_count <= 0:
            return 0
        if candidate_count <= 10:
            return min(6, candidate_count)
        if candidate_count <= 25:
            return 8
        return 10

    def _determine_a6_target_fill_counts(self, remaining_slots: int) -> dict[str, int]:
        desired_minimums = {
            "synergy": 25,
            "ramp": 10,
            "draw": 10,
            "removal": 9,
            "wipe": 3,
            "protection": 4,
            "recursion": 4,
        }
        current_counts = self.state.category_counts()
        eligible_categories = [
            category for category in self.state.category_queue if category != "lands"
        ]
        allocations = {category: 0 for category in eligible_categories}
        remaining = remaining_slots

        deficits = {
            category: max(0, desired_minimums.get(category, 0) - current_counts.get(category, 0))
            for category in eligible_categories
        }
        while remaining > 0 and any(value > 0 for value in deficits.values()):
            for category in eligible_categories:
                if remaining <= 0:
                    break
                if deficits.get(category, 0) <= 0:
                    continue
                allocations[category] += 1
                deficits[category] -= 1
                remaining -= 1

        weights = {
            "synergy": 3,
            "draw": 2,
            "ramp": 2,
            "removal": 2,
            "protection": 1,
            "recursion": 1,
            "wipe": 1,
        }
        weighted_order: list[str] = []
        for category in eligible_categories:
            weighted_order.extend([category] * weights.get(category, 1))

        while remaining > 0 and weighted_order:
            for category in weighted_order:
                if remaining <= 0:
                    break
                allocations[category] += 1
                remaining -= 1

        return {category: count for category, count in allocations.items() if count > 0}

    @staticmethod
    def _build_candidate_pool_summary(
        candidate_pool: list[dict],
    ) -> list[dict[str, str | int | None | list[str]]]:
        summary: list[dict[str, str | int | None | list[str]]] = []
        for card in candidate_pool:
            oracle_text = (card.get("oracle_text") or "").replace("\n", " ").strip()
            summary.append(
                {
                    "name": card.get("name"),
                    "mana_cost": card.get("mana_cost"),
                    "type": card.get("type"),
                    "oracle_preview": oracle_text[:180],
                    "usd": card.get("usd"),
                    "edhrec_rank": card.get("edhrec_rank"),
                }
            )
        return summary

    def _build_a6_candidate_pools(
        self,
        target_fill_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        candidate_pools: dict[str, list[dict]] = {}
        for category, target_count in target_fill_counts.items():
            if target_count <= 0:
                continue
            category_plan = self.state.category_tags.get(category, A3CategoryPlan())
            tag_queries = self.scryfall.build_queries_for_tags(
                tags=category_plan.tags,
                cid=self.state.cid,
                budget_tier=self.state.budget_tier,
            )
            prepared_queries = [
                normalized
                for query in category_plan.candidate_queries
                if (
                    normalized := self.scryfall.normalize_candidate_query(
                        query=query,
                        cid=self.state.cid,
                        budget_tier=self.state.budget_tier,
                    )
                )
            ]
            search_queries = self._dedupe_preserve_order(prepared_queries + tag_queries)
            pool: list[dict] = []

            existing_history = next(
                (entry for entry in reversed(self.state.search_history) if entry.category == category),
                None,
            )
            if existing_history:
                for card in existing_history.recommended_cards:
                    if self.state.has_card(card.get("name", "")):
                        continue
                    if any(existing.get("name") == card.get("name") for existing in pool):
                        continue
                    pool.append(card)

            for query in search_queries:
                cards = self.scryfall.search_cards(query, limit=max(12, target_count * 2))
                for card in cards:
                    if self.state.has_card(card.get("name", "")):
                        continue
                    if any(existing.get("name") == card.get("name") for existing in pool):
                        continue
                    pool.append(card)
                if len(pool) >= max(10, target_count * 3):
                    break

            candidate_pools[category] = pool[: max(10, target_count * 3)]
        return candidate_pools

    def _resolve_a6_recommendations(
        self,
        candidate_pools_by_category: dict[str, list[dict]],
        recommended_by_category: dict[str, list[str]],
        target_fill_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        resolved: dict[str, list[dict]] = {}
        used_names = {name.lower() for name in self._current_deck_names()}

        for category, target_count in target_fill_counts.items():
            pool = candidate_pools_by_category.get(category, [])
            by_name = {
                str(card.get("name", "")).strip().lower(): card
                for card in pool
                if card.get("name")
            }
            cards: list[dict] = []
            for name in recommended_by_category.get(category, []):
                card = by_name.get(name.strip().lower())
                card_name = str(card.get("name", "")).lower() if card else ""
                if not card or not card_name or card_name in used_names:
                    continue
                cards.append(card)
                used_names.add(card_name)
                if len(cards) >= target_count:
                    break

            if len(cards) < target_count:
                for card in pool:
                    card_name = str(card.get("name", "")).lower()
                    if not card_name or card_name in used_names:
                        continue
                    cards.append(card)
                    used_names.add(card_name)
                    if len(cards) >= target_count:
                        break

            resolved[category] = cards[:target_count]

        return resolved

    def _determine_a6_target_cut_counts(self, overfull_count: int) -> dict[str, int]:
        if overfull_count <= 0:
            return {}

        desired_minimums = {
            "synergy": 25,
            "ramp": 10,
            "draw": 10,
            "removal": 9,
            "wipe": 3,
            "protection": 4,
            "recursion": 4,
            "other": 0,
        }
        current_counts = self.state.category_counts()
        categories = [
            category
            for category in current_counts
            if category not in {"commander", "lands"} and current_counts.get(category, 0) > 0
        ]
        allocations = {category: 0 for category in categories}
        remaining = overfull_count

        excesses = {
            category: max(0, current_counts.get(category, 0) - desired_minimums.get(category, 0))
            for category in categories
        }
        while remaining > 0 and any(value > 0 for value in excesses.values()):
            ranked = sorted(
                categories,
                key=lambda category: (excesses.get(category, 0), current_counts.get(category, 0)),
                reverse=True,
            )
            for category in ranked:
                if remaining <= 0:
                    break
                if excesses.get(category, 0) <= 0:
                    continue
                allocations[category] += 1
                excesses[category] -= 1
                remaining -= 1

        if remaining > 0:
            ranked = sorted(categories, key=lambda category: current_counts.get(category, 0), reverse=True)
            while remaining > 0 and ranked:
                for category in ranked:
                    if remaining <= 0:
                        break
                    allocations[category] += 1
                    remaining -= 1

        return {category: count for category, count in allocations.items() if count > 0}

    def _build_a6_current_deck_summary(
        self,
    ) -> dict[str, list[dict[str, str | int | None | list[str]]]]:
        summary: dict[str, list[dict[str, str | int | None | list[str]]]] = {}
        for category, cards in self.state.decklist.items():
            if category in {"commander", "lands"} or not cards:
                continue
            summary[category] = [
                {
                    "name": card.name,
                    "mana_cost": card.mana_cost,
                    "type": card.type_line,
                    "oracle_preview": " ".join((card.oracle_text or "").split())[:180],
                    "usd": card.usd,
                    "edhrec_rank": card.edhrec_rank,
                }
                for card in cards
            ]
        return summary

    def _resolve_a6_cuts(
        self,
        current_deck_summary_by_category: dict[str, list[dict[str, str | int | None | list[str]]]],
        cuts_by_category: dict[str, list[str]],
        target_cut_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        resolved: dict[str, list[dict]] = {}
        for category, target_count in target_cut_counts.items():
            pool = current_deck_summary_by_category.get(category, [])
            by_name = {
                str(card.get("name", "")).strip().lower(): card
                for card in pool
                if card.get("name")
            }
            cuts: list[dict] = []
            for name in cuts_by_category.get(category, []):
                card = by_name.get(name.strip().lower())
                if not card:
                    continue
                if any(existing.get("name") == card.get("name") for existing in cuts):
                    continue
                cuts.append(card)
                if len(cuts) >= target_count:
                    break

            if len(cuts) < target_count:
                for card in pool:
                    if any(existing.get("name") == card.get("name") for existing in cuts):
                        continue
                    cuts.append(card)
                    if len(cuts) >= target_count:
                        break

            resolved[category] = cuts[:target_count]
        return resolved

    def _print_a6_grouped_cards(
        self,
        heading_label: str,
        cards_by_category: dict[str, list[dict]],
        raw_names_by_category: dict[str, list[str]],
        notes_by_category: dict[str, list[str]],
    ) -> int:
        total = 0
        for category, cards in cards_by_category.items():
            if not cards:
                continue
            total += len(cards)
            print(f"{category.title()} {heading_label}:")
            note_lookup = self._pair_notes_with_names(
                raw_names_by_category.get(category, []),
                notes_by_category.get(category, []),
            )
            for index, card in enumerate(cards, start=1):
                note = note_lookup.get(str(card.get("name", "")).lower(), "")
                note_suffix = f" | {note}" if note else ""
                print(
                    f"  {index}. {card.get('name')} | {card.get('type')} | "
                    f"${card.get('usd') or '?'} | EDHREC {card.get('edhrec_rank')}{note_suffix}"
                )
        return total

    @staticmethod
    def _pair_notes_with_names(
        names: list[str],
        notes: list[str],
    ) -> dict[str, str]:
        paired: dict[str, str] = {}
        for name, note in zip(names, notes):
            cleaned_name = name.strip().lower()
            cleaned_note = " ".join(note.split()).strip()
            if cleaned_name and cleaned_note:
                paired[cleaned_name] = cleaned_note[:120]
        return paired

    @staticmethod
    def _resolve_a4_recommendations(
        candidate_pool: list[dict],
        recommended_names: list[str],
        target_count: int,
    ) -> list[dict]:
        by_name = {
            str(card.get("name", "")).strip().lower(): card for card in candidate_pool if card.get("name")
        }
        resolved: list[dict] = []
        for name in recommended_names:
            card = by_name.get(name.strip().lower())
            if card and all(existing.get("name") != card.get("name") for existing in resolved):
                resolved.append(card)

        fallback_limit = target_count or 4
        if len(resolved) < fallback_limit:
            for card in candidate_pool:
                if all(existing.get("name") != card.get("name") for existing in resolved):
                    resolved.append(card)
                if len(resolved) >= fallback_limit:
                    break

        return resolved[:fallback_limit]

    def _load_a5_examples_reference(self) -> str:
        try:
            return A5_EXAMPLES_PATH.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _calculate_average_mana_value(self) -> float:
        if self.state.total_non_commander_cards() == 0:
            return 3.0
        mana_values: list[int] = []
        for cards in self.state.decklist.values():
            for card in cards:
                if card.category == "lands":
                    continue
                mana_value = self._estimate_mana_value(card.mana_cost)
                if mana_value is not None:
                    mana_values.append(mana_value)
        if not mana_values:
            return self._infer_typical_average_mana_value()
        return sum(mana_values) / len(mana_values)

    def _infer_typical_average_mana_value(self) -> float:
        theme_text = " ".join(theme.lower() for theme in self.state.synergy_themes)
        if any(term in theme_text for term in ("landfall", "lands matter", "lands", "big mana")):
            return 3.9
        if any(term in theme_text for term in ("big creatures", "reanimator", "dragons", "eldrazi")):
            return 3.8
        if any(term in theme_text for term in ("spellslinger", "spell-chaining", "cantrip", "cheap spells")):
            return 3.1
        if any(term in theme_text for term in ("aggro", "low curve", "equipment")):
            return 3.0
        return 3.4

    def _calculate_color_pip_counts(self) -> dict[str, int]:
        pip_counts = {color: 0 for color in self.state.cid}
        for cards in self.state.decklist.values():
            for card in cards:
                if card.category == "lands":
                    continue
                for color, count in self._count_color_pips(card.mana_cost).items():
                    if color in pip_counts:
                        pip_counts[color] += count
        return pip_counts

    @staticmethod
    def _estimate_mana_value(mana_cost: str | None) -> int | None:
        if not mana_cost:
            return None
        total = 0
        for symbol in re.findall(r"\{([^}]+)\}", mana_cost):
            upper = symbol.upper()
            if upper.isdigit():
                total += int(upper)
                continue
            if upper in {"W", "U", "B", "R", "G", "S", "C"}:
                total += 1
                continue
            if upper in {"X", "Y", "Z"}:
                continue
            if "/" in upper:
                total += 1
                continue
            if upper.startswith("2/"):
                total += 2
                continue
            if upper.startswith("HALF"):
                continue
            total += 1
        return total

    @staticmethod
    def _count_color_pips(mana_cost: str | None) -> dict[str, int]:
        counts = {color: 0 for color in "WUBRG"}
        if not mana_cost:
            return counts
        for symbol in re.findall(r"\{([^}]+)\}", mana_cost):
            upper = symbol.upper()
            for color in "WUBRG":
                if color in upper:
                    counts[color] += 1
        return counts

    def _color_pair_label(self, colors: tuple[str, str]) -> str:
        return "".join(color for color in "WUBRG" if color in colors)

    def _budget_price_filter(self) -> str | None:
        from .constants import BUDGET_PRICE_FILTERS

        return BUDGET_PRICE_FILTERS.get(self.state.budget_tier or "none")

    def _utility_land_cap(self) -> int:
        caps = {1: 7, 2: 5, 3: 3, 4: 2, 5: 2}
        return caps.get(len(self.state.cid), 2)

    def _build_land_query(self, *parts: str) -> str:
        query_parts = ["game:paper", "legal:commander"]
        price_filter = self._budget_price_filter()
        if price_filter:
            query_parts.append(price_filter)
        query_parts.extend(part for part in parts if part)
        return " ".join(query_parts)

    def _build_utility_land_candidates(self) -> list[dict]:
        if not self.state.cid:
            return []
        query = self._build_land_query(
            "t:land",
            f"id<={''.join(color.lower() for color in self.state.cid)}",
            "otag:utility-land",
        )
        return self.scryfall.search_cards(query, limit=48)

    def _build_dual_land_candidates_by_pair(self) -> dict[str, list[dict]]:
        if len(self.state.cid) < 2:
            return {}

        candidates_by_pair: dict[str, list[dict]] = {}
        for pair in combinations(self.state.cid, 2):
            pair_label = self._color_pair_label(pair)
            query = self._build_land_query("t:land", f"id={pair_label.lower()}")
            candidates_by_pair[pair_label] = self.scryfall.search_cards(query, limit=20)
        return candidates_by_pair

    def _build_tri_land_candidates(self) -> list[dict]:
        if len(self.state.cid) < 3:
            return []
        tri_selector = (
            "is:triland"
            if self.state.budget_tier in {"low", "medium"}
            else "is:triome"
        )
        query = self._build_land_query(
            tri_selector,
            "t:land",
            f"id<={''.join(color.lower() for color in self.state.cid)}",
        )
        limit = 20 if len(self.state.cid) <= 4 else 8
        return self.scryfall.search_cards(query, limit=limit)

    def _build_fetch_land_candidates(self) -> list[dict]:
        if self.state.budget_tier not in {"high", "none"} or len(self.state.cid) < 2:
            return []

        fetch_map = {
            "Arid Mesa": {"R", "W"},
            "Bloodstained Mire": {"B", "R"},
            "Flooded Strand": {"U", "W"},
            "Marsh Flats": {"B", "W"},
            "Misty Rainforest": {"G", "U"},
            "Polluted Delta": {"B", "U"},
            "Scalding Tarn": {"R", "U"},
            "Verdant Catacombs": {"B", "G"},
            "Windswept Heath": {"G", "W"},
            "Wooded Foothills": {"G", "R"},
        }

        deck_colors = set(self.state.cid)
        allowed_names = [
            name for name, colors in fetch_map.items() if colors.issubset(deck_colors)
        ]
        candidates: list[dict] = []
        for name in allowed_names:
            card = self.scryfall.lookup_card_by_name(name)
            if not card:
                continue
            if not self.scryfall.is_card_within_budget(card, self.state.budget_tier):
                continue
            if not self.scryfall.is_card_within_cid(card, self.state.cid):
                continue
            candidates.append(
                {
                    "name": card.get("name"),
                    "mana_cost": card.get("mana_cost"),
                    "type": card.get("type_line"),
                    "oracle_text": card.get("oracle_text", ""),
                    "usd": self.scryfall.get_lowest_price(card),
                    "set": (card.get("set") or "").upper(),
                    "edhrec_rank": card.get("edhrec_rank"),
                }
            )
        candidates.sort(key=lambda card: (card.get("edhrec_rank") is None, card.get("edhrec_rank") or 10**9))
        return candidates

    @staticmethod
    def _summarize_land_candidates(
        candidates: list[dict],
    ) -> list[dict[str, str | int | None]]:
        summary: list[dict[str, str | int | None]] = []
        for card in candidates:
            oracle_text = " ".join(str(card.get("oracle_text") or "").split())
            summary.append(
                {
                    "name": card.get("name"),
                    "mana_cost": card.get("mana_cost"),
                    "type": card.get("type"),
                    "oracle_preview": oracle_text[:180],
                    "usd": card.get("usd"),
                    "edhrec_rank": card.get("edhrec_rank"),
                }
            )
        return summary

    def _collect_a5_utility_selection(
        self,
        utility_candidates: list[dict],
        recommended_names: list[str],
    ) -> list[str]:
        cap = self._utility_land_cap()
        candidate_lookup = {
            str(card.get("name", "")).strip().lower(): str(card.get("name", "")).strip()
            for card in utility_candidates
            if card.get("name")
        }
        default_selection = [
            candidate_lookup[name.strip().lower()]
            for name in recommended_names
            if name.strip().lower() in candidate_lookup
        ][:cap]

        print(
            f"Choose up to {cap} utility lands to include. "
            "Press Enter on a blank line immediately to accept the recommended list."
        )
        chosen = self._read_card_name_lines("Utility land: ")
        if not chosen:
            return default_selection

        cleaned: list[str] = []
        for name in chosen:
            resolved = candidate_lookup.get(name.strip().lower())
            if not resolved or resolved in cleaned:
                continue
            cleaned.append(resolved)
            if len(cleaned) >= cap:
                break
        return cleaned

    def _prompt_a5_test_commander(self) -> None:
        raw = input(
            "Commander for A5 test (optional, exact name if you want real card context): "
        ).strip()
        self.state.commander = None
        self.state.cid = []
        self.state.decklist["commander"] = []
        if not raw:
            return

        card = self.scryfall.lookup_card_by_name(raw)
        if not card:
            self.state.commander = raw
            return

        self.state.commander = card.get("name", raw)
        self.state.cid = self.scryfall.extract_color_identity(card)
        self.state.decklist["commander"] = [
            DeckCard(
                name=self.state.commander,
                category="commander",
                mana_cost=card.get("mana_cost"),
                type_line=card.get("type_line"),
                oracle_text=card.get("oracle_text"),
                usd=self.scryfall.get_lowest_price(card),
                set_code=card.get("set"),
                edhrec_rank=card.get("edhrec_rank"),
                source="a5-test",
            )
        ]

    def _prompt_color_identity(self, default_cid: list[str] | None = None) -> list[str]:
        default_cid = default_cid or []
        while True:
            default_label = f" [{''.join(default_cid)}]" if default_cid else ""
            raw = input(
                f"Color identity for A5 test (e.g. W, WB, WUBRG){default_label}: "
            ).strip().upper()
            if not raw and default_cid:
                return default_cid
            cleaned = [color for color in "WUBRG" if color in raw]
            if cleaned:
                return cleaned

    def _prompt_budget_tier(self) -> str:
        while True:
            raw = input("Budget tier for A5 test [low/medium/high/none]: ").strip().lower()
            if raw in BUDGET_TIER_LABELS:
                return raw

    def _prompt_synergy_themes(self) -> list[str]:
        print("Enter synergy themes for A5 testing, one per line. Press Enter on a blank line to finish.")
        return self._read_card_name_lines("Theme: ")

    def _confirm_target_land_count(
        self,
        proposed_target: int,
        average_mana_value: float,
    ) -> int:
        default_target = max(37, proposed_target)
        print(
            f"A5 proposed {default_target} total lands "
            f"(average mana value {average_mana_value:.2f})."
        )
        response = input("Override total land count or press Enter to accept: ").strip()
        if not response:
            return default_target
        try:
            return max(37, int(response))
        except ValueError:
            return default_target

    def _finalize_a5_land_package(
        self,
        selected_utility_land_names: list[str],
        target_land_count: int,
        utility_candidates: list[dict],
        dual_candidates_by_pair: dict[str, list[dict]],
        tri_candidates: list[dict],
        fetch_candidates: list[dict],
        final_turn,
        color_pip_counts: dict[str, int],
    ) -> list[DeckCard]:
        utility_lookup = self._candidate_lookup(utility_candidates)
        dual_lookup = self._candidate_lookup(
            [card for cards in dual_candidates_by_pair.values() for card in cards]
        )
        tri_lookup = self._candidate_lookup(tri_candidates)
        fetch_lookup = self._candidate_lookup(fetch_candidates)

        final_cards: list[DeckCard] = []
        seen_names: set[str] = set()

        def add_candidate(card: dict | None, source_query: str) -> bool:
            if not card:
                return False
            name = str(card.get("name") or "").strip()
            if not name or name.lower() in seen_names:
                return False
            seen_names.add(name.lower())
            final_cards.append(
                DeckCard(
                    name=name,
                    category="lands",
                    mana_cost=card.get("mana_cost"),
                    type_line=card.get("type") or card.get("type_line"),
                    oracle_text=card.get("oracle_text"),
                    usd=card.get("usd"),
                    set_code=card.get("set"),
                    edhrec_rank=card.get("edhrec_rank"),
                    source_query=source_query,
                    source="a5",
                )
            )
            return True

        utility_cap = self._utility_land_cap()
        for name in selected_utility_land_names[:utility_cap]:
            add_candidate(utility_lookup.get(name.lower()), "a5-utility")

        if len(self.state.cid) >= 2:
            self._add_named_land_if_available(
                "Command Tower",
                final_cards,
                seen_names,
                source_query="a5-auto",
            )
            if self.state.budget_tier in {"low", "medium"}:
                self._add_named_land_if_available(
                    "Path of Ancestry",
                    final_cards,
                    seen_names,
                    source_query="a5-auto",
                )

        for name in final_turn.dual_land_names:
            add_candidate(dual_lookup.get(name.lower()), "a5-dual")

        tri_limit = 4 if len(self.state.cid) == 5 else len(final_turn.tri_land_names)
        for name in final_turn.tri_land_names[:tri_limit]:
            add_candidate(tri_lookup.get(name.lower()), "a5-tri")

        for name in final_turn.fetch_land_names:
            add_candidate(fetch_lookup.get(name.lower()), "a5-fetch")

        minimum_basic_slots = len(self.state.cid)
        max_nonbasic = max(0, target_land_count - minimum_basic_slots)
        if len(final_cards) > max_nonbasic:
            final_cards = self._trim_land_cards_to_limit(
                final_cards,
                max_nonbasic,
                required_names={
                    "command tower",
                    "path of ancestry",
                    *{name.lower() for name in selected_utility_land_names[:utility_cap]},
                },
            )
            seen_names = {card.name.lower() for card in final_cards}

        basic_total = max(minimum_basic_slots, target_land_count - len(final_cards))
        basic_counts = self._normalize_basic_land_counts(
            final_turn.basic_land_counts,
            basic_total,
            color_pip_counts,
        )

        for basic_name, count in basic_counts.items():
            for _ in range(count):
                final_cards.append(
                    DeckCard(
                        name=basic_name,
                        category="lands",
                        type_line="Basic Land",
                        source_query="a5-basics",
                        source="a5",
                    )
                )

        if len(final_cards) < target_land_count:
            extras = self._normalize_basic_land_counts({}, target_land_count - len(final_cards), color_pip_counts)
            for basic_name, count in extras.items():
                for _ in range(count):
                    final_cards.append(
                        DeckCard(
                            name=basic_name,
                            category="lands",
                            type_line="Basic Land",
                            source_query="a5-basics-fill",
                            source="a5",
                        )
                    )

        return final_cards[:target_land_count]

    @staticmethod
    def _candidate_lookup(candidates: list[dict]) -> dict[str, dict]:
        return {
            str(card.get("name", "")).strip().lower(): card
            for card in candidates
            if card.get("name")
        }

    def _add_named_land_if_available(
        self,
        card_name: str,
        final_cards: list[DeckCard],
        seen_names: set[str],
        source_query: str,
    ) -> None:
        lowered = card_name.lower()
        if lowered in seen_names:
            return
        card = self.scryfall.lookup_card_by_name(card_name)
        if not card:
            return
        if self.state.cid and not self.scryfall.is_card_within_cid(card, self.state.cid):
            return
        if not self.scryfall.is_card_within_budget(card, self.state.budget_tier):
            return
        seen_names.add(lowered)
        final_cards.append(
            DeckCard(
                name=card.get("name", card_name),
                category="lands",
                mana_cost=card.get("mana_cost"),
                type_line=card.get("type_line"),
                oracle_text=card.get("oracle_text"),
                usd=self.scryfall.get_lowest_price(card),
                set_code=card.get("set"),
                edhrec_rank=card.get("edhrec_rank"),
                source_query=source_query,
                source="a5",
            )
        )

    @staticmethod
    def _trim_land_cards_to_limit(
        cards: list[DeckCard],
        limit: int,
        required_names: set[str],
    ) -> list[DeckCard]:
        if len(cards) <= limit:
            return cards
        required = [card for card in cards if card.name.lower() in required_names]
        optional = [card for card in cards if card.name.lower() not in required_names]
        trimmed = required[:limit]
        if len(trimmed) < limit:
            trimmed.extend(optional[: limit - len(trimmed)])
        return trimmed

    def _normalize_basic_land_counts(
        self,
        proposed_counts: dict[str, int],
        total_basics: int,
        color_pip_counts: dict[str, int],
    ) -> dict[str, int]:
        color_to_basic = {
            "W": "Plains",
            "U": "Island",
            "B": "Swamp",
            "R": "Mountain",
            "G": "Forest",
        }
        colors = list(self.state.cid)
        if not colors or total_basics <= 0:
            return {}

        normalized = {color_to_basic[color]: 1 for color in colors}
        remaining = max(0, total_basics - len(colors))

        proposed_by_color = {
            color: max(0, int(proposed_counts.get(color_to_basic[color], 0)))
            for color in colors
        }
        total_proposed = sum(proposed_by_color.values())

        if total_proposed > 0:
            allocation_source = proposed_by_color
        else:
            allocation_source = {
                color: max(1, color_pip_counts.get(color, 0))
                for color in colors
            }

        total_weight = sum(allocation_source.values()) or len(colors)
        provisional: dict[str, int] = {}
        assigned = 0
        for color in colors:
            share = int(remaining * allocation_source[color] / total_weight)
            provisional[color] = share
            assigned += share

        leftovers = remaining - assigned
        ranked_colors = sorted(
            colors,
            key=lambda color: (allocation_source[color], color_pip_counts.get(color, 0)),
            reverse=True,
        )
        for color in ranked_colors:
            if leftovers <= 0:
                break
            provisional[color] += 1
            leftovers -= 1

        for color in colors:
            normalized[color_to_basic[color]] += provisional.get(color, 0)

        return normalized

    def _replace_lands_decklist(self, land_cards: list[DeckCard]) -> None:
        old_lands = self.state.decklist.get("lands", [])
        self.state.card_count -= len(old_lands)
        self.state.decklist["lands"] = []
        for card in land_cards:
            self.state.add_card(card)

    @staticmethod
    def _print_final_landbase(land_cards: list[DeckCard]) -> None:
        print("\nFinal landbase:")
        grouped: dict[str, list[str]] = {
            "Utility / auto-includes": [],
            "Dual lands": [],
            "Tri-lands / triomes": [],
            "Fetch lands": [],
            "Basics": [],
        }
        basic_names = {"Plains", "Island", "Swamp", "Mountain", "Forest"}

        for card in land_cards:
            if card.name in basic_names:
                grouped["Basics"].append(card.name)
            elif card.source_query == "a5-fetch":
                grouped["Fetch lands"].append(card.name)
            elif card.source_query == "a5-tri":
                grouped["Tri-lands / triomes"].append(card.name)
            elif card.source_query == "a5-dual":
                grouped["Dual lands"].append(card.name)
            else:
                grouped["Utility / auto-includes"].append(card.name)

        for label, names in grouped.items():
            if not names:
                continue
            print(f"{label}:")
            if label == "Basics":
                counts: dict[str, int] = {}
                for name in names:
                    counts[name] = counts.get(name, 0) + 1
                for name, count in counts.items():
                    print(f"  {count} {name}")
            else:
                for name in names:
                    print(f"  - {name}")
        print(f"Total lands added: {len(land_cards)}")

    def _validate_a2_submission(
        self,
        synergy_themes: list[str],
        budget_tier: str | None,
        category_queue: list[str],
    ) -> tuple[bool, str, dict[str, list[str] | str]]:
        cleaned_themes = [theme.strip() for theme in synergy_themes if theme.strip()]
        cleaned_budget = (budget_tier or "").strip().lower()
        cleaned_categories = []
        for category in category_queue:
            normalized = category.strip().lower()
            if normalized in CATEGORY_ORDER and normalized not in cleaned_categories:
                cleaned_categories.append(normalized)

        if not cleaned_themes:
            return False, "You still need to capture at least one synergy theme.", {}
        if cleaned_budget not in BUDGET_TIER_LABELS:
            return False, "You still need one valid budget tier: low, medium, high, or none.", {}
        if not cleaned_categories:
            return False, "You still need at least one confirmed category.", {}
        if "synergy" not in cleaned_categories:
            cleaned_categories.insert(0, "synergy")

        return True, "", {
            "synergy_themes": cleaned_themes,
            "budget_tier": cleaned_budget,
            "category_queue": cleaned_categories,
        }

    def _validate_a3_category_plans(
        self,
        category_plans: dict[str, A3CategoryPlan],
        synergy_theme_plans: dict[str, A3CategoryPlan],
        all_tags: list[str],
    ) -> tuple[bool, str, dict[str, A3CategoryPlan], dict[str, A3CategoryPlan]]:
        valid_tag_set = {tag.lower(): tag for tag in all_tags}
        cleaned: dict[str, A3CategoryPlan] = {}
        cleaned_theme_plans: dict[str, A3CategoryPlan] = {}
        validation_notes: list[str] = []

        def normalize_plan(
            raw_plan: A3CategoryPlan | None,
            label: str,
        ) -> tuple[bool, str, A3CategoryPlan | None, list[str]]:
            if not raw_plan:
                return False, f"A3 did not provide a search plan for {label}.", None, []

            normalized_tags: list[str] = []
            for tag in raw_plan.tags:
                lookup = valid_tag_set.get(tag.strip().lower())
                if lookup and lookup not in normalized_tags:
                    normalized_tags.append(lookup)

            normalized_intents: list[str] = []
            for intent in raw_plan.search_intents:
                cleaned_intent = " ".join(intent.split()).strip()
                if cleaned_intent and cleaned_intent not in normalized_intents:
                    normalized_intents.append(cleaned_intent)

            normalized_queries: list[str] = []
            normalized_preview_cards: list[dict] = []
            invalid_query_notes: list[str] = []
            for query in raw_plan.candidate_queries:
                normalized_query = self.scryfall.normalize_candidate_query(
                    query=query,
                    cid=self.state.cid,
                    budget_tier=self.state.budget_tier,
                )
                if not normalized_query:
                    continue
                if normalized_query in normalized_queries:
                    continue

                is_valid, message, preview_cards = self.scryfall.validate_search_query(
                    normalized_query
                )
                if is_valid:
                    normalized_queries.append(normalized_query)
                    for card in preview_cards:
                        if any(existing.get("name") == card.get("name") for existing in normalized_preview_cards):
                            continue
                        normalized_preview_cards.append(card)
                else:
                    invalid_query_notes.append(f'"{normalized_query}" -> {message}')

            if not normalized_tags and not normalized_queries:
                return (
                    False,
                    f"A3 did not provide any usable tags or queries for {label}.",
                    None,
                    invalid_query_notes,
                )
            if not normalized_intents:
                return False, f"A3 did not provide any search intents for {label}.", None, invalid_query_notes

            return True, "", A3CategoryPlan(
                tags=normalized_tags[:5],
                search_intents=normalized_intents[:3],
                candidate_queries=normalized_queries[:5],
                validated_preview_cards=normalized_preview_cards[:24],
            ), invalid_query_notes

        for category in self.state.category_queue:
            ok, message, normalized_plan, invalid_query_notes = normalize_plan(
                category_plans.get(category),
                f"category '{category}'",
            )
            if not ok or not normalized_plan:
                return False, message, {}, {}
            cleaned[category] = normalized_plan
            if invalid_query_notes:
                validation_notes.append(
                    f"Category '{category}' had invalid candidate queries:\n"
                    + "\n".join(f"- {note}" for note in invalid_query_notes[:3])
                )

        if "synergy" in self.state.category_queue and self.state.synergy_themes:
            for theme in self.state.synergy_themes:
                raw_theme_plan = (
                    synergy_theme_plans.get(theme)
                    or synergy_theme_plans.get(theme.strip())
                )
                ok, message, normalized_plan, invalid_query_notes = normalize_plan(
                    raw_theme_plan,
                    f"synergy theme '{theme}'",
                )
                if not ok or not normalized_plan:
                    return False, message, {}, {}
                cleaned_theme_plans[theme] = normalized_plan
                if invalid_query_notes:
                    validation_notes.append(
                        f"Synergy theme '{theme}' had invalid candidate queries:\n"
                        + "\n".join(f"- {note}" for note in invalid_query_notes[:3])
                    )

        return True, "\n\n".join(validation_notes), cleaned, cleaned_theme_plans

    def _format_commander_search_feedback(self, query: str, candidates: list[dict]) -> str:
        if not candidates:
            return (
                f'No commander results were found on Scryfall for search query "{query}". '
                "Ask the user for a different spelling, a longer name, or a different commander."
            )

        formatted = []
        for candidate in candidates:
            cid = "".join(candidate.get("color_identity", [])) or "C"
            oracle_lines = candidate.get("oracle_text", "").splitlines()
            oracle_text = oracle_lines[0].strip() if oracle_lines else ""
            oracle_preview = f" | {oracle_text}" if oracle_text else ""
            formatted.append(
                f'- {candidate.get("name")} [{cid}] | {candidate.get("type_line")}{oracle_preview}'
            )

        return (
            f'Scryfall commander search results for "{query}":\n'
            + "\n".join(formatted)
            + "\nPresent the options briefly and ask the user which one they want."
        )

    def _format_random_commander_feedback(self, candidates: list[dict]) -> str:
        if not candidates:
            return (
                "Scryfall random commander lookup was unavailable or too slow. "
                "Choose one interesting commander from your own knowledge, give its exact name, "
                "briefly explain why you picked it, and ask the user to confirm it."
            )

        formatted = []
        for candidate in candidates:
            cid = "".join(candidate.get("color_identity", [])) or "C"
            oracle_lines = candidate.get("oracle_text", "").splitlines()
            oracle_text = oracle_lines[0].strip() if oracle_lines else ""
            oracle_preview = f" | {oracle_text}" if oracle_text else ""
            formatted.append(
                f'- {candidate.get("name")} [{cid}] | {candidate.get("type_line")}{oracle_preview}'
            )

        return (
            "Random commander pool from Scryfall:\n"
            + "\n".join(formatted)
            + "\nPick one commander from this pool for the user, explain the choice briefly, and ask for confirmation."
        )

    def _show_agent_usage_summary(self, agent_id: str, agent_name: str) -> None:
        summary = self.agent_runner.get_agent_usage_summary(agent_id)
        if not summary["call_count"]:
            return

        print(f"\n{agent_id} usage summary:")
        print(
            f"  Agent: {agent_name} | "
            f"Calls: {summary['call_count']} | "
            f"Model: {summary['model']} | "
            f"Input: {summary['input_tokens']} | "
            f"Cached: {summary['cached_tokens']} | "
            f"Output: {summary['output_tokens']} | "
            f"Reasoning: {summary['reasoning_tokens']} | "
            f"Cost: ${summary['cost_usd']:.6f}"
        )

    def _maybe_show_usage_details(self) -> None:
        choice = input("Show detailed LLM usage by agent call? [y/N]: ").strip().lower()
        if choice not in {"y", "yes"}:
            return

        print("\nDetailed LLM usage:")
        for item in self.agent_runner.get_usage_history_summary():
            print(
                f"  Call {item['call_index']}: {item['agent_id']} {item['agent_name']} | "
                f"Model: {item['model']} | "
                f"Input: {item['input_tokens']} | "
                f"Cached: {item['cached_tokens']} | "
                f"Output: {item['output_tokens']} | "
                f"Reasoning: {item['reasoning_tokens']} | "
                f"Cost: ${item['cost_usd']:.6f}"
            )

    @staticmethod
    def _read_card_name_lines(prompt: str) -> list[str]:
        names: list[str] = []
        while True:
            value = input(prompt).strip()
            if not value:
                return names
            names.append(value)

    @staticmethod
    def _is_affirmative(value: str) -> bool:
        cleaned = " ".join(value.strip().lower().split())
        if not cleaned:
            return False
        exact_matches = {
            "yes",
            "y",
            "yeah",
            "yep",
            "yup",
            "correct",
            "confirm",
            "confirmed",
            "proceed",
            "verify",
            "do it",
            "sounds good",
            "that's right",
            "that is right",
            "exactly",
        }
        if cleaned in exact_matches:
            return True
        return cleaned.startswith("yes ")

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @staticmethod
    def _ask_non_empty(prompt: str) -> str:
        while True:
            value = input(prompt).strip()
            if value:
                return value
