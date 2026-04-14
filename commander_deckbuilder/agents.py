"""Prompt builders for the commander workflow."""

from __future__ import annotations

import json
from textwrap import dedent

from .constants import CATEGORY_ORDER
from .models import AgentPrompt, DeckState

DUAL_LAND_PRIORITY_GUIDANCE = dedent("""
    Dual-land priority order:
    1. ABU dual land
    2. Fetchland
    3. Shockland
    4. Bondland
    5. Surveil land
    6. Slowland
    7. Verge land
    8. Filter land
    9. Painland
    10. Canopy land
    11. Bounce land
    12. Checkland
    13. Signet land
    14. Pathway
    15. Temple
    """).strip()


def _format_commander_context(state: DeckState) -> str:
    commander_cards = state.decklist.get("commander", [])
    if not commander_cards:
        return "Commander details unavailable."

    commander = commander_cards[0]
    oracle_text = commander.oracle_text or "Oracle text unavailable."
    type_line = commander.type_line or "Type line unavailable."
    mana_cost = commander.mana_cost or "Mana cost unavailable."
    return (
        f"Name: {commander.name}\n"
        f"Mana cost: {mana_cost}\n"
        f"Type line: {type_line}\n"
        f"Oracle text: {oracle_text}"
    )


def build_intake_prompt(
    conversation: list[dict[str, str]] | None = None,
    validation_feedback: str | None = None,
    search_feedback: str | None = None,
) -> AgentPrompt:
    conversation = conversation or []
    conversation_block = json.dumps(conversation, indent=2)
    validation_block = validation_feedback or "None yet."
    search_block = search_feedback or "None yet."

    return AgentPrompt(
        agent_id="A1",
        agent_name="Intake Agent",
        system_prompt=(
            "You are A1, the Intake Agent for an MTG Commander deck-building assistant. "
            "Your job is to talk with the user until they settle on one commander card. "
            "Plain code will verify any candidate with Scryfall and feed the result back "
            "to you. Plain code can also search Scryfall for commander candidates when "
            "the user only knows part of a name. Keep the conversation concise and focused "
            "on getting to one valid commander."
        ),
        user_prompt=dedent(f"""
            Continue the A1 commander-intake conversation.

            Conversation so far:
            {conversation_block}

            Latest plain-code validation feedback:
            {validation_block}

            Latest plain-code commander search feedback:
            {search_block}

            Rules:
            - On the first turn, open simply and directly. Ask what commander the user wants to build, and mention that partial names are okay.
            - If the user has not clearly chosen one exact commander card, ask one concise follow-up question.
            - If the conversation mentions a possible commander but the user has not clearly committed to it yet, you may mention it in `assistant_message` but set `candidate_commander` to null and `done` to false.
            - If the user gives what looks like a full commander name, prefer setting `candidate_commander` to that exact name rather than triggering a partial-name lookup.
            - If the user only knows part of a commander name, says they do not know the full name, or asks you to look it up, you may request a commander search.
            - To request a commander search, set `commander_search_query` to a short search string like `frodo` or `lotho`, and keep `candidate_commander` null and `done` false.
            - If you request a commander search, do not ask the user for permission first. Briefly say that you are looking it up, or leave `assistant_message` empty.
            - If commander search feedback is available, use it to present the commander options clearly and ask the user to choose one.
            - If the user asks you to pick a random commander, surprise them, or choose for them, set `random_commander_request` to true and keep `candidate_commander` null and `done` false.
            - When random commander feedback is available, recommend one commander from the provided pool and explain the choice briefly.
            - If random commander feedback is already available, do not request another random pool.
            - If random commander feedback says the Scryfall random lookup was unavailable or too slow, choose one commander from your own knowledge instead, set `candidate_commander` to that exact name, keep `done` false, and ask the user to confirm it.
            - If commander search feedback or random commander feedback is available and the user asks you to choose for them, pick one exact commander from the provided options, set `candidate_commander` to that exact name, keep `done` false, and ask the user to confirm it.
            - If there is only one strong commander result and the user seems to want that card, you may suggest it and ask for confirmation, but keep `done` false until they confirm.
            - Only set `candidate_commander` when the user has clearly chosen one exact commander card.
            - If the user gives a clear affirmative reply like yes, yep, correct, proceed, or verify after you have already identified one exact commander, keep the same `candidate_commander` and set `done` to true.
            - Only set `done` to true when the user has clearly confirmed that exact commander and you are ready for plain code to finalize intake.
            - If validation feedback says the candidate is invalid, explain that briefly and ask the user for another commander.
            - Do not keep re-asking to verify the same commander after the user already affirmed it.
            - Do not mention JSON or internal fields.
            - Do not invent Scryfall facts. The validation feedback is the source of truth.
            - Do not ask meta questions about how search results should be displayed. If search results are available, just present the options briefly.
            - Avoid clunky multi-option opener phrasing like asking both "pick one or search by part of the name" unless the user is actually undecided.
            - Output JSON only. Do not include any prose outside the JSON object.
            - Keep responses brief enough to feel like a chat.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", '
            '"candidate_commander": "Atraxa, Praetors\' Voice" | null, '
            '"commander_search_query": "frodo" | null, '
            '"random_commander_request": true | false, "done": true | false}.'
        ),
    )


def build_strategy_prompt(state: DeckState) -> AgentPrompt:
    return build_strategy_prompt_with_context(
        state=state,
        conversation=[],
        validation_feedback=None,
    )


def build_strategy_prompt_with_context(
    state: DeckState,
    conversation: list[dict[str, str]] | None = None,
    validation_feedback: str | None = None,
) -> AgentPrompt:
    conversation = conversation or []
    conversation_block = json.dumps(conversation, indent=2)
    validation_block = validation_feedback or "None yet."
    commander_context = _format_commander_context(state)

    return AgentPrompt(
        agent_id="A2",
        agent_name="Strategy Agent",
        system_prompt=(
            "You are A2, the Strategy Agent for an MTG Commander deck-building assistant. "
            "Your job is to help the user shape the deck's strategic direction after the "
            "commander has been chosen. Keep the conversation focused on three things: "
            "synergy themes, budget tier, and which deck-building categories to include."
        ),
        user_prompt=dedent(f"""
            Continue the A2 strategy-planning conversation.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Commander card details:
            {commander_context}

            Conversation so far:
            {conversation_block}

            Latest plain-code validation feedback:
            {validation_block}

            Budget tiers:
            - low
            - medium
            - high
            - none

            Standard categories:
            {CATEGORY_ORDER}

            Rules:
            - Read the commander card details before suggesting or discussing synergy themes.
            - Collect enough information to produce a short list of synergy themes.
            - Collect one valid budget tier from: low, medium, high, none.
            - Collect an ordered list of deck categories the user wants included.
            - If the user wants the standard categories, you may use the full standard list.
            - Treat `synergy` as a core category whenever the user has clear deck themes, even if they do not name that category explicitly.
            - Synergy themes should be short and concrete.
            - Only include synergy themes the user clearly stated, or themes the user explicitly agreed to after you proposed them.
            - If you are proposing possible synergy themes for the user to choose from, keep `done` false.
            - Ask for only one missing area at a time.
            - Priority order for missing information:
              1. synergy themes
              2. budget tier
              3. category queue
            - Do not ask for all remaining requirements in one message.
            - If you say you are listing or suggesting themes, include the actual theme options in that same assistant message.
            - Never send a teaser like "Here are some themes" without the themes themselves.
            - When proposing synergy themes, provide the options immediately and end by asking which of those themes the user wants.
            - Only set `done` to true when synergy themes, budget tier, and category queue are all clear enough to finalize.
            - Don't send a message talking about what the user wants to do next, from your conversation the user will be passed to another agent. 
            - Do not mention JSON or internal field names.
            - Keep the conversation brief and practical.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", "synergy_themes": ["..."], '
            '"budget_tier": "low|medium|high|none|null", "category_queue": ["synergy", "ramp"], '
            '"done": true | false}.'
        ),
    )


