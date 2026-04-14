# Commander Deckbuilder Skeleton Summary

## Changelog

### 2026-04-12
- Implemented the first real A5 lands phase.
- Added `A5TurnResult` and wired A5 through the shared OpenAI runner.
- Replaced the A5 stub with a two-step live flow:
  - A5 first recommends utility lands and proposes a total land count
  - A5 then builds the final mana base from plain-code-generated land pools
- Added plain-code land helpers for utility, dual, tri-land / triome, and fetch-land candidate gathering.
- Added plain-code mana-value, color-pip, and basic-land distribution helpers for A5.
- Added A5 hard-rule enforcement for:
  - minimum 37 lands
  - minimum 1 basic of each color
  - utility-land caps by color count
  - `Command Tower` for 2+ color decks
  - `Path of Ancestry` for `low` / `medium` 2+ color decks
  - triome cap of 4 for 5-color decks
- Added the post-A5 branch so the user can skip A6 and export immediately.
- Added final landbase printing after A5 completes.
- Added a direct A5 testing mode at workflow startup so lands can be tested without running A1-A4 first.
- Changed A5 intake prompting so it can recommend a broader utility-land shortlist; the utility cap only applies to what the user finally adds.
- Updated direct A5 testing mode so it can also take a commander and use real commander card context.
- Moved tapped-land judgment back into A5 prompt reasoning instead of filtering those lands out in plain code.
- Changed the no-deck A5 average-mana-value default to `3.0` so direct A5 testing does not get distorted by commander-only context.
- Added an explicit dual-land priority block directly into the A5 prompt and told A5 to use higher-priority land cycles before lower-priority ones while there is room.
- Implemented the first real A6 completion phase.
- Added `A6TurnResult` and wired A6 through the shared OpenAI runner.
- Replaced the A6 stub with a single-shot batch completion flow:
  - plain code computes target fill counts by category
  - plain code builds compact candidate pools from A3/A4 search plans and history
  - A6 recommends a grouped completion batch
  - the user can remove individual cards before they are added
- Expanded A6 so it also has a cut mode for overfull decks:
  - plain code computes target cut counts by category
  - A6 recommends grouped cuts from the current deck
  - the user can keep individual suggested cuts before removal
- Fixed deck-state storage so repeated basic lands from A5 are preserved correctly.
- Updated project-wide card pricing so displayed prices and budget checks use the lowest available paper USD price.
- Updated A1 random commander selection to prefer semi-popular EDHREC-ranked commanders before wider random fallback.
- Updated A6 so it does not add or cut lands.
- Added automatic `decklist.txt` snapshot export at the end of A6.
- Changed A4 synergy handling so the `synergy` category now runs one recommendation round per declared A2 theme instead of one combined synergy batch.
- Extended A3 so it also prepares separate synergy search plans per declared A2 theme.
- Added `docs/ui_implementation_plan.md` to capture the agreed local UI direction.
- Locked in the first UI direction as a local Streamlit app backed by a UI session controller instead of trying to bolt a web UI directly onto the CLI workflow.
- Recorded the first UI implementation order:
  - add Scryfall image helpers
  - add UI event dataclasses
  - add a UI session controller
  - scaffold `ui_app.py`
  - implement A1 in the UI first, then A4, A5, and A6

### 2026-04-07
- Updated the workflow design to split the old A3 into two agents:
  - A3 silent tag preparation after A2
  - A4 user-facing per-category search and recommendation
- Updated the design docs so lands/completion/export shift to A5/A6/A7.
- Updated A3 design so it remains fully silent and outputs both:
  - `otag:` selections
  - search intents
  - full candidate Scryfall queries
- Added Scryfall API guidance to the docs: keep traffic under 10 requests per second.
- Implemented the first live A3 pass in code so it silently prepares category tags after A2.
- Upgraded A3 in code from tags-only output to a hybrid per-category search plan:
  - tags
  - search intents
  - candidate Scryfall queries
- Updated the category search loop to consume both A3-generated candidate queries and tag-derived queries.
- Added plain-code normalization for A3 candidate queries so commander legality, paper legality, CID limits, and budget filters are enforced consistently.
- Added a simple request throttle in the Scryfall wrapper to stay under the 10-requests-per-second guideline.
- Added live validation for A3 candidate queries so invalid or zero-result searches are dropped before they are accepted into workflow state.
- Defined the intended first-pass A4 behavior more clearly:
  - A4 should begin with an EDHREC-informed recommendation step before category-by-category search begins once that data path exists
  - single-shot per category
  - no user-driven requery loop yet
  - plain code trims and dedupes search results before the model sees them
  - A4 recommends a dynamic number of cards based on the candidate pool size
  - A4 gives only brief recommendation summaries
  - future EDHREC support should consider `High Synergy Cards` and `Top Cards`, but that data path is deferred until separate extraction code is available
