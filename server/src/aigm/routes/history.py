from typing import Annotated, Any

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from aigm.compendium import unseen_totals
from aigm.deps import get_repo, get_session
from aigm.errors import Conflict
from aigm.session.persistence import HistoryRepository
from aigm.session.store import Session
from aigm.story import public_summary

log = logging.getLogger(__name__)
CATCH_UP_ROUNDS = 4  # sweeps of each kind after a restore: a few turns' worth, so a loaded game fills in

router = APIRouter(prefix="/history")
RepoDep = Annotated[HistoryRepository, Depends(get_repo)]
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
async def list_histories(repo: RepoDep) -> dict[str, Any]:
    return {"histories": await repo.list_all()}


@router.get("/{name}")
async def history_info(name: str, repo: RepoDep, include_messages: Annotated[bool, Query()] = False) -> dict[str, Any]:
    return await repo.info(name, include_messages)


@router.put("/{name}/save")
async def save_history(
    name: str,
    request: Request,
    repo: RepoDep,
    session: SessionDep,
    overwrite: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    if session.busy:
        raise Conflict("A turn is in progress for this session; wait for it to finish before saving")
    result = await repo.save(name, list(session.messages), session.state, request.app.state.model_name, overwrite)
    return {**result, "session_id": session.id}


@router.post("/{name}/restore")
async def restore_history(
    name: str, request: Request, repo: RepoDep, session: SessionDep, background: BackgroundTasks
) -> dict[str, Any]:
    if session.busy:
        raise Conflict("A turn is in progress for this session; wait for it to finish before restoring")
    messages, state, info = await repo.load(name)  # fully validated before anything is replaced
    if session.busy:  # re-check: a turn may have started while the file was being read
        raise Conflict("A turn started while restoring; try again")
    replaced = len(session.messages)
    session.messages = messages
    session.state = state
    session.reset_world_work()
    await request.app.state.dumper.update(session)
    background.add_task(catch_up, request.app, session, session.generation)
    return {
        "name": name,
        "session_id": session.id,
        "phase": state.phase.value,
        "ruleset": state.ruleset,
        "story": public_summary(state.story),
        "compendium": unseen_totals(state.world, state.compendium),
        "message_count": len(messages),
        "saved_at": info["saved_at"],
        "replaced_message_count": replaced,
    }


async def catch_up(app: Any, session: Session, generation: int) -> None:
    """After a game is loaded, write the descriptions and pictures it is missing without waiting for a turn: Looks of
    people, then of places, then the pictures, a few sweeps of each (the same sweeps a turn runs, never the world pass).
    A game loaded from a save made before these existed, or one the server was stopped in the middle of, fills in
    while the player reads. It stops if the game is replaced, and never raises."""
    try:
        service, portraits = app.state.curator, app.state.portraits
        for _ in range(CATCH_UP_ROUNDS):
            if session.generation != generation:
                return
            progressed = False
            if service is not None:
                progressed |= await service.run_looks_if_due(session)
                progressed |= await service.run_place_looks_if_due(session)
            if portraits is not None:
                progressed |= await portraits.run_if_due(session)
            if not progressed:
                break
        await app.state.dumper.update(session)
    except Exception:
        log.exception("catching up on descriptions and pictures failed")


@router.delete("/{name}")
async def delete_history(name: str, repo: RepoDep) -> dict[str, Any]:
    await repo.delete(name)
    return {"name": name, "deleted": True}
