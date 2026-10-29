from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    debug = request.app.state.settings.debug
    info: dict[str, Any] = {
        "status": "ok", "model": request.app.state.model_name, "debug": debug, "compendium": True, "status": True,
        "images": request.app.state.portraits is not None,
    }  # fmt: skip
    if debug:
        info["thinking"] = getattr(request.app.state.llm, "thinking", True)
    return info
