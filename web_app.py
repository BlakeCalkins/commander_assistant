"""Local Flask UI for the Commander deckbuilder."""

from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from uuid import uuid4

from flask import Flask, redirect, render_template, request, session, url_for

from commander_deckbuilder.ui_events import (
    ChatMessageEvent,
    DeckStateEvent,
    PhaseEvent,
    PromptEvent,
    RecommendationBatchEvent,
)
from commander_deckbuilder.ui_session import DeckbuilderUISession


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "commander-deckbuilder-local-dev")

_SESSIONS: dict[str, DeckbuilderUISession] = {}
_EVENT_LOGS: dict[str, list] = {}


def _get_session_id() -> str:
    sid = session.get("deckbuilder_ui_sid")
    if not sid:
        sid = str(uuid4())
        session["deckbuilder_ui_sid"] = sid
    return sid


def _get_ui_session() -> DeckbuilderUISession:
    sid = _get_session_id()
    ui_session = _SESSIONS.get(sid)
    if ui_session is None:
        ui_session = DeckbuilderUISession()
        _SESSIONS[sid] = ui_session
        _EVENT_LOGS[sid] = list(ui_session.start())
    return ui_session


def _get_event_log() -> list:
    sid = _get_session_id()
    if sid not in _EVENT_LOGS:
        _EVENT_LOGS[sid] = []
    return _EVENT_LOGS[sid]


def _set_notice(text: str | None) -> None:
    session["deckbuilder_ui_notice"] = text or ""


def _get_notice() -> str:
    return str(session.get("deckbuilder_ui_notice", "") or "")


def _append_events(events: list | None) -> None:
    if not events:
        return
    _get_event_log().extend(events)


def _serialize(value):
    if is_dataclass(value):
        return {key: _serialize(val) for key, val in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(val) for key, val in value.items()}
    return value


def _serialize_event(event) -> dict:
    if isinstance(event, ChatMessageEvent):
        return {
            "kind": "chat",
            "role": event.role,
            "text": event.text,
            "agent_id": event.agent_id,
        }
    if isinstance(event, PhaseEvent):
        return {
            "kind": "phase",
            "phase_id": event.phase_id,
            "title": event.title,
        }
    if isinstance(event, RecommendationBatchEvent):
        return {
            "kind": "batch",
            "batch_id": event.batch_id,
            "agent_id": event.agent_id,
            "title": event.title,
            "category": event.category,
            "theme_focus": event.theme_focus,
            "action_mode": event.action_mode,
            "allow_skip": event.allow_skip,
            "cards": _serialize(event.cards),
        }
    if isinstance(event, PromptEvent):
        return {
            "kind": "prompt",
            "prompt_id": event.prompt_id,
            "label": event.label,
            "placeholder": event.placeholder,
            "prompt_kind": event.kind,
            "choices": list(event.choices),
        }
    if isinstance(event, DeckStateEvent):
        return {
            "kind": "deck_state",
            "commander": event.commander,
            "category_counts": dict(event.category_counts),
            "total_non_commander_cards": event.total_non_commander_cards,
            "decklist_preview": list(event.decklist_preview),
        }
    return {"kind": "unknown", "value": repr(event)}


def _current_batch_for_render(ui_session: DeckbuilderUISession) -> dict | None:
    batch_state = ui_session.active_batch
    if not batch_state:
        return None
    title = batch_state.title
    action_mode = "pick_one"
    if batch_state.mode == "confirm_one":
        action_mode = "confirm_one"
    elif batch_state.mode == "add":
        action_mode = "add"
    can_go_prev = batch_state.can_go_prev
    can_go_next = batch_state.can_go_next
    next_pending = batch_state.next_pending
    if batch_state.mode == "add":
        current_index = batch_state.batch_index
        ready_count = len(ui_session._a4_precomputed_rounds)
        can_go_prev = current_index > 0
        can_go_next = (current_index + 1) < ready_count
        next_pending = (current_index + 1) >= ready_count and not ui_session._a4_precompute_complete
    return {
        "kind": "batch",
        "batch_id": batch_state.batch_id,
        "agent_id": "A4" if batch_state.mode == "add" else "A1",
        "title": title,
        "category": batch_state.category,
        "action_mode": action_mode,
        "cards": _serialize(batch_state.cards),
        "allow_skip": batch_state.allow_skip,
        "theme_focus": batch_state.theme_focus,
        "can_go_prev": can_go_prev,
        "can_go_next": can_go_next,
        "next_pending": next_pending,
        "batch_index": batch_state.batch_index,
    }


