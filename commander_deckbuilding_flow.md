# Commander Deckbuilding AI - Agent Workflow (v4)

## Glossary
- **CID** - Color Identity. Constrains all card searches to legal colors.
- **Agent** - An LLM-powered bot that reasons, plans, or converses.
- **Plain Code** - Deterministic Python logic; no LLM involved.
- **State** - A shared Python dict, held in memory for the session, passed explicitly into each agent call as injected context.

---

## Shared State Object
Created at session start. Every agent receives the relevant fields as injected context and returns updates that plain code writes back in.
```json
{
  "commander": null,
  "cid": [],
  "budget_tier": null,
  "synergy_themes": [],
  "category_queue": [],
  "category_tags": {
    "synergy": {
      "tags": [],
      "search_intents": [],
      "candidate_queries": []
    }
  },
  "decklist": {
    "commander": [],
    "synergy": [],
    "ramp": [],
    "draw": [],
    "removal": [],
    "wipe": [],
    "protection": [],
    "recursion": [],
    "lands": [],
    "other": []
  },
  "card_count": 1
}
```

### Budget Tiers
| Tier     | Label shown to user       | Scryfall price filter (per card) |
|----------|---------------------------|----------------------------------|
| `low`    | Low (~$100 total)         | `usd<=1.00`                      |
| `medium` | Medium (~$100-$500 total) | `usd<=10.00`                     |
| `high`   | High ($500+)              | `usd<=100.00`                    |
| `none`   | No limit                  | *(omit price filter)*            |

> Price checks and displayed prices should use the lowest available paper USD price for a card.

---

## Agent Roster

| ID | Agent Name           | Role                                                                                   |
|----|----------------------|----------------------------------------------------------------------------------------|
| A1 | **Intake Agent**     | Greets user, confirms commander and CID                                                |
| A2 | **Strategy Agent**   | Discusses themes, budget, and which categories the user wants                          |
| A3 | **Tag Prep Agent**   | Silently prepares category tags, search intents, and candidate Scryfall queries        |
| A4 | **Search Agent**     | Runs category searches, filters and scores results, and surfaces cards to the user     |
| A5 | **Lands Agent**      | Discusses and generates a landbase recommendation                                      |
| A6 | **Completion Agent** | Fills remaining deck slots in one batch if user requests                               |
| A7 | **Export Agent**     | Formats and validates the final decklist for export                                    |

---

## Workflow

### Phase 1 - Commander Selection
**Owner: A1 (Intake Agent)**

- Greets the user and opens conversation about what they want to build.
- Asks clarifying questions until a specific commander is confirmed.
- May use plain-code Scryfall lookup/search support when the user only knows part of a commander name.
- If the user wants A1 to pick for them, plain code may build a random commander pool.
- That random pool should prefer semi-popular commanders using EDHREC rank before falling back to wider random legal commanders.
- Plain code resolves the CID from the confirmed commander name and verifies commander exists and is valid.
- **Outputs -> State**: `commander`, `cid`

---

### Phase 2 - Strategy and Category Planning
**Owner: A2 (Strategy Agent)**

- **Receives from State**: `commander`, `cid`
- Discusses synergy themes and win conditions with the user.
- Produces a short list of `synergy_themes`.
- Asks the user about budget and maps their answer to a `budget_tier`.
- Presents the standard category list and asks the user which ones they want to include.
- Builds the `category_queue` as an ordered list of only the categories the user confirmed.
- **Outputs -> State**: `synergy_themes`, `budget_tier`, `category_queue`

> Example `category_queue`: `["synergy", "ramp", "draw", "removal", "wipe"]`

---

### Phase 3 - Silent Tag Preparation
**Owner: A3 (Tag Prep Agent)**

- **Receives from State**: `commander`, `cid`, `budget_tier`, `synergy_themes`, `category_queue`
- Runs silently after A2 completes. The user does not interact with this agent directly.
- Reads the commander, the strategy themes, and the selected categories.
- Searches the `scryfall_tags.json` resource semantically to find the most relevant oracle tags for each category in `category_queue`.
- Also prepares full candidate Scryfall queries for each category when tags alone are not sufficient.
- This is important for concepts that may not map cleanly to a single `otag:`, such as ETB creatures, death-trigger creatures, or other rules-text-driven searches.
- Prepares a mapping from category to:
  - candidate tag list
  - search intents
  - candidate queries
- If the `synergy` category is present, also prepares one separate synergy search plan per declared synergy theme so later A4 rounds are not forced to reuse one combined synergy query set.
- Plain code writes that mapping into state.
- **Outputs -> State**: `category_tags`