def build_search_tag_prompt(
    state: DeckState, category: str, all_tags: list[str]
) -> AgentPrompt:
    return AgentPrompt(
        agent_id="A3",
        agent_name="Search Agent",
        system_prompt=(
            "You are the Search Agent for an MTG Commander deck-building assistant. "
            "You read a full list of Scryfall tags and choose the tags that best match "
            "the current category and deck strategy semantically."
        ),
        user_prompt=dedent(f"""
            Placeholder call for semantic tag selection.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Current category: {category}
            Existing category counts: {state.category_counts()}

            Available Scryfall tags from tools/scryfall_tags.json:
            {all_tags}

            Read through the tag list semantically and choose the best 3-5 tags for this
            category and strategy. Do not rely on literal keyword overlap alone.
            """).strip(),
        expected_output=(
            'Return JSON like {"selected_tags": ["tag-1", "tag-2", "tag-3"], '
            '"reasoning": "..."}'
        ),
    )


def build_tag_prep_prompt(
    state: DeckState,
    all_tags: list[str],
    validation_feedback: str | None = None,
) -> AgentPrompt:
    commander_context = _format_commander_context(state)
    validation_block = validation_feedback or "None yet."
    return AgentPrompt(
        agent_id="A3",
        agent_name="Tag Prep Agent",
        system_prompt=(
            "You are A3, the silent Tag Prep Agent for an MTG Commander deck-building assistant. "
            "Your job is to read the commander's card text, the selected synergy themes, and the "
            "selected categories, then prepare strong category-specific Scryfall search plans. "
            "You are not user-facing. Plain code will validate your tags and queries before using them."
        ),
        user_prompt=dedent(f"""
            Prepare category-specific search plans for later Scryfall searches.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Commander card details:
            {commander_context}

            Budget tier: {state.budget_tier or "UNKNOWN"}
            Synergy themes: {state.synergy_themes or "UNKNOWN"}
            Category queue: {state.category_queue or "UNKNOWN"}

            Latest plain-code validation feedback:
            {validation_block}

            Available Scryfall tags from tools/scryfall_tags.json:
            {all_tags}

            Rules:
              - For each category in the category queue, return:
                - 2-5 relevant tags when useful
                - 1-3 search intents
                - 2-5 candidate Scryfall queries
              - It is better to return fewer strong candidate queries than to fill the quota with fragile or overfit ones.
              - If the `synergy` category is present, also return a separate `synergy_theme_plans` mapping with one plan per declared synergy theme.
              - Treat the declared synergy themes as required search drivers, not optional background context.
              - Across the full output, make sure every declared synergy theme is represented by at least one tag, search intent, or candidate query.
              - If the `synergy` category is present, its plan must directly target the declared synergy themes rather than generic good-stuff cards.
              - Each entry in `synergy_theme_plans` should focus tightly on that one theme instead of combining all themes together.
              - Use the tag list semantically, not only by keyword overlap.
              - Prefer tags that are broad enough to produce useful searches.
              - Candidate queries should be valid Scryfall search strings whenever possible.
            - Prefer broad, robust Scryfall queries over brittle exact-phrase oracle searches.
            - Avoid very narrow quoted oracle fragments unless they are extremely likely to match many relevant cards.
            - Prefer category/type/cmc/keyword style filters first, and only add oracle text when it meaningfully improves relevance.
            - Under low-budget constraints, favor broader queries because the budget filter already shrinks the result pool.
            - Avoid redundant color constraints such as adding `identity=` or similar when plain code will already apply `id<=CID`.
            - Do not include both `identity=` and `id<=` in the same query.
            - Prefer `t:` over `type:` and `o:` over `oracle:` for cleaner Scryfall syntax.
            - When combining alternatives, use parentheses carefully so the whole query stays valid.
            - Avoid queries that depend on exact full rules sentences like `o:"return target creature to its owner's hand"` when broader text like `o:"return target"` plus type/category filters will do.
            - For cantrips and cheap interaction, prefer broad low-CMC searches rather than exact mini-phrases that may miss valid cards.
            - For the `draw` category specifically, do not use the `cantrip` otag. Treat simple self-replacing cantrips as support pieces, not as meaningful draw-category hits.
            - For the `draw` category, prioritize tags and queries that find real card advantage, repeatable draw engines, burst draw, or multi-card draw effects.
            - If a query idea feels likely to return zero results, broaden it rather than forcing a highly specific phrase match.
            - Candidate queries may use otag, oracle text, type filters, mana value filters, power/toughness filters, or other normal Scryfall syntax.
            - Note on MTG syntax: all instances of "enters the battlefield" have been replaced with just "enters" so construct your queries accordingly.
            - Do not rely on otag alone when the concept is better captured by rules text or card types.
            - Think in terms of search intents first, then produce queries that match those intents.
            - The most important thing is relevance to the commander, synergy themes, and requested category.
            - Only return categories that are in the category queue.
            - Output only the search plans. Do not include reasoning prose outside the JSON object.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"category_plans": {"synergy": {"tags": ["tag-1", "tag-2"], '
            '"search_intents": ["intent-1", "intent-2"], "candidate_queries": ["query-1", "query-2"]}, '
            '"draw": {"tags": ["tag-3"], "search_intents": ["intent-3"], '
            '"candidate_queries": ["query-3", "query-4"]}}, '
            '"synergy_theme_plans": {"Theme name": {"tags": ["tag-1"], "search_intents": ["intent-1"], "candidate_queries": ["query-1", "query-2"]}}}.'
        ),
    )


def build_search_ranking_prompt(
    state: DeckState,
    category: str,
    theme_focus: str | None,
    selected_tags: list[str],
    search_intents: list[str],
    queries: list[str],
    candidate_pool_summary: list[dict[str, str | int | None | list[str]]],
    current_deck_names: list[str],
    target_recommendation_count: int,
) -> AgentPrompt:
    return AgentPrompt(
        agent_id="A4",
        agent_name="Recommendation Agent",
        system_prompt=(
            "You are A4, the Recommendation Agent for an MTG Commander deck-building assistant. "
            "You receive a compact pool of candidate cards that plain code already trimmed, "
            "deduped, and filtered against the current deck. Your job is to choose the best cards "
            "for the current category and explain each pick very briefly."
        ),
        user_prompt=dedent(f"""
            Recommend the best cards for this category.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Current category: {category}
            Current theme focus: {theme_focus or "None"}
            Selected tags: {selected_tags}
            Search intents: {search_intents}
            Queries run: {queries}
            Current deck card names:
            {current_deck_names}

            Candidate pool:
            {json.dumps(candidate_pool_summary, indent=2)}

            Target recommendation count: {target_recommendation_count}

            Rules:
            - Choose only from the provided candidate pool.
            - Recommend up to the target recommendation count, not more.
            - Prioritize strong synergy with the commander, selected themes, and current category.
            - If a current theme focus is provided, prioritize cards that specifically advance that theme before broader category staples.
            - Prefer cards with clear fit over generic staples when possible.
            - Each card selected should be relevant to the current category (ex. curr category: draw, only suggest cards that gain lots of card advantage for the player)
            - For the `draw` category specifically, prioritize meaningful card advantage over mere card selection or self-replacement; avoid recommending cards whose only draw role is being a lightweight cantrip unless the pool is extremely thin.
            - For the `draw` category, aim to fill the full target recommendation count whenever the candidate pool supports it.
            - Do not recommend cards already in the current deck.
            - Each note must match the corresponding recommended card by position.
            - Keep each note extremely brief: a short phrase or one short sentence, ideally 3-8 words and never more than 12 words.
            - Do not write paragraphs or long explanations.
            - Keep `assistant_message` brief.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", "recommended_card_names": ["..."], '
            '"brief_recommendation_notes": ["...", "..."]}.'
        ),
    )