@app.get("/")
def index():
    ui_session = _get_ui_session()
    deck_state = ui_session.get_deck_state_event()
    active_prompt = ui_session.active_prompt
    active_batch = _current_batch_for_render(ui_session)
    loading_context = (
        ui_session.get_loading_view_model()
        if ui_session.phase in {"loading", "a4_pending"}
        else None
    )
    auto_refresh_active = bool(
        (loading_context and loading_context.get("is_loading"))
        or (
            ui_session.phase == "a4"
            and ui_session._a4_precompute_started
            and not ui_session._a4_precompute_complete
        )
    )
    return render_template(
        "chat.html",
        events=[_serialize_event(event) for event in _get_event_log()],
        deck_state=_serialize(deck_state),
        active_prompt=_serialize_event(active_prompt) if active_prompt else None,
        active_batch=active_batch,
        phase=ui_session.phase,
        notice=_get_notice(),
        loading_context=_serialize(loading_context),
        auto_refresh_active=auto_refresh_active,
    )


@app.post("/submit")
def submit_text():
    ui_session = _get_ui_session()
    prompt = ui_session.active_prompt
    prompt_id = request.form.get("prompt_id", "").strip()
    user_text = request.form.get("user_text", "").strip()

    if not prompt or prompt.kind != "text":
        _set_notice("Submit ignored: no active text prompt was available.")
        return redirect(url_for("index"))
    if not user_text:
        _set_notice("Submit ignored: empty input.")
        return redirect(url_for("index"))
    if ui_session.is_busy:
        _set_notice("Submit ignored: session was already busy.")
        return redirect(url_for("index"))
    if prompt.prompt_id != prompt_id:
        _set_notice(
            f"Prompt id mismatch: page={prompt_id or 'none'} session={prompt.prompt_id}. Processing anyway."
        )
    else:
        _set_notice("")

    ui_session.is_busy = True
    try:
        _append_events(ui_session.submit_text(user_text))
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/select-card")
def select_card():
    ui_session = _get_ui_session()
    batch_state = ui_session.active_batch
    batch_id = request.form.get("batch_id", "").strip()
    card_name = request.form.get("card_name", "").strip()

    if not batch_state or not batch_id or not card_name:
        _set_notice("Card selection ignored: no active batch or missing card.")
        return redirect(url_for("index"))
    if ui_session.is_busy:
        _set_notice("Card selection ignored: session was already busy.")
        return redirect(url_for("index"))
    if batch_state.batch_id != batch_id:
        _set_notice(
            f"Batch id mismatch: page={batch_id or 'none'} session={batch_state.batch_id}. Processing anyway."
        )
    else:
        _set_notice("")

    ui_session.is_busy = True
    try:
        _append_events(ui_session.select_card(batch_id, card_name))
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/add-edhrec")
def add_edhrec():
    ui_session = _get_ui_session()
    section = request.form.get("section", "").strip()
    card_name = request.form.get("card_name", "").strip()
    if not section or not card_name:
        _set_notice("EDHREC add ignored: missing section or card.")
        return redirect(url_for("index"))
    if ui_session.is_busy:
        _set_notice("EDHREC add ignored: session was already busy.")
        return redirect(url_for("index"))
    _set_notice("")
    ui_session.is_busy = True
    try:
        _append_events(ui_session.add_edhrec_card(section, card_name))
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/skip")
def skip():
    ui_session = _get_ui_session()
    if ui_session.is_busy:
        _set_notice("Skip ignored: session was already busy.")
        return redirect(url_for("index"))
    _set_notice("")
    ui_session.is_busy = True
    try:
        _append_events(ui_session.skip())
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/start-a4")
def start_a4():
    ui_session = _get_ui_session()
    if ui_session.is_busy:
        _set_notice("A4 start ignored: session was already busy.")
        return redirect(url_for("index"))
    _set_notice("")
    ui_session.is_busy = True
    try:
        _append_events(ui_session.start_a4())
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/a4-next")
def a4_next():
    ui_session = _get_ui_session()
    if ui_session.is_busy:
        _set_notice("A4 next ignored: session was already busy.")
        return redirect(url_for("index"))
    _set_notice("")
    ui_session.is_busy = True
    try:
        _append_events(ui_session.next_a4_batch())
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/a4-prev")
def a4_prev():
    ui_session = _get_ui_session()
    if ui_session.is_busy:
        _set_notice("A4 previous ignored: session was already busy.")
        return redirect(url_for("index"))
    _set_notice("")
    ui_session.is_busy = True
    try:
        _append_events(ui_session.previous_a4_batch())
    finally:
        ui_session.is_busy = False
    return redirect(url_for("index"))


@app.post("/reset")
def reset():
    sid = _get_session_id()
    _SESSIONS.pop(sid, None)
    _EVENT_LOGS.pop(sid, None)
    session.pop("deckbuilder_ui_sid", None)
    session.pop("deckbuilder_ui_notice", None)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