- Implemented the first real A4 Scryfall-backed per-category pass in code.
- A4 now receives a compact candidate pool from plain code instead of raw full search dumps.
- Plain code now trims per-query results, dedupes across queries, and removes cards already in the deck before calling A4.
- A4 now returns:
  - `assistant_message`
  - `recommended_card_names`
  - `brief_recommendation_notes`
- A4 notes are intentionally constrained to one very brief note per recommended card.
- Changed card entry after recommendations from comma-separated input to one-card-per-line input so names with commas work correctly.
- Increased A4 candidate-pool sizing and recommendation counts, with extra room for `synergy`, so the user sees more options per category.
- Hardened A1 confirmation flow so a direct affirmative reply can finalize a pending commander in plain code instead of bouncing through repeated verification turns.
- Made `synergy` a core category that is automatically included once the user has real synergy themes, so A3 and A4 do not skip the deck's theme cards.
- Tightened the A3 prompt so declared synergy themes are required search drivers and must be covered across the generated plans.
- Updated live Scryfall search requests to ask the API for `order=edhrec` directly, and confirmed that the API accepts it and returns EDHREC-ranked results.
- Integrated `tools/edhrec_scraper.py` into the workflow and implemented the A4 EDHREC opening recommendation pass before category-by-category search.
- EDHREC opening recommendations now use the commander's `High Synergy Cards` and `Top Cards` sections, then let the user add cards before the normal category loop begins.
- EDHREC opening recommendations are now enriched with Scryfall price data and filtered by budget before they are passed to A4, so expensive off-budget cards do not appear in that opening batch.

### 2026-04-10
- Cleaned up stale A3/A4 summary sections so the document matches the current implementation state.
- Recorded the planned A5 landbase behavior in the docs:
  - A5 confirms utility lands and total land count with the user
  - plain code gathers utility, dual, and tri-land candidate pools
  - A5 builds the rest of the mana base itself
  - every 2+ color deck should include `Command Tower`
  - `Path of Ancestry` should be included for `low` and `medium` budget 2+ color decks
  - land count should not go below 37
  - land count can increase for high-average-mana-value, big-mana, or lands-focused decks
  - after A5, the user should be allowed to skip A6 before export

### 2026-04-03
- Added a real model-backed A1 intake phase.
- Added a real model-backed A2 strategy-planning phase.
- Added `commander_deckbuilder/llm.py` as the shared OpenAI runner for workflow agents.
- Implemented commander validation against Scryfall.
- Added A1 commander lookup support using Scryfall search for partial names like `frodo` or `lotho`.
- Added A1 random commander support with a Scryfall-backed random pool and fallback to A1's own commander knowledge when Scryfall is too slow.
- Added protection against A1 crashing when the model replies in plain text instead of JSON.
- Improved A1 JSON parsing so mixed prose plus JSON responses are handled more robustly.
- Refined A1 prompting so it opens more directly and prefers treating full-looking commander names as commander candidates instead of partial-name searches.
- Changed A1 completion so it only finalizes when `candidate_commander` is present and `done == true`.
- Added A2 completion so it only finalizes when synergy themes, budget tier, and category queue are all present and `done == true`.
- Refined A2 prompting so it reads commander card text before suggesting themes and provides theme lists immediately instead of teaser messages.
- Integrated token and cost tracking through `model_usage.py`.
- Added aggregated per-agent usage summaries and end-of-flow usage reporting.
- Updated `one_prompt_one_model.py` to read prompt files as UTF-8 on Windows.

## Current State

This project is a runnable CLI skeleton with real model-backed A1, A2, silent A3, live A4 recommendation phases, a real first-pass A5 lands phase, and a real first-pass A6 completion phase.