> Example `category_tags`:
```json
{
  "synergy": {
    "tags": ["repeatable-treasures", "artifact", "sacrifice-outlet-creature"],
    "search_intents": [
      "treasure payoffs",
      "artifact sacrifice value"
    ],
    "candidate_queries": [
      "game:paper legal:commander id<=wb otag:repeatable-treasures",
      "game:paper legal:commander id<=wb t:creature o:\"create a Treasure token\"",
      "game:paper legal:commander id<=wb o:\"enters the battlefield\" t:creature"
    ]
  },
  "draw": {
    "tags": ["draw-engine", "burst-draw"],
    "search_intents": [
      "repeatable draw",
      "artifact-based card advantage"
    ],
    "candidate_queries": [
      "game:paper legal:commander id<=wb otag:draw-engine",
      "game:paper legal:commander id<=wb o:\"draw a card\""
    ]
  }
}
```

#### A3 Output Contract
Plain code should expect A3 to return strict JSON in the shape:
```json
{
  "category_plans": {
    "synergy": {
      "tags": ["tag-1", "tag-2"],
      "search_intents": ["intent-1", "intent-2"],
      "candidate_queries": ["query-1", "query-2", "query-3"]
    },
    "draw": {
      "tags": ["tag-3", "tag-4"],
      "search_intents": ["intent-3"],
      "candidate_queries": ["query-4", "query-5"]
    }
  }
}
```

Validation expectations for plain code:
- A3 remains a **silent agent**. The user should not be asked follow-up questions by A3.
- Each category in `category_queue` should receive:
  - 2-5 tags when useful
  - 1-3 search intents
  - 2-5 candidate queries
- Candidate queries should be valid Scryfall syntax whenever possible.
- Plain code should normalize and validate queries before using them live.
- Plain code may add shared constraints like `game:paper`, `legal:commander`, CID limits, and budget filters if A3 omitted them.
- Queries that are invalid or return no live results should be dropped before they are written into state.

---

### Phase 4 - Card Discovery Loop
*Iterate through each category in `state["category_queue"]`.*
*One full pass of steps 4a-4b runs per category.*

#### Step 4a - Query Generation and Card Filtering
**Owner: A4 (Search Agent)**

- **Receives from State**: current category, `commander`, `cid`,
  `synergy_themes`, `budget_tier`, current `decklist`, `category_tags`
- Reads the prepared plan from `state["category_tags"][category]`.
- Uses both:
  - prepared `otag:` tags
  - prepared full candidate Scryfall queries
- Plain code normalizes, validates, and deduplicates the prepared queries before use.
- If a query is invalid or too poor, plain code may drop it or run one repair pass.
- Plain code executes the queries against the Scryfall API and returns raw results to A4.
- A4 scores results for synergy fit, avoids cards already in `decklist`, and selects the top 8-12 cards to surface.
- If the current category is `synergy`, plain code should run one A4 recommendation round per declared synergy theme so each theme gets its own focused recommendation batch.
- For those synergy rounds, A4 should consume the matching A3 theme-specific synergy plan rather than reusing one shared synergy plan across all themes.
- **Outputs**: ordered list of recommended cards for this category.

#### Step 4b - Display and User Selection
**Owner: Plain Code + UI**

- Renders card images and names for the recommended list.
- User can:
  - Click to add any card to the decklist.
  - Type a card name manually to add it directly.
  - Request a new batch of suggestions for this category.
  - Confirm they are done with this category and move on.
- Plain code writes accepted cards into `decklist[category]`, increments `card_count`.
- Plain code enforces CID legality on every card added.

*Loop repeats for the next category in `category_queue`.*

---

### Phase 4 Exit - Choose Next Step
**Owner: Plain Code + UI**

After the category loop completes, present the user with two options:

> **Option A - Full Completion**
> Continue to landbase generation, then auto-fill remaining slots to reach 99 cards.
>
> **Option B - Export Now**
> Export the current working decklist as-is.

Plain code routes to Phase 5 (Option A) or Phase 7 (Option B).

---

### Phase 5 - Lands *(Option A only)*
**Owner: A5 (Lands Agent)**

- **Receives from State**: full `decklist`, `cid`, `budget_tier`, `card_count`
- First recommends a short list of utility lands from a plain-code-generated utility-land pool.
- Talks with the user only about:
  - which utility lands to keep
  - the proposed target total land count
- Plain code gathers:
  - utility-land candidates from a query like `otag:utility-land id<=CID usd<=budget`
  - dual-land candidates from plain-code-generated color-pair queries like `t:land id=<pair> ...`
  - tri-land or triome candidates from plain-code-generated 3+ color queries
  - on-color fetch-land candidates for `high` and `none`
  - color pip information from the current decklist
  - average mana value from the current decklist
- A5 recommends a land package built from:
  - user-approved utility lands
  - dual lands / tri-lands / triomes chosen by the agent from the gathered candidate pools
  - fetches when allowed by budget
  - basic lands with ratios informed by color pip data
- Utility-land caps should be enforced by color count:
  - 1 color: 7
  - 2 colors: 5
  - 3 colors: 3
  - 4 or 5 colors: 2
