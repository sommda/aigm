"""Named saved histories ("save files") stored as JSON under the save directory."""

import asyncio
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aigm.errors import AlreadyExists, BadRequest, CorruptSave, NotFound
from aigm.models import ID_RE
from aigm.session.state import GameState
from aigm.story import public_summary

log = logging.getLogger(__name__)
FORMAT_VERSION = 10  # 1: messages only (read as mid-adventure); 2: adds game state; 3: adds the world; 4: adds the story; 5: adds the party's level and XP; 6: adds the compendium's reading state and when facts were learned; 7: adds whom a starting fact is known by; 8: adds the character sheets; 9: adds the fight in progress; 10: adds the characters' looks
READABLE_VERSIONS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def validate_name(name: str) -> str:
    if not ID_RE.match(name):
        raise BadRequest(f"Invalid name {name!r}: use 1-64 letters, digits, '-' or '_'.")
    return name


def validate_messages(messages: Any) -> None:
    """Check structure well enough that the API will accept the history back."""
    if not isinstance(messages, list):
        raise CorruptSave("messages must be a list")
    pending: set[str] = set()  # tool_use ids awaiting a tool_result
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") not in ("user", "assistant"):
            raise CorruptSave(f"message {i}: bad role")
        if msg["role"] != ("user" if i % 2 == 0 else "assistant"):
            raise CorruptSave(f"message {i}: roles must alternate user/assistant starting with user")
        content = msg.get("content")
        if not isinstance(content, list) or not all(isinstance(b, dict) and "type" in b for b in content):
            raise CorruptSave(f"message {i}: content must be a list of blocks")
        if msg["role"] == "assistant":
            if pending:
                raise CorruptSave(f"message {i}: tool_use without tool_result")
            pending = {b["id"] for b in content if b["type"] == "tool_use" and "id" in b}
        else:
            results = {b.get("tool_use_id") for b in content if b["type"] == "tool_result"}
            if results != pending:
                raise CorruptSave(f"message {i}: tool_result does not match tool_use")
            pending = set()
    if pending:
        raise CorruptSave("history ends with an unanswered tool_use")


def last_assistant_preview(messages: list[dict[str, Any]], limit: int = 200) -> str | None:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        text = "".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text").strip()
        if text:
            return text[:limit]
    return None


class HistoryRepository:
    def __init__(self, save_dir: Path) -> None:
        self.dir = Path(save_dir)

    def _path(self, name: str) -> Path:
        return self.dir / f"{validate_name(name)}.json"

    # ---- sync implementations (run in a thread by the async wrappers) -------------------

    def _read(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotFound(f"No saved history named '{name}'") from None
        except (OSError, ValueError) as exc:
            raise CorruptSave(f"Saved history '{name}' is unreadable: {exc}") from None
        if not isinstance(data, dict) or data.get("version") not in READABLE_VERSIONS:
            raise CorruptSave(f"Saved history '{name}' has an unsupported format")
        validate_messages(data.get("messages"))
        data["state"] = GameState.from_dict(data)
        return data

    def _info(self, data: dict[str, Any], include_messages: bool) -> dict[str, Any]:
        messages = data["messages"]
        counts = data["state"].world.counts()
        info: dict[str, Any] = {
            "name": data["name"],
            "message_count": len(messages),
            "saved_at": data.get("saved_at"),
            "model": data.get("model"),
            "phase": data["state"].phase.value,
            "structure": data["state"].structure,
            "story": public_summary(data["state"].story),
            "entity_count": counts["entities"],
            "fact_count": counts["facts"],
            "world_time": data["state"].world.time.to_dict(),
        }
        preview = last_assistant_preview(messages)
        if preview:
            info["last_message_preview"] = preview
        if include_messages:
            info["messages"] = messages
        return info

    def _list(self) -> list[dict[str, Any]]:
        infos = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            if not ID_RE.match(path.stem):
                continue
            try:
                info = self._info(self._read(path.stem), False)
            except Exception as exc:  # a bad file must not break the listing
                log.warning("skipping unreadable save %s: %s", path.name, exc)
                continue
            info.pop("last_message_preview", None)
            infos.append(info)
        return sorted(infos, key=lambda i: i.get("saved_at") or "", reverse=True)

    def _save(
        self, name: str, messages: list[dict[str, Any]], state: GameState, model: str, overwrite: bool
    ) -> dict[str, Any]:
        path = self._path(name)
        existed = path.exists()
        if existed and not overwrite:
            raise AlreadyExists(f"A saved history named '{name}' already exists (use overwrite=true)")
        saved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "version": FORMAT_VERSION,
            "name": name,
            "saved_at": saved_at,
            "model": model,
            "message_count": len(messages),
            **state.to_dict(),
            "messages": messages,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return {
            "name": name,
            "phase": state.phase.value,
            "message_count": len(messages),
            "saved_at": saved_at,
            "overwritten": existed,
        }

    def _delete(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except FileNotFoundError:
            raise NotFound(f"No saved history named '{name}'") from None

    # ---- async API ----------------------------------------------------------------------

    async def list_all(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list)

    async def info(self, name: str, include_messages: bool = False) -> dict[str, Any]:
        data = await asyncio.to_thread(self._read, name)
        return self._info(data, include_messages)

    async def save(
        self, name: str, messages: list[dict[str, Any]], state: GameState, model: str, overwrite: bool = False
    ) -> dict[str, Any]:
        validate_name(name)
        return await asyncio.to_thread(self._save, name, messages, state.copy(), model, overwrite)

    async def load(self, name: str) -> tuple[list[dict[str, Any]], GameState, dict[str, Any]]:
        data = await asyncio.to_thread(self._read, name)
        return data["messages"], data["state"], self._info(data, False)

    async def delete(self, name: str) -> None:
        await asyncio.to_thread(self._delete, name)