Current status:
- A1 is implemented with real OpenAI API calls.
- A2 is implemented with real OpenAI API calls.
- A3 is implemented as a silent model-backed planning step after A2.
- A4 is implemented for both the EDHREC opening recommendation pass and the per-category Scryfall recommendation pass.
- A5 is implemented as a two-step model-backed lands phase.
- A6 is implemented as a single-shot model-backed completion phase.
- A6 now supports both add mode and cut mode.
- A5 can also be run directly in a lands-only testing mode.
- A1 loops in conversation until the user clearly settles on a commander.
- A2 loops in conversation until strategy information is complete enough to finalize.
- A3 runs silently after A2 and prepares category-specific search plans.
- A5 runs after A4 when the user chooses full completion.
- A5 can also be entered directly from the CLI start menu by providing CID, budget, and themes.
- A6 runs after A5 when the user chooses completion instead of export.
- Direct A5 mode can also take a commander name first and use that card's CID and oracle text as context.
- A1 validates commander candidates against Scryfall before accepting them.
- A1 can search Scryfall for commander candidates when the user only knows part of a name.
- A1 can pick from a random commander pool, with a fallback to its own knowledge if Scryfall random lookup is too slow.
- A1 random commander selection now prefers semi-popular EDHREC-ranked commanders before falling back to wider random picks.
- The design target for downstream search is now:
  - A3 silent tag preparation
  - A4 visible category search and recommendation
  - A5 lands
  - A6 completion
  - A7 export
- A3 is explicitly intended to remain silent. The user should not have to answer A3-specific questions.
- The current code now includes a real silent A3 pass that prepares:
  - tags
  - search intents
  - candidate queries
- For `synergy`, A3 now also prepares theme-specific subplans keyed to each declared synergy theme.
- The visible A4 phase is no longer placeholder-only. It now consumes the fuller A3 plan and produces real model-backed recommendations.
- The A4 EDHREC-first opening pass is now implemented.
- For the `synergy` category, A4 now runs once per declared synergy theme.
- The A5 lands phase is no longer placeholder-only. It now uses both model output and plain-code land search/build logic.
- The A6 completion phase is no longer placeholder-only. It now uses model output plus plain-code category allocation and candidate-pool building.
- A6 can now either fill remaining slots or recommend cuts if the deck is over 99 non-commander cards.
- A6 now excludes lands entirely, so only A5 manages the mana base.
- Usage and cost tracking are integrated for model-backed agent calls.
- The agreed next product layer is a local Streamlit UI with clickable card images for recommendations.
- The UI implementation spec now lives in `docs/ui_implementation_plan.md`.

## Files

`main.py`
- Entry point for the workflow.
- Starts the Commander deck-building CLI.

`one_prompt_one_model.py`
- Standalone test script for one prompt and one model call.
- Reads prompt files as UTF-8 so it does not crash on Windows encoding issues.

`model_usage.py`
- Stores pricing and token-cost helpers for supported models.
- Provides:
  - `print_usage()`
  - `summarize_usage()`
  - `format_usage_markdown()`
- Used by the shared agent runner so model-backed agent calls can record token and cost data.

`commander_deckbuilder/__init__.py`
- Makes the package importable.
- Exposes the main workflow class.

`commander_deckbuilder/constants.py`
- Stores shared configuration.
- Defines:
  - standard deck categories
  - budget tier labels
  - budget price filters
  - color ordering

`commander_deckbuilder/models.py`
- Defines the core dataclasses for the workflow.
- Main structures:
  - `DeckCard`
  - `AgentPrompt`
  - `A1TurnResult`
  - `A2TurnResult`
  - `A3CategoryPlan`
  - `A3TagPrepResult`
  - `A4TurnResult`
  - `A5TurnResult`
  - `A6TurnResult`
  - `AgentUsageReport`
  - `SearchPlan`
  - `DeckState`
- `A1TurnResult` includes:
  - `candidate_commander`
  - `commander_search_query`
  - `random_commander_request`
  - `done`
- `DeckState` now includes `category_tags` as a mapping from category to hybrid A3 plan output.

`commander_deckbuilder/agents.py`
- Contains prompt builders for the workflow agents.
- A1 prompt supports:
  - conversation history
  - validation feedback from plain code
  - commander search feedback from plain code
  - structured JSON output
  - a stricter completion rule using `done`
  - explicit commander search requests for partial names
  - explicit random commander requests
  - fallback behavior when random Scryfall lookup is unavailable or too slow
  - a more direct opener
  - preference for treating full commander names as direct candidates
