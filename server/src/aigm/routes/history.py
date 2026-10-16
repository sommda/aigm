from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from aigm.deps import get_repo, get_session
from aigm.errors import Conflict
from aigm.session.persistence import HistoryRepository
from aigm.session.store import Session

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
async def restore_history(name: str, repo: RepoDep, session: SessionDep) -> dict[str, Any]:
    if session.busy:
        raise Conflict("A turn is in progress for this session; wait for it to finish before restoring")
    messages, state, info = await repo.load(name)  # fully validated before anything is replaced
    if session.busy:  # re-check: a turn may have started while the file was being read
        raise Conflict("A turn started while restoring; try again")
    replaced = len(session.messages)
    session.messages = messages
    session.state = state
    return {
        "name": name,
        "session_id": session.id,
        "phase": state.phase.value,
        "message_count": len(messages),
        "saved_at": info["saved_at"],
        "replaced_message_count": replaced,
    }


@router.delete("/{name}")
async def delete_history(name: str, repo: RepoDep) -> dict[str, Any]:
    await repo.delete(name)
    return {"name": name, "deleted": True}