def build_edhrec_opening_prompt(
    state: DeckState,
    edhrec_url: str,
    candidate_pool_summary: list[dict[str, str | int | None]],
    current_deck_names: list[str],
    target_recommendation_count: int,
) -> AgentPrompt:
    return AgentPrompt(
        agent_id="A4",
        agent_name="Recommendation Agent",
        system_prompt=(
            "You are A4, the Recommendation Agent for an MTG Commander deck-building assistant. "
            "You are starting with commander-specific EDHREC data. Choose the best opening recommendations "
            "for this deck based on the commander's themes and keep every note extremely brief."
        ),
        user_prompt=dedent(f"""
            Recommend the best opening cards from EDHREC for this commander.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            EDHREC page: {edhrec_url}
            Current deck card names:
            {current_deck_names}

            Candidate pool from EDHREC:
            {json.dumps(candidate_pool_summary, indent=2)}

            Target recommendation count: {target_recommendation_count}

            Rules:
            - Choose only from the provided EDHREC candidate pool.
            - Recommend up to the target recommendation count, not more.
            - Prefer cards that most directly match the selected themes, not just generic popularity.
            - Use both `high_synergy` and `top_cards` information when deciding.
            - Respect the shown card prices and selected budget tier.
            - Do not recommend cards already in the current deck.
            - Each note must match the corresponding recommended card by position.
            - Keep each note extremely brief: a short phrase or one short sentence, ideally 3-8 words and never more than 12 words.
            - Keep `assistant_message` brief.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", "recommended_card_names": ["..."], '
            '"brief_recommendation_notes": ["...", "..."]}.'
        ),
    )


def build_lands_prompt(state: DeckState) -> AgentPrompt:
    return build_lands_intake_prompt(
        state=state,
        utility_candidates=[],
        average_mana_value=0.0,
        example_reference="",
    )


def build_lands_intake_prompt(
    state: DeckState,
    utility_candidates: list[dict[str, str | int | None]],
    average_mana_value: float,
    example_reference: str,
) -> AgentPrompt:
    commander_context = _format_commander_context(state)
    return AgentPrompt(
        agent_id="A5",
        agent_name="Lands Agent",
        system_prompt=(
            "You are A5, the Lands Agent for an MTG Commander deck-building assistant. "
            "Your first job is to recommend a broad shortlist of relevant utility lands and propose "
            "a target total land count."
        ),
        user_prompt=dedent(f"""
            Start the A5 lands phase.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Commander card details:
            {commander_context}

            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Current non-commander card count: {state.total_non_commander_cards()}
            Average mana value estimate: {average_mana_value:.2f}
            Current deck card names:
            {state.to_dict().get("decklist", {})}

            Utility land candidates:
            {json.dumps(utility_candidates, indent=2)}

            Landbase examples reference:
            {example_reference}

            Dual-land priority guidance:
            {DUAL_LAND_PRIORITY_GUIDANCE}

            Rules:
            - Recommend many relevant utility lands from the provided candidate pool when they exist.
            - It is fine to recommend substantially more utility lands than the final deck will be allowed to play.
            - The utility-land cap only limits how many the user will finally add, not how many you may recommend now.
            - Keep utility recommendations relevant to the commander's strategy and the deck themes.
            - Propose a total land count that is at least 37.
            - Increase land count by 1-2 if average mana value is above 3.5.
            - If themes strongly indicate land focus or big-mana plans, you may push land count into the 40-42 range.
            - Keep `assistant_message` concise and user-facing.
            - Do not build the final mana base yet.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", '
            '"recommended_utility_land_names": ["..."], "proposed_target_land_count": 38, '
            '"done": false}.'
        ),
    )