- A2 prompt supports:
  - conversation history
  - validation feedback from plain code
  - structured JSON output
  - a `done` gate
  - collecting synergy themes, budget tier, and category queue
  - using commander card text when suggesting themes
  - providing theme options in the same message instead of announcing them first
- A3 prompt is now a silent planner that returns:
  - selected tags
  - search intents
  - full candidate Scryfall queries
- A3 now also supports `synergy_theme_plans` for theme-specific synergy search planning.
- A5 prompts now support:
  - an intake pass for utility-land recommendations and proposed total land count
  - a final-pass landbase build using plain-code-generated land candidate pools
  - reference guidance from `docs/a5_landbase_examples.md`
- A6 prompt now supports:
  - target fill counts by category
  - compact candidate pools by category
  - grouped recommendation output with brief notes
  - target cut counts by category
  - current deck summaries by category for cut mode

`commander_deckbuilder/llm.py`
- Shared OpenAI runner for workflow agents.
- Handles:
  - model calls through the Responses API
  - JSON parsing
  - A1-, A2-, A3-, A4-, A5-, and A6-specific handling
  - fallback when A1 or A2 returns plain text instead of JSON
  - robust extraction of the final JSON object when a model mixes prose with JSON
  - usage and cost tracking for every model-backed call
- Stores usage history in a structure that can later support a hidden UI panel or button.

`commander_deckbuilder/scryfall.py`
- Wraps Scryfall helper behavior.
- Supports:
  - exact card lookup
  - partial commander search using `is:commander <query>`
  - random commander pool generation
  - semi-popular random commander preference using EDHREC rank
  - loading the tag list from `tools/scryfall_tags.json`
  - color identity extraction
  - color identity legality checks
  - one-query-per-tag generation
  - normalization of A3-generated candidate queries
  - live validation of A3-generated candidate queries against Scryfall
  - commander validation
  - lowest-available-price extraction for paper USD pricing
- Scryfall-facing behavior now includes a simple throttle to stay under the under-10-requests-per-second guideline.

`commander_deckbuilder/workflow.py`
- Main orchestration layer for the CLI workflow.
- Current code behavior:
  - A1 is model-backed and conversational
  - A2 is model-backed and conversational
  - A3 is model-backed and silent
  - A4 is model-backed and single-shot in two places:
    - one EDHREC opening recommendation pass before category search
    - one per-category Scryfall recommendation pass
  - A5 is model-backed in two steps:
    - one utility-land / target-count intake pass
    - one final mana-base construction pass
  - A6 is model-backed as a single-shot grouped completion pass
  - A3 currently prepares a hybrid per-category plan and stores it in shared state
  - A3 now also prepares theme-specific synergy plans when the `synergy` category is present
  - A3 candidate queries are normalized and validated before they are stored in state
  - plain code also builds a compact EDHREC candidate pool, enriches it with Scryfall data, and filters it by CID and budget before A4 sees it
  - plain code trims and dedupes live Scryfall results into a compact candidate pool for A4
  - A4 ranks that compact pool and returns exact card-name recommendations with very brief notes
  - plain code now generates A5 land pools for:
    - utility lands
    - pairwise dual lands
    - tri-lands / triomes
    - on-color fetches for `high` / `none`
  - plain code now estimates mana value and color-pip demand to support A5 land construction
  - A5 now writes the final land package directly into `decklist["lands"]` and prints the landbase
  - plain code now computes A6 target fill counts by category and builds compact candidate pools from prior search plans/results
  - plain code now computes A6 target cut counts when the deck is overfull
  - A6 now returns grouped recommendations or grouped cuts by category and plain code lets the user review them before applying changes
  - A6 now excludes lands entirely and writes a `decklist.txt` snapshot after completion runs
  - A1 can trigger a commander search tool path for partial names
  - A1 can trigger a random commander tool path
  - A1 random commander tool flow now prefers semi-popular commanders before using wider random fallback
  - card additions are still manual outside of A5, which adds lands directly
  - export and validation are still basic
- Design target behavior:
  - A3 silent tag prep after A2
  - A3 outputs tags, search intents, and full candidate queries per category
  - A4 EDHREC opening recommendations
  - A4 per-category search/recommendation using A3 output
  - A5 lands
  - A6 batch completion
  - A7 export
- A1 only finalizes when:
  - `candidate_commander` is present
  - `done == true`
- A2 only finalizes when:
  - `done == true`
  - plain code confirms that synergy themes, budget tier, and category queue are all valid
