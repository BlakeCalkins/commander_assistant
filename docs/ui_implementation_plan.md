# Commander Deckbuilder UI Plan

## Goal

Build a local UI for the existing Commander deckbuilding workflow with:

- a clean chat interface
- clickable card images for recommendations
- a visible current deck / counts panel
- support for A1, A4, A5, and A6 recommendation interactions

The fastest implementation path is a **local Streamlit app** on top of the current Python backend.

## Why Streamlit

- The project is already Python-first.
- The current workflow, agent runner, and Scryfall helpers are already in Python.
- Streamlit is much faster to ship than React + API for a local tool.
- It supports:
  - chat-like layouts
  - images
  - buttons
  - forms
  - session state
  - sidebars / columns

## Core Architecture

Do **not** try to directly drive the UI from the current CLI workflow.

The current `CommanderDeckWorkflow` is tightly coupled to:

- `print(...)`
- `input(...)`

Instead, add a UI-facing session controller that returns structured UI events.

### Layers

1. Existing services / logic
- `ScryfallService`
- `EDHRECService`
- agent prompt builders
- LLM runner
- `DeckState`

2. New UI session controller
- owns workflow state
- advances the flow one step at a time
- returns structured events instead of printing / reading input

3. Streamlit app
- renders messages and recommendation batches
- collects user input
- calls the session controller

## Initial File Structure

Recommended additions:

- `ui_app.py`
- `commander_deckbuilder/ui_session.py`
- `commander_deckbuilder/ui_events.py`
- `commander_deckbuilder/card_view_models.py`

### Responsibilities

`ui_app.py`
- Streamlit entrypoint
- renders layout
- stores session in `st.session_state`

`commander_deckbuilder/ui_session.py`
- stateful orchestration for the UI flow
- exposes methods like:
  - `start()`
  - `submit_text(user_text)`
  - `select_card(action_id, card_name)`
  - `skip_current_step()`

`commander_deckbuilder/ui_events.py`
- dataclasses for structured UI events

`commander_deckbuilder/card_view_models.py`
- transforms raw Scryfall / EDHREC cards into UI-friendly card objects

## UI Event Schema

The UI should be driven by explicit event objects, not raw prints.

### Base Event Types

1. `ChatMessageEvent`
- shown in the chat log
- fields:
  - `role`: `assistant` | `user` | `system`
  - `agent_id`: optional
  - `text`

2. `PromptEvent`
- asks the user for typed input
- fields:
  - `prompt_id`
  - `kind`: `text` | `number` | `choice`
  - `label`
  - `placeholder`
  - `choices`

3. `RecommendationBatchEvent`
- renders clickable cards
- fields:
  - `batch_id`
  - `agent_id`
  - `title`
  - `category`
  - `theme_focus`
  - `action_mode`: `add` | `pick_one` | `keep_or_cut`
  - `cards`
  - `allow_skip`

4. `DeckStateEvent`
- refreshes sidebar / summary
- fields:
  - `commander`
  - `category_counts`
  - `total_non_commander_cards`
  - `decklist_preview`

5. `PhaseEvent`
- small phase headers / transitions
- fields:
  - `phase_id`
  - `title`

## Card View Model

Every clickable card shown in the UI should use the same shape.

### `UICard`

- `name`
- `image_url`
- `mana_cost`
- `type_line`
- `oracle_text`
- `usd`
- `edhrec_rank`
- `source_label`
- `note`
- `category`

### Image Rules

Use Scryfall image URLs directly.

Preferred extraction order:

1. `card["image_uris"]["normal"]`
2. `card["card_faces"][0]["image_uris"]["normal"]`

Add a helper in `ScryfallService`, for example:

- `get_card_image_url(card: dict | None) -> str | None`

This should be used anywhere cards are prepared for the UI.

## UI Layout

### Main Layout

Two-column layout:

1. Main column
- chat transcript
- current prompt input
- recommendation card grids

2. Right sidebar
- commander
- themes
- budget
- category counts
- current deck size
- recent additions

### Card Display

