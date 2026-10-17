from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return {"status": "ok", "model": request.app.state.model_name, "debug": request.app.state.settings.debug}