- A3 is silent and should remain a planning agent, not a conversational one.

`docs/ui_implementation_plan.md`
- Implementation plan for the upcoming local UI.
- Defines:
  - the Streamlit-first direction
  - the new UI session-controller layer
  - the event schema for chat, prompts, recommendation batches, and deck updates
  - the reusable UI card shape
  - the phased UI implementation order

`tools/__init__.py`
- Makes the `tools` folder importable as a package.

`tools/scryfall_query_search.py`
- Older standalone Scryfall search helper from earlier skeleton work.
- The current workflow no longer depends on it directly; live Scryfall search now runs through `commander_deckbuilder/scryfall.py`.

`tools/scryfall_tags.json`
- Existing curated list of Scryfall gameplay tags.
- Intended to be read semantically by silent A3.

`tools/edhrec_scraper.py`
- Fetches commander-page EDHREC data.
- Returns structured `high_synergy_cards` and `top_cards` data for a commander.

`commander_deckbuilder/edhrec.py`
- Thin wrapper around the EDHREC scraper for use in workflow code.

## What Works Right Now

- The CLI runs from `python main.py`.
- A1 performs real model calls.
- A2 performs real model calls.
- A3 performs a real silent model call.
- A4 performs a real EDHREC opening recommendation call.
- A4 performs a real per-category model call.
- A5 performs real model calls.
- A6 performs real model calls.
- A1 can converse across multiple turns.
- A2 can converse across multiple turns.
- A1 can survive non-JSON model replies without crashing.
- A2 can survive non-JSON model replies without crashing.
- A1 verifies commander candidates through Scryfall.
- A1 can search for commander candidates from partial names like `frodo` or `lotho`.
- A1 can present Scryfall commander options and wait for the user to choose.
- A1 can generate a random commander suggestion flow.
- A1 random suggestion flow now biases toward semi-popular commanders rather than total jank.
- A1 is better at handling exact commander names directly instead of looking them up unnecessarily.
- A1 only closes after explicit model completion via the `done` flag and successful Scryfall validation.
- A2 only closes after explicit model completion via the `done` flag and successful plain-code validation.
- `synergy` is automatically inserted into the confirmed category queue if the user has real synergy themes.
- A3 writes prepared category search plans into shared state.
- A3 currently prepares tags, search intents, and candidate queries for the category loop.
- A3 now also prepares per-theme synergy search plans when the `synergy` category is present.
- A3-generated candidate queries are normalized and validated against live Scryfall before they are stored in state.
- The EDHREC opening pool is enriched with live Scryfall data and filtered by budget before A4 sees it.
- The category loop deduplicates those validated candidate queries with tag-derived queries before running them.
- The category loop now trims per-query results, dedupes the candidate pool, and sends that reduced pool to A4.
- A4 returns a dynamic-sized recommendation set based on the compact candidate pool size.
- A5 recommends utility lands, proposes a target land count, and constructs a final mana base.
- A5 can be launched directly for lands-only testing by entering CID, budget, and themes.
- In direct A5 mode, the user can also provide a commander for better landbase context.
- A5 enforces utility caps, minimum basics, and multi-color auto-includes before adding lands.
- A5 now persists the full basic-land package into deck state correctly.
- A5 prints the final landbase and the user can skip A6 afterward.
- A6 recommends a grouped completion batch and supports remove-before-add review.
- A6 can also recommend cuts and supports keep-before-remove review for overfull decks.
- A6 does not add or cut lands.
- A6 writes a `decklist.txt` snapshot at the end of the phase.
- Card additions now use one-card-per-line entry instead of comma splitting.
- Confirmed commanders are written into workflow state with color identity.
- Confirmed strategy outputs are written into workflow state:
  - `synergy_themes`
  - `budget_tier`
  - `category_queue`
- LLM usage and estimated cost are tracked for model-backed agent calls.

## Current Usage Reporting

Usage tracking is implemented in a way that should map well to a future UI.

Current behavior:
- raw per-turn usage is not printed after every model response
- when A1 finishes, the workflow prints one aggregated A1 usage summary
- when A2 finishes, the workflow prints one aggregated A2 usage summary
- when A3 finishes, the workflow prints one aggregated A3 usage summary
- when A5 finishes, the workflow prints one aggregated A5 usage summary
- at the end of the flow, the workflow prints a total usage summary
- the user can optionally ask to see detailed usage by individual agent call

