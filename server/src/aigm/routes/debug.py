"""Debug-only endpoints. This router is registered only when the server runs with --debug (docs/CONTEXT.md),
so without it these paths do not exist."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from aigm import rulesets
from aigm.compendium import unseen_totals
from aigm.context_view import build_context
from aigm.deps import get_session
from aigm.session.state import Phase
from aigm.session.store import Session
from aigm.story import needs_plan, summary_so_far
from aigm.world.ops import apply_ops
from aigm.world.passes import run_backfill, run_sheets

log = logging.getLogger(__name__)
router = APIRouter(prefix="/debug")


@router.get("/context")
def context(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    draft: Annotated[str, Query(max_length=20000, description="The text typed so far")] = "",
) -> dict[str, Any]:
    log.info("context requested for session %s", session.id)  # the content is never logged
    return build_context(
        game=request.app.state.game, session=session, model=request.app.state.model_name, draft=draft
    )


class ThinkingSetting(BaseModel):
    enabled: bool


@router.get("/thinking")
def get_thinking(request: Request) -> dict[str, bool]:
    return {"thinking": getattr(request.app.state.llm, "thinking", True)}


@router.put("/thinking")
def set_thinking(request: Request, body: ThinkingSetting) -> dict[str, bool]:
    """Turns the GM's model thinking on or off for every session until changed (or the server restarts), so one
    action can be tried both ways from the same save."""
    request.app.state.llm.thinking = body.enabled
    log.info("model thinking %s", "on" if body.enabled else "off")
    return {"thinking": body.enabled}


class BackfillRequest(BaseModel):
    backgrounds: dict[str, str] = {}


@router.post("/backfill")
async def backfill(
    request: Request, body: BackfillRequest, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    """Records what the characters know of the world in a game that began without it (docs/OPENING.md 9). The
    optional `backgrounds` map character names to a background (they are kept in the record for the next pass);
    a character with none is judged from the sheet. The result is shown as new in the compendium."""
    service = request.app.state.curator
    if service is None:
        raise HTTPException(status_code=409, detail="The world curator is off")
    state = session.state
    if state.phase is not Phase.ADVENTURE or not state.campaign:
        raise HTTPException(status_code=409, detail="There is no adventure to backfill")
    if session.busy or session.curating:
        raise HTTPException(status_code=409, detail="A turn or a curator pass is running; try again in a moment")
    session.curating = True
    generation = session.generation
    try:
        result = await run_backfill(state.world, state.campaign, service.curator, body.backgrounds)
    except Exception as exc:
        log.exception("backfill failed")
        raise HTTPException(status_code=502, detail=f"The curator failed ({type(exc).__name__})") from None
    finally:
        session.curating = False
    if session.generation != generation or session.busy:
        raise HTTPException(status_code=409, detail="The game changed while this ran; try again")
    for member in state.campaign.get("party", []):
        text = next((v for k, v in body.backgrounds.items() if k.strip().lower() == str(member.get("name", "")).lower()), None)
        if isinstance(member, dict) and text and text.strip():
            member["background"] = text.strip()
    before = len(state.world.facts)
    applied = apply_ops(state.world, result.ops)
    log.info("backfill: %d ops applied, %d skipped", len(applied.ops), len(applied.skipped))
    return {
        "facts_added": len(state.world.facts) - before,
        "notes": [*result.notes, *applied.skipped],
        "compendium": unseen_totals(state.world, session.reading_state()),
    }


@router.post("/sheets")
async def sheets(request: Request, session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """Writes every party member's sheet out as sections, for a game that began without them (docs/STATUS.md 9).
    Sheets already written are replaced. A member whose sheet could not be written keeps what they had."""
    service = request.app.state.curator
    if service is None:
        raise HTTPException(status_code=409, detail="The world curator is off")
    state = session.state
    if state.phase is not Phase.ADVENTURE or not state.campaign:
        raise HTTPException(status_code=409, detail="There is no adventure to write sheets for")
    if session.busy or session.curating:
        raise HTTPException(status_code=409, detail="A turn or a curator pass is running; try again in a moment")
    session.curating = True
    generation = session.generation
    try:
        written, notes = await run_sheets(
            state.campaign, rulesets.get(state.ruleset).name, {n: state.hero(n).level for n in state.party_names}, service.curator
        )
    except Exception as exc:
        log.exception("writing sheets failed")
        raise HTTPException(status_code=502, detail=f"The curator failed ({type(exc).__name__})") from None
    finally:
        session.curating = False
    if session.generation != generation or session.busy:
        raise HTTPException(status_code=409, detail="The game changed while this ran; try again")
    state.sheets.update(written)
    return {"written": sorted(written), "notes": notes}


@router.get("/story")
def story(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """The whole story plan, spoilers and all, and the same as readable text."""
    state = session.state
    plan = state.story
    return {
        "session_id": session.id,
        "structure": state.structure,
        "story": plan.to_dict() if plan else None,
        "text": summary_so_far(plan) if plan else "",
        "waiting_for_plan": needs_plan(plan) if plan else None,
    }