def build_lands_final_prompt(
    state: DeckState,
    selected_utility_land_names: list[str],
    confirmed_target_land_count: int,
    utility_candidates: list[dict[str, str | int | None]],
    dual_candidates_by_pair: dict[str, list[dict[str, str | int | None]]],
    tri_candidates: list[dict[str, str | int | None]],
    fetch_candidates: list[dict[str, str | int | None]],
    color_pip_counts: dict[str, int],
    average_mana_value: float,
    example_reference: str,
) -> AgentPrompt:
    commander_context = _format_commander_context(state)
    return AgentPrompt(
        agent_id="A5",
        agent_name="Lands Agent",
        system_prompt=(
            "You are A5, the Lands Agent for an MTG Commander deck-building assistant. "
            "Your job is to build the final mana base from the provided land candidate pools and hard rules."
        ),
        user_prompt=dedent(f"""
            Build the final mana base for this deck.

            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Commander card details:
            {commander_context}

            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Confirmed target land count: {confirmed_target_land_count}
            Selected utility lands:
            {selected_utility_land_names}

            Average mana value estimate: {average_mana_value:.2f}
            Color pip counts:
            {color_pip_counts}

            Utility land candidates:
            {json.dumps(utility_candidates, indent=2)}

            Dual land candidates by color pair:
            {json.dumps(dual_candidates_by_pair, indent=2)}

            Tri-land / triome candidates:
            {json.dumps(tri_candidates, indent=2)}

            Fetch-land candidates:
            {json.dumps(fetch_candidates, indent=2)}

            Landbase examples reference:
            {example_reference}

            Dual-land priority guidance:
            {DUAL_LAND_PRIORITY_GUIDANCE}

            Rules:
            - Build the final mana base now.
            - Keep the final total land count equal to the confirmed target land count.
            - Preserve the user-selected utility lands in the final mana base unless they exceed the allowed utility cap.
            - Respect these hard rules:
              - minimum 1 basic of each color
              - utility-land caps by color count
              - every 2+ color deck includes Command Tower
              - low/medium 2+ color decks always include Path of Ancestry
              - fetches only for high/none budgets
              - 5-color decks cap triomes at 4
            - For 3+ color decks, include tri-lands or triomes from the provided pool.
            - Use the selected utility lands as the starting utility package.
            - Choose duals, tri-lands, fetches, and basics from the provided pools only.
            - Follow the dual-land priority guidance closely.
            - Fill with higher-priority dual/fixing land cycles first while there is room in the mana base before moving down to lower-priority cycles.
            - Do not skip to lower-priority duals if stronger higher-priority options are still available, legal, and budget-appropriate.
            - Avoid lands that always enter tapped unless they are clearly part of the preferred cycle/order shown in the examples reference.
            - Do not blanket-reject valuable tapped lands such as surveil lands if they fit the example priorities and deck needs.
            - Basic land counts should reflect color pip demand while keeping at least 1 basic of each color.
            - The more colors the deck has, the less total basics it should include (2-color: ~20, 3-color: ~10, 4-color: ~7, 5-color: ~5) 
            - Keep `assistant_message` very brief.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", "utility_land_names": ["..."], '
            '"dual_land_names": ["..."], "tri_land_names": ["..."], "fetch_land_names": ["..."], '
            '"basic_land_counts": {"Plains": 4, "Island": 3}, "done": true}.'
        ),
    )


def build_completion_prompt(state: DeckState) -> AgentPrompt:
    return build_completion_prompt_with_candidates(
        state=state,
        mode="add",
        target_fill_counts={},
        target_cut_counts={},
        current_deck_summary_by_category={},
        candidate_pools_by_category={},
        current_deck_names=[],
    )


def build_completion_prompt_with_candidates(
    state: DeckState,
    mode: str,
    target_fill_counts: dict[str, int],
    target_cut_counts: dict[str, int],
    current_deck_summary_by_category: dict[str, list[dict[str, str | int | None | list[str]]]],
    candidate_pools_by_category: dict[str, list[dict[str, str | int | None | list[str]]]],
    current_deck_names: list[str],
) -> AgentPrompt:
    return AgentPrompt(
        agent_id="A6",
        agent_name="Completion Agent",
        system_prompt=(
            "You are A6, the Completion Agent for an MTG Commander deck-building assistant. "
            "You receive compact candidate pools by category after the main discovery and lands phases. "
            "Your job is to choose a final batch of cards to fill the remaining deck slots while respecting "
            "the deck's themes and the intended category balance."
        ),
        user_prompt=dedent(f"""
            Commander: {state.commander or "UNKNOWN"}
            Color identity: {state.cid or "UNKNOWN"}
            Budget tier: {state.budget_tier or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Current category counts: {state.category_counts()}
            Current deck card names:
            {current_deck_names}
            Remaining slots: {state.remaining_slots()}
            Mode: {mode}
            Target fill counts by category:
            {json.dumps(target_fill_counts, indent=2)}
            Target cut counts by category:
            {json.dumps(target_cut_counts, indent=2)}

            Current deck summaries by category:
            {json.dumps(current_deck_summary_by_category, indent=2)}

            Candidate pools by category:
            {json.dumps(candidate_pools_by_category, indent=2)}

            Rules:
            - If mode is `add`, choose only from the provided candidate pools and fill categories according to the target fill counts as closely as possible.
            - If mode is `cut`, choose only from the current deck summaries and recommend cuts according to the target cut counts as closely as possible.
            - In cut mode, prioritize cutting redundant, low-synergy, lower-impact, or off-plan cards before stronger core cards.
            - In add mode, prioritize cards that are on-theme and category-appropriate over generic staples.
            - Do not recommend cards already in the current deck when mode is `add`.
            - Keep notes extremely brief, similar to A4.
            - Each note list must line up with the corresponding names for its category.
            - Keep `assistant_message` brief.
            - Output JSON only.
            """).strip(),
        expected_output=(
            'Return strict JSON like {"assistant_message": "...", '
            '"recommendations_by_category": {"draw": ["..."], "ramp": ["..."]}, '
            '"cuts_by_category": {"draw": ["..."], "other": ["..."]}, '
            '"brief_notes_by_category": {"draw": ["...", "..."], "ramp": ["..."]}}.'
        ),
    )


def build_export_prompt(state: DeckState) -> AgentPrompt:
    return AgentPrompt(
        agent_id="A7",
        agent_name="Export Agent",
        system_prompt=(
            "You are the Export Agent for an MTG Commander deck-building assistant. "
            "Summarize the deck and note any validation issues."
        ),
        user_prompt=dedent(f"""
            Placeholder call.

            Commander: {state.commander or "UNKNOWN"}
            Themes: {state.synergy_themes or "UNKNOWN"}
            Category counts: {state.category_counts()}
            Total non-commander cards: {state.total_non_commander_cards()}
            """).strip(),
        expected_output='Return JSON like {"summary": "...", "validation_notes": ["..."]}.',
    )