Tracked data includes:
- call count
- model
- input tokens
- cached tokens
- output tokens
- reasoning tokens
- estimated USD cost

Pricing behavior:
- card prices shown in the workflow now use the lowest available paper USD price for that card
- budget checks use that same lowest-price rule

## What Is Still Stubbed

- A7 Export Agent

Those phases are still either design-only or placeholder behavior rather than real model-backed implementations.

## What Still Needs To Be Added

### 1. Real Agent Execution Beyond A6
- Wire A7 to the shared agent runner in `commander_deckbuilder/llm.py`.
- Define a structured JSON output contract for A7.
- Add error handling and retry behavior for malformed outputs.

### 2. Better A1/A2 Hardening
- Possibly require an explicit confirmation field in addition to `done`.
- Add retry logic if A1 or A2 repeatedly fails to follow output format.
- Continue prompt tuning for A1 and A2 now that they are in place.
- Consider whether A1 random commander fallback should use a cached commander pool instead of live Scryfall requests.

### 3. Search-Agent Refactor
- Keep A3 fully silent. The user should not have to interact with it directly.
- Continue refining A3 so its tags and candidate queries cover the declared deck themes as directly as possible.
- Tune A4 recommendation quality for both:
  - the EDHREC opening pass
  - the per-category Scryfall pass
- Improve deduplication and scoring across multiple Scryfall searches where recommendation quality still feels weak.
- Keep Scryfall-friendly request pacing in place and stay under 10 requests per second.

### 4. A4 Implementation Direction
- A4 now begins with an EDHREC-informed recommendation pass before the category-by-category Scryfall loop.
- That EDHREC-first pass recommends cards from commander-page data before the normal category flow starts.
- A4 is currently single-shot per category.
- A4 does not handle a user-driven "new batch" loop yet.
- A3 candidate queries do not need to be revalidated in A4 because they are already validated in the A3 step.
- For the Scryfall category loop, CID and budget are already baked into the validated query strings.
- For the EDHREC opening pass, plain code now re-enforces CID and budget by enriching the EDHREC card names with live Scryfall data before passing them to A4.
- Plain code should still:
  - trim per-query result sets before sending them to A4
  - dedupe cards across queries
  - remove cards already present in the current decklist
- A4 currently receives a compact candidate pool rather than raw full search dumps, to keep token usage under control.
- A4 currently recommends a dynamic number of cards depending on how many usable candidates remain after trimming and deduping.
- A4 currently provides a brief summary of its recommendations rather than a long explanation.
- For `synergy`, A4 now gets a theme-focus field so each round targets one specific declared theme.
- EDHREC commander-page data is already incorporated through:
  - `High Synergy Cards`
  - `Top Cards`
- Future A4 work can expand how EDHREC data is weighted, filtered, and presented.

### 5. A5/A6 and Workflow Completion
- Tune A5 recommendation quality and landbase composition against real transcripts.
- Harden any A5 edge cases found in testing.
- Tune A6 category allocation and completion-batch quality against real transcripts.
- Consider whether A1 random commander popularity filtering should become a named constant or user-tunable setting.
- Use A7 output for polished export summaries and validation notes.

### 6. Validation
- Improve Commander legality checks beyond the current commander validation.
- Add stronger full-deck validation for:
  - total card count
  - duplicates
  - color identity
  - commander-specific constraints

### 7. Persistence and UI
- Save and load workflow state if resumability is desired.
- Implement the local Streamlit UI path described in `docs/ui_implementation_plan.md`.
- Add Scryfall image extraction helpers so recommendation batches can render real card images.
- Add UI event dataclasses and a UI session controller so the workflow can drive the UI without `print()` / `input()`.
- Reuse one clickable card-grid component for:
  - A1 commander choices
  - A4 recommendations
  - A5 utility lands
  - A6 additions and cuts

## Recommended Next Steps

The cleanest next steps are:
- add `get_card_image_url(...)` to `ScryfallService`
- add UI event dataclasses and the UI card view model
- add the UI session controller layer
- scaffold `ui_app.py`
- implement A1 in the UI first
- then implement A4 recommendation batches in the UI
- then wire A5 and A6 into the same clickable card-grid component
- after that, tune A3/A4/A5/A6 quality from real UI transcripts
- implement A7

That keeps the architecture consistent and lets each agent inherit the same usage tracking and error-handling structure.

## Blake notes
- None currently recorded.
