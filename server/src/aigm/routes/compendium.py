"""The player's compendium (docs/COMPENDIUM.md): what the party has learned about the world, and what is new."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field, model_validator

from aigm import compendium as comp
from aigm.deps import get_session
from aigm.errors import NotFound
from aigm.session.store import Session

router = APIRouter(prefix="/compendium")
SessionDep = Annotated[Session, Depends(get_session)]
ENTITY_ID = r"^e\d+$"


class SeenRequest(BaseModel):
    entities: list[Annotated[str, Field(pattern=ENTITY_ID)]] | None = None
    all: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> "SeenRequest":
        if (self.entities is None) == (not self.all):
            raise ValueError("send either entities or all: true")
        return self


def _summary(session: Session) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "phase": session.state.phase.value,
        **comp.summary(session.state.world, session.reading_state()),
    }


@router.get("")
def overview(session: SessionDep) -> dict[str, Any]:
    return _summary(session)


@router.get("/entities/{entity_id}")
def entity(session: SessionDep, entity_id: Annotated[str, Path(pattern=ENTITY_ID)]) -> dict[str, Any]:
    found = comp.detail(session.state.world, session.reading_state(), entity_id)
    if found is None:  # the same answer for an id that does not exist and one the player has not discovered
        raise NotFound(f"No compendium entry {entity_id!r}")
    return {"session_id": session.id, **found}


@router.get("/{category}")
def category_list(
    session: SessionDep,
    category: str,
    q: Annotated[str | None, Query(max_length=80)] = None,
    status: Literal["new", "updated", "unseen"] | None = None,
    sort: Literal["name", "recent", "tree"] = "name",
) -> dict[str, Any]:
    if category not in comp.CATEGORIES:
        raise NotFound(f"No compendium category {category!r}")
    if sort == "tree" and category != "locations":
        sort = "name"  # containment is only meaningful for places
    rows = comp.entries(session.state.world, session.reading_state(), category, q=q, status=status, sort=sort)
    return {
        "session_id": session.id,
        "category": category,
        "title": comp.CATEGORIES[category][0],
        "count": len(rows),
        "entries": rows,
    }


@router.post("/seen")
def seen(session: SessionDep, body: SeenRequest) -> dict[str, Any]:
    session.mark_seen(None if body.all else list(body.entities or []))
    return _summary(session)