Each recommendation batch should render cards in a grid:

- card image
- card name
- price
- short note
- action button

Action buttons by phase:

- A1:
  - `Choose Commander`
- A4:
  - `Add to Deck`
- A5 utility lands:
  - `Include`
- A6 add mode:
  - `Add`
- A6 cut mode:
  - `Keep`
  - `Cut`

## Phase-by-Phase UI Behavior

## A1

### Needed UI interactions

- free-text user input
- clickable commander search results
- clickable random commander recommendations
- commander confirmation card

### Event pattern

1. `ChatMessageEvent` from A1
2. if search results exist:
   - `RecommendationBatchEvent(action_mode="pick_one")`
3. user either:
   - types a reply
   - clicks a commander

### Important A1 display cases

- partial-name lookup results
- random commander pool
- final commander confirmation

## A4

### Needed UI interactions

- EDHREC opening recommendations
- per-category recommendations
- per-theme synergy recommendations
- add card clicks

### Event pattern

1. `PhaseEvent(title="EDHREC Opening Recommendations")`
2. `RecommendationBatchEvent(action_mode="add")`
3. repeated category batches

### Important note

Synergy should render one batch per theme.

## A5

### Needed UI interactions

- utility land shortlist as clickable cards
- total land count confirmation input
- final mana base display

### Event pattern

1. A5 assistant message
2. `RecommendationBatchEvent(action_mode="add")` for utility lands
3. `PromptEvent(kind="number")` for target land count
4. final landbase summary grid / grouped list

## A6

### Needed UI interactions

Add mode:

- grouped recommendation batches
- click cards to keep / add

Cut mode:

- grouped cut recommendation batches
- click cards to keep or cut

### Output

- updated deck state
- `decklist.txt` still written at the end

## Session Controller Shape

Suggested public API:

```python
class DeckbuilderUISession:
    def start(self) -> list[UIEvent]: ...
    def submit_text(self, user_text: str) -> list[UIEvent]: ...
    def select_card(self, batch_id: str, card_name: str, action: str) -> list[UIEvent]: ...
    def submit_number(self, prompt_id: str, value: int) -> list[UIEvent]: ...
    def skip(self, prompt_id: str | None = None) -> list[UIEvent]: ...
```

Internally it should track:

- current phase
- pending prompt
- pending recommendation batch
- `DeckState`
- any in-progress agent conversation history

## Fastest Implementation Order

### Milestone 1

Make Streamlit app boot and render:

- chat history
- deck sidebar
- fake recommendation batch from static data

### Milestone 2

Wire A1 only:

- text input
- commander search cards
- random commander cards
- commander confirmation

### Milestone 3

Wire A4:

- EDHREC opening recommendations
- category recommendations
- add-to-deck clicks

### Milestone 4

Wire A5:

- utility land card grid
- total land count input
- final mana-base display

### Milestone 5

Wire A6:

- add mode cards
- cut mode cards
- decklist export notice

## Fastest MVP Decision

For the first UI pass:

- support click-to-add only
- do not implement drag-and-drop
- keep the chat simple
- reuse existing backend logic as much as possible
- leave the CLI workflow intact
- build the UI path beside it, not by replacing it immediately

## Known Refactor Need

The current CLI workflow is not UI-friendly because it mixes:

- orchestration
- I/O
- display formatting

The main UI refactor target is to move user interaction boundaries into the new UI session controller.

That controller should:

- call agent methods
- call service methods
- return event objects

The Streamlit app should only render those objects and send user actions back.

## Recommended First Code Tasks

1. Add `get_card_image_url(...)` to `ScryfallService`
2. Add `UICard` and event dataclasses
3. Create `DeckbuilderUISession`
4. Create `ui_app.py`
5. Implement A1 in UI first

## Local Run Target

Expected local command:

```powershell
streamlit run ui_app.py
```

## Non-Goals For First Pass

- production authentication
- database persistence
- multiplayer collaboration
- polished deck analytics
- hosted deployment
- fancy animations

The first goal is a clean local chat UI with clickable card images that actually drives the working workflow.