- Every 2+ color deck should include `Command Tower`.
- If budget is `low` or `medium`, every 2+ color deck should also include `Path of Ancestry`.
- Fetch lands should only be considered for `high` and `none` budgets, and only on-color fetches should be included.
- For 3+ color decks:
  - run an extra tri-land style query
  - if budget is `low` or `medium`, use `is:triland id<=CID usd<=budget`
  - otherwise use `is:triome id<=CID usd<=budget`
  - if the deck is 4 colors or less, include all 3-color lands in CID
  - if the deck is 5 colors, cap triomes at 4
- If the commander is single-color, skip the dual-land step.
- Total land count should not go below 37.
- Land count should go up by 1-2 if average mana value is above 3.5.
- If themes indicate land-focus or strong big-mana plans, A5 may push the total up to roughly 40-42 lands.
- The final mana base should keep at least 1 basic land of each deck color.
- Basic land count should generally:
  - be highest for mono-color decks
  - sit around 15-20 for many two-color decks depending on utility-land count
  - usually top out around 10 or less for three-color decks
- Plain code adds the A5-approved land package directly to `decklist["lands"]`, updates `card_count`, and prints the final landbase.
- **Outputs -> State**: updated `decklist`, `card_count`

---

### Phase 5 Exit - Choose Next Step
**Owner: Plain Code + UI**

After A5 completes, present the user with two options:

> **Option A - Continue to Completion**
> Run A6 to fill the remaining nonland slots.
>
> **Option B - Skip Completion**
> Skip A6 and export the deck after the current landbase is added.

Plain code routes to Phase 6 (Option A) or Phase 7 (Option B).

---

### Phase 6 - Batch Completion *(Option A only)*
**Owner: A6 (Completion Agent)**

- **Receives from State**: full `decklist`, `synergy_themes`, `budget_tier`, `card_count`
- Determines whether the deck is:
  - under 99 non-commander cards and needs additions
  - over 99 non-commander cards and needs cuts
- In add mode:
  - plain code determines target fill counts by category
  - plain code builds compact candidate pools by category
  - A6 generates a complete grouped list of fill cards
  - plain code displays the batch grouped by category
  - user can remove individual suggested additions before they are added
  - plain code adds the confirmed cards to `decklist`, updates `card_count`
- In cut mode:
  - plain code determines target cut counts by category
  - plain code summarizes the current deck by category
  - A6 generates a grouped list of suggested cuts
  - plain code displays the cut list grouped by category
  - user can keep individual suggested cuts before removal
  - plain code removes the confirmed cuts from `decklist`, updates `card_count`
- A6 should not add or cut lands; the mana base is owned by A5.
- After A6 completes, plain code should write a convenient decklist snapshot file for copying/testing.
- **Outputs -> State**: updated `decklist`, `card_count`

---

### Phase 7 - Export
**Owner: A7 (Export Agent)**

- Produces a short deck summary.
- Plain code formats the complete decklist as plain text.
- Plain code runs a final validation:
  - Total count is exactly 99 + 1 commander (if Option A was taken).
  - All cards are within CID.
- Output is displayed in a copyable text box ready for external deckbuilding tools.

---

## Scryfall API Guardrails
- Keep API traffic under 10 requests per second.
- Enforce a small delay between live Scryfall requests in plain code so the workflow stays under that limit.
- Prefer validating and deduplicating A3-generated queries before sending them live, to avoid redundant or junk traffic.
- If the workflow grows into large-scale repeated lookups, bulk-data or cached approaches should be considered instead of constant live requests.

---

## UI Direction
- The agreed first UI should be a **local Streamlit app** rather than a separate frontend/backend web stack.
- The UI should not drive the current CLI workflow directly because the CLI is tightly coupled to `print(...)` and `input(...)`.
- Instead, add a UI-facing session controller that:
  - owns `DeckState`
  - advances the workflow one step at a time
  - returns structured events for the UI to render
- The detailed UI build spec now lives in `docs/ui_implementation_plan.md`.

### UI Requirements
- Render a clean chat-style interface for agent/user interaction.
- Display real card images for recommended cards using Scryfall image URLs.
- Let the user click cards to act on them whenever a recommendation batch is shown.
- The same clickable card-grid pattern should be reused for:
  - A1 commander search / random commander choices / commander confirmation
  - A4 EDHREC opening recommendations
  - A4 category recommendations
  - A5 utility-land recommendations
  - A6 additions and cut suggestions

### Immediate UI Build Order
1. Add a Scryfall helper to extract card image URLs.
2. Add UI event dataclasses for:
   - chat messages
   - prompts
   - recommendation batches
   - deck-state refreshes
3. Add a UI session controller layer.
4. Scaffold `ui_app.py`.
5. Implement A1 in the UI first.
6. Then implement A4, then A5, then A6.

---

## Open Decisions (Deferred to Development)
- Exact Scryfall API endpoints and query syntax.
- Exact price cap per card for each `budget_tier`.
- Whether A4 gets one re-query attempt on poor results, or the user manually triggers a new batch.
- Exact visual styling of the Streamlit UI once the first local version exists.
- Whether session state is stored in memory only, or persisted to disk/session file for resumability.
- How plain code should repair or discard invalid A3-generated Scryfall queries.
