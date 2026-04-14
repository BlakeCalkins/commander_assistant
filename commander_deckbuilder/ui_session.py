"""UI-facing workflow session controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread

from .agents import (
    build_intake_prompt,
    build_search_ranking_prompt,
    build_strategy_prompt_with_context,
    build_tag_prep_prompt,
)
from .card_view_models import UICard, ui_card_from_scryfall, ui_card_from_summary
from .edhrec import EDHRECService
from .llm import AgentRunner
from .models import A3CategoryPlan, DeckCard, DeckState, SearchPlan
from .scryfall import ScryfallService
from .workflow import CommanderDeckWorkflow
from .ui_events import (
    ChatMessageEvent,
    DeckStateEvent,
    PhaseEvent,
    PromptEvent,
    RecommendationBatchEvent,
    UIEvent,
)


@dataclass
class _ActiveBatchState:
    batch_id: str
    mode: str
    title: str
    category: str
    cards: list[UICard] = field(default_factory=list)
    candidate_name: str | None = None
    theme_focus: str | None = None
    allow_skip: bool = True
    source_query: str | None = None
    batch_index: int = 0
    can_go_prev: bool = False
    can_go_next: bool = False
    next_pending: bool = False


@dataclass
class _PrecomputedA4Round:
    title: str
    category: str
    theme_focus: str | None = None
    cards: list[UICard] = field(default_factory=list)
    assistant_message: str | None = None
    allow_skip: bool = True
    source_query: str | None = None
    search_plan: SearchPlan | None = None
    no_results_message: str | None = None
    search_plan_recorded: bool = False


class DeckbuilderUISession:
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
        self.workflow = CommanderDeckWorkflow(
            scryfall=self.scryfall,
            edhrec=self.edhrec,
            agent_runner=self.agent_runner,
        )
        self.workflow.state = self.state

        self.phase = "a1"
        self.started = False
        self.is_busy = False
        self.active_prompt: PromptEvent | None = None
        self.active_batch: _ActiveBatchState | None = None
        self._event_counter = 0
        self._bg_lock = Lock()

        self._a1_conversation: list[dict[str, str]] = []
        self._a1_validation_feedback: str | None = None
        self._a1_search_feedback: str | None = None
        self._a1_pending_candidate_commander: str | None = None
        self._a1_pending_search_cards: list[dict] = []
        self._a1_pending_search_mode: str | None = None

        self._a2_conversation: list[dict[str, str]] = []
        self._a2_validation_feedback: str | None = None
        self._a4_rounds: list[tuple[str, str | None]] = []
        self._a4_round_index = 0
        self._a4_precompute_started = False
        self._a4_precompute_complete = False
        self._a4_precompute_error: str | None = None
        self._a4_precomputed_rounds: list[_PrecomputedA4Round] = []
        self._a4_precompute_total = 0

        self.a3_started = False
        self.a3_complete = False
        self.a3_error: str | None = None
        self.a3_validation_notes: str | None = None
        self.edhrec_started = False
        self.edhrec_ready = False
        self.edhrec_error: str | None = None
        self.edhrec_sections: dict[str, list[UICard]] = {
            "high_synergy": [],
            "top_cards": [],
        }
        self._edhrec_cards_by_section_and_name: dict[str, dict[str, dict]] = {
            "high_synergy": {},
            "top_cards": {},
        }

    def start(self) -> list[UIEvent]:
        self.started = True
        events: list[UIEvent] = [
            PhaseEvent(phase_id="a1", title="Commander Selection (A1)")
        ]
        events.extend(self._advance_a1())
        return events

    def submit_text(self, user_text: str) -> list[UIEvent]:
        text = user_text.strip()
        if not text:
            return []

        events: list[UIEvent] = [ChatMessageEvent(role="user", text=text)]
        self.active_prompt = None

        if self.phase == "a1_complete":
            return events

        if self.phase == "a2":
            self._a2_conversation.append({"role": "user", "content": text})
            events.extend(self._advance_a2())
            return events

        if self._a1_pending_candidate_commander and self._is_affirmative(text):
            is_valid, message, card_data = self.scryfall.validate_commander_candidate(
                self._a1_pending_candidate_commander
            )
            if is_valid and card_data:
                events.extend(
                    self._finalize_commander_ui(
                        card_data,
                        fallback_name=self._a1_pending_candidate_commander,
                    )
                )
                return events
            self._a1_validation_feedback = message
            self._a1_search_feedback = None
            self._a1_pending_candidate_commander = None
            self.active_batch = None
            events.extend(self._advance_a1())
            return events

        self._a1_conversation.append({"role": "user", "content": text})
        events.extend(self._advance_a1())
        return events

    def select_card(self, batch_id: str, card_name: str, action: str = "select") -> list[UIEvent]:
        if not self.active_batch or self.active_batch.batch_id != batch_id:
            return []

        if self.active_batch.mode == "confirm_one":
            return self.submit_text("yes")
        if self.active_batch.mode == "add":
            return self._add_recommendation_card(card_name)
        return self.submit_text(card_name)

    def skip(self, prompt_id: str | None = None) -> list[UIEvent]:
        if self.phase == "a1" and self.active_batch and self.active_batch.mode in {"search", "random"}:
            self.active_batch = None
            self.active_prompt = PromptEvent(
                prompt_id=self._next_id("prompt"),
                kind="text",
                label="Reply to A1",
                placeholder="Type the commander you want or ask A1 to choose again.",
            )
            return [self.active_prompt]
        if self.phase == "a4" and self.active_batch and self.active_batch.mode == "add":
            return self.next_a4_batch()
        return []

    def next_a4_batch(self) -> list[UIEvent]:
        if self.phase != "a4":
            return []
        next_index = self._a4_round_index + 1
        if next_index < len(self._a4_precomputed_rounds):
            self._a4_round_index = next_index
            return self._show_a4_batch(self._a4_round_index)
        if not self._a4_precompute_complete:
            return [
                ChatMessageEvent(
                    role="system",
                    text=(
                        "The next A4 batch is still being prepared "
                        f"({len(self._a4_precomputed_rounds)}/{self._a4_precompute_total or '?'} ready)."
                    ),
                )
            ]
        self.phase = "a5_pending"
        self.active_batch = None
        return [
            ChatMessageEvent(
                role="system",
                text="A4 recommendation rounds are complete. A5 UI wiring is next.",
            )
        ]

    def previous_a4_batch(self) -> list[UIEvent]:
        if self.phase != "a4":
            return []
        if self._a4_round_index <= 0:
            return [
                ChatMessageEvent(
                    role="system",
                    text="You are already on the first available A4 batch.",
                )
            ]
        self._a4_round_index -= 1
        return self._show_a4_batch(self._a4_round_index)

    def start_a4(self) -> list[UIEvent]:
        if self.phase not in {"a4_pending", "a4"}:
            return []
        if self._a4_precompute_error:
            return [
                ChatMessageEvent(
                    role="system",
                    text=f"A4 recommendations could not be prepared: {self._a4_precompute_error}",
                )
            ]
        if not self._a4_precomputed_rounds:
            return [
                ChatMessageEvent(
                    role="system",
                    text=(
                        "A4 recommendations are still being prepared "
                        f"({len(self._a4_precomputed_rounds)}/{self._a4_precompute_total or '?'} ready)."
                    ),
                )
            ]
        self.phase = "a4"
        if not self._a4_rounds:
            self._a4_rounds = self._build_a4_rounds()
            self._a4_round_index = 0
        if self._a4_round_index >= len(self._a4_precomputed_rounds):
            self._a4_round_index = 0
        return self._show_a4_batch(self._a4_round_index)

    def add_edhrec_card(self, section: str, card_name: str) -> list[UIEvent]:
        lowered = card_name.strip().lower()
        if not lowered:
            return []
        with self._bg_lock:
            source_card = self._edhrec_cards_by_section_and_name.get(section, {}).get(lowered)
            if not source_card or self.state.has_card(card_name):
                return []
            self.state.add_card(
                DeckCard(
                    name=source_card.get("name", card_name),
                    category="synergy",
                    mana_cost=source_card.get("mana_cost"),
                    type_line=source_card.get("type"),
                    oracle_text=source_card.get("oracle_text"),
                    usd=source_card.get("usd"),
                    set_code=source_card.get("set"),
                    edhrec_rank=source_card.get("edhrec_rank"),
                    source="edhrec-display",
                    source_query=f"edhrec-{section}",
                )
            )
        return [
            ChatMessageEvent(
                role="system",
                text=f'Added "{source_card.get("name", card_name)}" from {section.replace("_", " ")}.',
            ),
            self.get_deck_state_event(),
        ]

    def get_loading_view_model(self) -> dict:
        with self._bg_lock:
            return {
                "is_loading": (
                    self.phase in {"loading", "a4_pending"}
                    and (
                        not self.a3_complete
                        or (
                            self.a3_complete
                            and self._a4_precompute_started
                            and not self._a4_precompute_complete
                        )
                    )
                ),
                "a3_started": self.a3_started,
                "a3_complete": self.a3_complete,
                "a3_error": self.a3_error,
                "a3_validation_notes": self.a3_validation_notes,
                "a4_precompute_started": self._a4_precompute_started,
                "a4_precompute_complete": self._a4_precompute_complete,
                "a4_precompute_error": self._a4_precompute_error,
                "a4_precomputed_count": len(self._a4_precomputed_rounds),
                "a4_precompute_total": self._a4_precompute_total,
                "edhrec_started": self.edhrec_started,
                "edhrec_ready": self.edhrec_ready,
                "edhrec_error": self.edhrec_error,
                "sections": {
                    key: list(cards) for key, cards in self.edhrec_sections.items()
                },
            }

    def get_deck_state_event(self) -> DeckStateEvent:
        preview: list[str] = []
        if self.state.commander:
            preview.append(f"Commander: {self.state.commander}")
        for category, cards in self.state.decklist.items():
            if category == "commander" or not cards:
                continue
            preview.append(f"{category.upper()}:")
            preview.extend(card.name for card in cards)
        return DeckStateEvent(
            commander=self.state.commander,
            category_counts=self.state.category_counts(),
            total_non_commander_cards=self.state.total_non_commander_cards(),
            decklist_preview=preview,
        )

    def _advance_a2(self) -> list[UIEvent]:
        events: list[UIEvent] = []

        while True:
            prompt = build_strategy_prompt_with_context(
                state=self.state,
                conversation=self._a2_conversation,
                validation_feedback=self._a2_validation_feedback,
            )
            turn = self.agent_runner.run_a2_turn(prompt)

            if turn.assistant_message:
                events.append(
                    ChatMessageEvent(
                        role="assistant",
                        text=turn.assistant_message,
                        agent_id="A2",
                    )
                )
                self._a2_conversation.append(
                    {"role": "assistant", "content": turn.assistant_message}
                )

            if turn.done:
                ok, message, cleaned = self.workflow._validate_a2_submission(
                    turn.synergy_themes,
                    turn.budget_tier,
                    turn.category_queue,
                )
                if ok:
                    self.state.synergy_themes = cleaned["synergy_themes"]
                    self.state.budget_tier = cleaned["budget_tier"]
                    self.state.category_queue = cleaned["category_queue"]
                    self.phase = "loading"
                    self.active_prompt = None
                    events.append(
                        ChatMessageEvent(
                            role="system",
                            text=(
                                "Confirmed strategy: "
                                f"themes={self.state.synergy_themes}, "
                                f"budget={self.state.budget_tier}, "
                                f"categories={self.state.category_queue}"
                            ),
                        )
                    )
                    events.append(
                        PhaseEvent(
                            phase_id="loading",
                            title="Generating Search Plans (A3) and Loading EDHREC",
                        )
                    )
                    self._start_background_loading()
                    return events

                self._a2_validation_feedback = message
                continue

            self._a2_validation_feedback = None
            self.active_prompt = PromptEvent(
                prompt_id=self._next_id("prompt"),
                kind="text",
                label="Reply to A2",
                placeholder="Answer A2's strategy question.",
            )
            events.append(self.active_prompt)
            return events

    def _advance_a1(self) -> list[UIEvent]:
        events: list[UIEvent] = []
        self.active_batch = None

        for _ in range(4):
            prompt = build_intake_prompt(
                conversation=self._a1_conversation,
                validation_feedback=self._a1_validation_feedback,
                search_feedback=self._a1_search_feedback,
            )
            turn = self.agent_runner.run_a1_turn(prompt)

            if turn.assistant_message:
                events.append(
                    ChatMessageEvent(
                        role="assistant",
                        text=turn.assistant_message,
                        agent_id="A1",
                    )
                )
                self._a1_conversation.append(
                    {"role": "assistant", "content": turn.assistant_message}
                )

            if turn.random_commander_request and not (
                self._a1_search_feedback
                and self._a1_search_feedback.startswith("Random commander pool from Scryfall:")
            ):
                candidates = self.scryfall.get_random_commander_candidates(count=8)
                self._a1_pending_search_cards = candidates
                self._a1_pending_search_mode = "random"
                self._a1_search_feedback = self._format_random_commander_feedback(candidates)
                self._a1_validation_feedback = None
                self._a1_pending_candidate_commander = None
                continue

            if turn.commander_search_query:
                candidates = self.scryfall.search_commander_candidates(
                    turn.commander_search_query
                )
                self._a1_pending_search_cards = candidates
                self._a1_pending_search_mode = "search"
                self._a1_search_feedback = self._format_commander_search_feedback(
                    turn.commander_search_query,
                    candidates,
                )
                self._a1_validation_feedback = None
                self._a1_pending_candidate_commander = None
                continue

            if turn.candidate_commander and turn.done:
                is_valid, message, card_data = self.scryfall.validate_commander_candidate(
                    turn.candidate_commander
                )
                if is_valid and card_data:
                    events.extend(
                        self._finalize_commander_ui(
                            card_data,
                            fallback_name=turn.candidate_commander,
                        )
                    )
                    return events

                self._a1_validation_feedback = message
                self._a1_search_feedback = None
                self._a1_pending_candidate_commander = None
                continue

            if turn.candidate_commander and not turn.done:
                self._a1_pending_candidate_commander = turn.candidate_commander
                self._a1_validation_feedback = None
                confirmation_card = ui_card_from_scryfall(
                    self.scryfall.lookup_card_by_name(turn.candidate_commander),
                    category="commander",
                    source_label="a1-confirmation",
                )
                if confirmation_card:
                    batch = RecommendationBatchEvent(
                        batch_id=self._next_id("batch"),
                        agent_id="A1",
                        title="Confirm Commander",
                        category="commander",
                        action_mode="confirm_one",
                        cards=[confirmation_card],
                        allow_skip=False,
                    )
                    self.active_batch = _ActiveBatchState(
                        batch_id=batch.batch_id,
                        mode="confirm_one",
                        title="Confirm Commander",
                        category="commander",
                        cards=batch.cards,
                        candidate_name=turn.candidate_commander,
                        allow_skip=False,
                    )
                    events.append(batch)
                self.active_prompt = PromptEvent(
                    prompt_id=self._next_id("prompt"),
                    kind="text",
                    label="Reply to A1",
                    placeholder="Confirm this commander or ask for a different one.",
                )
                events.append(self.active_prompt)
                return events

            if self._a1_pending_search_cards and self._a1_pending_search_mode:
                cards = [
                    ui_card_from_summary(
                        candidate,
                        category="commander",
                        source_label=f"a1-{self._a1_pending_search_mode}",
                    )
                    for candidate in self._a1_pending_search_cards
                ]
                cards = [card for card in cards if card]
                if cards:
                    title = (
                        "Choose a Random Commander"
                        if self._a1_pending_search_mode == "random"
                        else "Choose a Commander"
                    )
                    batch = RecommendationBatchEvent(
                        batch_id=self._next_id("batch"),
                        agent_id="A1",
                        title=title,
                        category="commander",
                        action_mode="pick_one",
                        cards=cards,
                    )
                    self.active_batch = _ActiveBatchState(
                        batch_id=batch.batch_id,
                        mode=self._a1_pending_search_mode,
                        title=title,
                        category="commander",
                        cards=batch.cards,
                        allow_skip=True,
                    )
                    events.append(batch)
                self.active_prompt = PromptEvent(
                    prompt_id=self._next_id("prompt"),
                    kind="text",
                    label="Reply to A1",
                    placeholder="Type a commander name or click a card above.",
                )
                events.append(self.active_prompt)
                return events

            self._a1_validation_feedback = None
            self.active_prompt = PromptEvent(
                prompt_id=self._next_id("prompt"),
                kind="text",
                label="Reply to A1",
                placeholder="Tell A1 what commander you want to build.",
            )
            events.append(self.active_prompt)
            return events

        if not self.active_prompt:
            self.active_prompt = PromptEvent(
                prompt_id=self._next_id("prompt"),
                kind="text",
                label="Reply to A1",
                placeholder="Tell A1 what commander you want to build.",
            )
            events.append(self.active_prompt)
        return events

    def _finalize_commander_ui(self, card_data: dict, fallback_name: str) -> list[UIEvent]:
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
        self.phase = "a2"
        self.active_prompt = None
        self.active_batch = None
        return [
            ChatMessageEvent(
                role="system",
                text=(
                    f"Confirmed commander: {self.state.commander} "
                    f"[{''.join(self.state.cid) or 'C'}]"
                ),
            ),
            DeckStateEvent(
                commander=self.state.commander,
                category_counts=self.state.category_counts(),
                total_non_commander_cards=self.state.total_non_commander_cards(),
                decklist_preview=self.get_deck_state_event().decklist_preview,
            ),
            PhaseEvent(phase_id="a2", title="Strategy Planning (A2)"),
            *self._advance_a2(),
        ]

    def _build_a4_rounds(self) -> list[tuple[str, str | None]]:
        rounds: list[tuple[str, str | None]] = []
        for category in self.state.category_queue:
            if category == "synergy" and self.state.synergy_themes:
                for theme in self.state.synergy_themes:
                    rounds.append((category, theme))
            else:
                rounds.append((category, None))
        return rounds

    def _prepare_a4_round(
        self,
        category: str,
        theme_focus: str | None,
    ) -> _PrecomputedA4Round:
        if category == "synergy" and theme_focus:
            category_plan = self.state.synergy_theme_plans.get(
                theme_focus,
                self.state.category_tags.get(category),
            )
        else:
            category_plan = self.state.category_tags.get(category)

        selected_tags, search_intents, queries, aggregated, candidate_pool = (
            self.workflow._collect_category_search_results_from_plan(
                category_plan or A3CategoryPlan(),
                category=category,
            )
        )

        title = (
            f"{category.title()} Recommendations"
            if not theme_focus
            else f"{category.title()} - {theme_focus}"
        )
        target_count = self.workflow._determine_target_recommendation_count(
            category,
            len(candidate_pool),
        )
        if not candidate_pool or not target_count:
            return _PrecomputedA4Round(
                title=title,
                category=category,
                theme_focus=theme_focus,
                no_results_message=(
                    f'No usable live Scryfall results were available for '
                    f'{category}{f" ({theme_focus})" if theme_focus else ""}.'
                ),
                search_plan=SearchPlan(
                    category=category if not theme_focus else f"{category}:{theme_focus}",
                    selected_tags=selected_tags,
                    search_intents=search_intents,
                    queries=queries,
                    recommended_cards=[],
                ),
            )

        prompt = build_search_ranking_prompt(
            self.state,
            category,
            theme_focus,
            selected_tags,
            search_intents,
            queries,
            self.workflow._build_candidate_pool_summary(candidate_pool),
            self.workflow._current_deck_names(),
            target_count,
        )
        turn = self.agent_runner.run_a4_turn(prompt)
        recommended_cards = self.workflow._resolve_a4_recommendations(
            candidate_pool,
            turn.recommended_card_names,
            target_count,
        )
        note_lookup = self.workflow._pair_notes_with_names(
            turn.recommended_card_names,
            turn.brief_recommendation_notes,
        )
        ui_cards: list[UICard] = []
        for card in recommended_cards:
            ui_card = ui_card_from_summary(
                {
                    **card,
                    "image_url": card.get("image_url"),
                },
                note=note_lookup.get(str(card.get("name", "")).lower()),
                category=category,
                source_label="a4",
            )
            if ui_card:
                ui_cards.append(ui_card)

        return _PrecomputedA4Round(
            title=title,
            category=category,
            theme_focus=theme_focus,
            cards=ui_cards,
            assistant_message=turn.assistant_message,
            allow_skip=True,
            source_query=queries[0] if queries else None,
            search_plan=SearchPlan(
                category=category if not theme_focus else f"{category}:{theme_focus}",
                selected_tags=selected_tags,
                search_intents=search_intents,
                queries=queries,
                recommended_cards=recommended_cards,
            ),
        )

    def _show_a4_batch(self, index: int) -> list[UIEvent]:
        if index < 0 or index >= len(self._a4_precomputed_rounds):
            return []

        round_data = self._a4_precomputed_rounds[index]
        events: list[UIEvent] = []
        self.active_prompt = None
        self.active_batch = None

        if round_data.no_results_message:
            events.append(
                ChatMessageEvent(
                    role="system",
                    text=round_data.no_results_message,
                )
            )
            return events

        self.active_batch = _ActiveBatchState(
            batch_id=self._next_id("batch"),
            mode="add",
            title=round_data.title,
            category=round_data.category,
            theme_focus=round_data.theme_focus,
            cards=round_data.cards,
            allow_skip=True,
            source_query=round_data.source_query,
            batch_index=index,
            can_go_prev=index > 0,
            can_go_next=(index + 1) < len(self._a4_precomputed_rounds),
            next_pending=(index + 1) >= len(self._a4_precomputed_rounds) and not self._a4_precompute_complete,
        )
        if round_data.search_plan and not round_data.search_plan_recorded:
            self.state.search_history.append(round_data.search_plan)
            round_data.search_plan_recorded = True
        if round_data.assistant_message:
            events.append(
                ChatMessageEvent(
                    role="assistant",
                    text=round_data.assistant_message,
                    agent_id="A4",
                )
            )
        events.append(
            RecommendationBatchEvent(
                batch_id=self.active_batch.batch_id,
                agent_id="A4",
                title=self.active_batch.title,
                category=round_data.category,
                theme_focus=round_data.theme_focus,
                action_mode="add",
                cards=round_data.cards,
                allow_skip=True,
            )
        )
        return events

    def _advance_a4(self) -> list[UIEvent]:
        return self._show_a4_batch(self._a4_round_index)

    def _add_recommendation_card(self, card_name: str) -> list[UIEvent]:
        if not self.active_batch:
            return []
        match = next(
            (card for card in self.active_batch.cards if card.name.lower() == card_name.lower()),
            None,
        )
        if not match or self.state.has_card(match.name):
            return []
        self.state.add_card(
            DeckCard(
                name=match.name,
                category=self.active_batch.category,
                mana_cost=match.mana_cost,
                type_line=match.type_line,
                oracle_text=match.oracle_text,
                usd=match.usd,
                edhrec_rank=match.edhrec_rank,
                source="a4",
                source_query=self.active_batch.source_query,
            )
        )
        return [
            ChatMessageEvent(
                role="system",
                text=f'Added "{match.name}" to {self.active_batch.category}.',
            ),
            self.get_deck_state_event(),
        ]

    def _start_background_loading(self) -> None:
        with self._bg_lock:
            if not self.a3_started:
                self.a3_started = True
                Thread(target=self._run_a3_background, daemon=True).start()
            if not self.edhrec_started:
                self.edhrec_started = True
                Thread(target=self._run_edhrec_background, daemon=True).start()

    def _run_a3_background(self) -> None:
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
            ok, message, cleaned, cleaned_theme_plans = self.workflow._validate_a3_category_plans(
                result.category_plans,
                result.synergy_theme_plans,
                all_tags,
            )
            if ok:
                with self._bg_lock:
                    self.state.category_tags = cleaned
                    self.state.synergy_theme_plans = cleaned_theme_plans
                    self._a4_rounds = self._build_a4_rounds()
                    self._a4_round_index = 0
                    self.a3_complete = True
                    self.a3_validation_notes = message or None
                    if self.phase == "loading":
                        self.phase = "a4_pending"
                self._start_background_a4_precompute()
                return
            validation_feedback = message

        with self._bg_lock:
            self.state.synergy_theme_plans = {}
            self.a3_complete = True
            self.a3_error = validation_feedback or "A3 did not return valid search plans."
            if self.phase == "loading":
                self.phase = "a4_pending"

    def _start_background_a4_precompute(self) -> None:
        with self._bg_lock:
            if self._a4_precompute_started:
                return
            self._a4_precompute_started = True
            self._a4_precompute_total = len(self._a4_rounds or self._build_a4_rounds())
        Thread(target=self._run_a4_precompute_background, daemon=True).start()

    def _run_a4_precompute_background(self) -> None:
        try:
            rounds = list(self._a4_rounds or self._build_a4_rounds())
            for category, theme_focus in rounds:
                prepared_round = self._prepare_a4_round(category, theme_focus)
                if prepared_round.no_results_message:
                    continue
                with self._bg_lock:
                    self._a4_precomputed_rounds.append(prepared_round)
            with self._bg_lock:
                self._a4_precompute_complete = True
        except Exception as exc:
            with self._bg_lock:
                self._a4_precompute_error = str(exc)
                self._a4_precompute_complete = True

    def _run_edhrec_background(self) -> None:
        if not self.state.commander:
            with self._bg_lock:
                self.edhrec_error = "Commander is not set."
            return
        try:
            data = self.edhrec.get_commander_recommendations(self.state.commander)
            high_synergy_cards = self._build_edhrec_section(data, "high_synergy_cards", "high_synergy")
            top_cards = self._build_edhrec_section(data, "top_cards", "top_cards")
            with self._bg_lock:
                self.edhrec_sections["high_synergy"] = high_synergy_cards
                self.edhrec_sections["top_cards"] = top_cards
                self.edhrec_ready = True
        except Exception as exc:
            with self._bg_lock:
                self.edhrec_error = str(exc)

    def _build_edhrec_section(self, data: dict, source_key: str, source_label: str) -> list[UICard]:
        cards: list[UICard] = []
        by_name: dict[str, dict] = {}
        current_names = {name.lower() for name in self.workflow._current_deck_names()}

        for card in data.get(source_key, []):
            name = str(card.get("name") or "").strip()
            lowered = name.lower()
            if not name or lowered in current_names:
                continue
            scryfall_card = self.scryfall.lookup_card_by_name(name)
            if not scryfall_card:
                continue
            if self.state.cid and not self.scryfall.is_card_within_cid(scryfall_card, self.state.cid):
                continue
            if not self.scryfall.is_card_within_budget(scryfall_card, self.state.budget_tier):
                continue
            summary = {
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
                "image_url": self.scryfall.get_card_image_url(scryfall_card),
                "scryfall_uri": scryfall_card.get("scryfall_uri"),
            }
            ui_card = ui_card_from_summary(
                summary,
                category="synergy",
                source_label=source_label,
            )
            if not ui_card:
                continue
            cards.append(ui_card)
            by_name[ui_card.name.lower()] = summary

        with self._bg_lock:
            self._edhrec_cards_by_section_and_name[source_label] = by_name
        return cards

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
            + "\nChoose one interesting commander from this pool, explain the pick briefly, and ask the user to confirm it."
        )

    def _next_id(self, prefix: str) -> str:
        self._event_counter += 1
        return f"{prefix}-{self._event_counter}"

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        lowered = text.strip().lower()
        return lowered in {
            "yes",
            "y",
            "yeah",
            "yep",
            "correct",
            "confirm",
            "confirmed",
            "proceed",
            "verify",
            "sounds good",
            "that works",
        }
