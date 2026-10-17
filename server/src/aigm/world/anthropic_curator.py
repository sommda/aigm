"""The model-driven curator: structured-output calls to cheaper Claude models (docs/WORLD.md 7).

Extraction, reconciliation and the independence check use a small model (`model`); expansion, where
invention quality matters, uses `expand_model`. Answers are constrained to a JSON schema with
`output_config.format`, since the newest models reject a forced tool call. Anything unusable raises
`CuratorError`, which makes the pass fail harmlessly and retry later."""

import json
import logging
from typing import Any

import anthropic

from aigm.prompts import PromptLibrary
from aigm.world.curator import (
    BootstrapRequest,
    CuratorError,
    EntityProposal,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    Label,
    ReconcileRequest,
    ReconcileResult,
)
from aigm.world.model import ASPECTS, DISCLOSURES, KINDS
from aigm.world.render import render_bootstrap, render_expand, render_extract, render_reconcile

log = logging.getLogger(__name__)
LABELS = ("new", "duplicate", "refines", "contradicts")


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
_ASPECT = _nullable({"type": "string", "enum": sorted({a for v in ASPECTS.values() for a in v})})
_ENTITY = _obj(name=_STR, kind={"type": "string", "enum": list(KINDS)}, aliases=_STRS, parent=_nullable(_STR))

EXTRACT_SCHEMA = _obj(
    entities={"type": "array", "items": _ENTITY},
    facts={
        "type": "array",
        "items": _obj(
            text=_STR, about=_STRS, aspect=_ASPECT, disclosure={"type": "string", "enum": list(DISCLOSURES)}, evidence=_STR
        ),
    },
    reveals=_STRS,
    location=_nullable(_STR),
    present=_nullable(_STRS),
    elapsed_hours={"type": "integer"},
)
BOOTSTRAP_SCHEMA = _obj(
    entities={"type": "array", "items": _ENTITY},
    facts=EXTRACT_SCHEMA["properties"]["facts"],
    location=_nullable(_STR),
    present=_nullable(_STRS),
    start_hour=_nullable({"type": "integer"}),
)
RECONCILE_SCHEMA = _obj(
    labels={
        "type": "array",
        "items": _obj(
            index={"type": "integer"},
            label={"type": "string", "enum": list(LABELS)},
            existing_id=_nullable(_STR),
            with_proposal=_nullable({"type": "integer"}),
        ),
    },
    same_as={"type": "array", "items": _obj(name=_STR, entity_id=_STR)},
)
EXPAND_SCHEMA = _obj(
    entities={"type": "array", "items": _ENTITY},
    facts={
        "type": "array",
        "items": _obj(text=_STR, about=_STRS, aspect=_ASPECT, replaces=_nullable(_STR)),
    },
)
JUDGE_SCHEMA = _obj(violations={"type": "array", "items": _obj(index={"type": "integer"}, reason=_STR)})


def _strs(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _entities(value: Any) -> list[EntityProposal]:
    out = []
    for raw in value if isinstance(value, list) else []:
        if isinstance(raw, dict) and isinstance(raw.get("name"), str) and isinstance(raw.get("kind"), str):
            parent = raw.get("parent")
            out.append(EntityProposal(raw["name"], raw["kind"], _strs(raw.get("aliases")), parent if isinstance(parent, str) else None))
    return out


def _facts(value: Any, default_disclosure: str) -> list[FactProposal]:
    out = []
    for raw in value if isinstance(value, list) else []:
        if not (isinstance(raw, dict) and isinstance(raw.get("text"), str)):
            continue
        aspect, replaces = raw.get("aspect"), raw.get("replaces")
        out.append(
            FactProposal(
                raw["text"],
                _strs(raw.get("about")),
                aspect if isinstance(aspect, str) else None,
                raw.get("disclosure") if raw.get("disclosure") in DISCLOSURES else default_disclosure,
                raw.get("evidence") if isinstance(raw.get("evidence"), str) else "",
                replaces if isinstance(replaces, str) else None,
            )
        )
    return out


class AnthropicCurator:
    def __init__(
        self,
        *,
        api_key: str | None,
        prompts: PromptLibrary,
        model: str = "claude-haiku-5-5",
        expand_model: str = "claude-sonnet-5-5",
        effort: str = "low",
        expand_effort: str = "medium",
        max_tokens: int = 8000,
        client: Any = None,
    ) -> None:
        self.api_key = api_key
        self.model, self.expand_model = model, expand_model
        self.effort, self.expand_effort = effort, expand_effort
        self.max_tokens = max_tokens
        self._client = client
        self.system = {n: prompts.world_prompt(n) for n in ("extract", "reconcile", "expand", "independence", "bootstrap")}
        self.guides = prompts.aspect_guides()

    def _get_client(self) -> Any:
        if self._client is None:  # created lazily so the server starts before credentials exist
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def _ask(self, step: str, model: str, effort: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": self.system[step], "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        response = await self._get_client().messages.create(**params)
        usage = getattr(response, "usage", None)
        log.info("curator %s (%s): in=%s out=%s", step, model, getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"))
        if response.stop_reason in ("refusal", "max_tokens"):
            raise CuratorError(f"{step}: the model stopped with {response.stop_reason}")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        try:
            data = json.loads(text or "")
        except ValueError:
            raise CuratorError(f"{step}: the model did not return JSON") from None
        if not isinstance(data, dict):
            raise CuratorError(f"{step}: the model returned {type(data).__name__}, not an object")
        return data

    async def extract(self, request: ExtractRequest) -> Extraction:
        data = await self._ask("extract", self.model, self.effort, render_extract(request), EXTRACT_SCHEMA)
        present = data.get("present")
        elapsed = data.get("elapsed_hours")
        return Extraction(
            entities=_entities(data.get("entities")),
            facts=_facts(data.get("facts"), "hidden"),
            reveals=_strs(data.get("reveals")),
            location=data["location"] if isinstance(data.get("location"), str) else None,
            present=_strs(present) if isinstance(present, list) else None,
            elapsed_hours=elapsed if isinstance(elapsed, int) and not isinstance(elapsed, bool) else 0,
        )

    async def bootstrap(self, request: BootstrapRequest) -> Extraction:
        # Structuring a record that is already written: the cheap model is enough. The invention
        # that follows (expansion around the opening) uses the stronger one.
        data = await self._ask("bootstrap", self.model, self.effort, render_bootstrap(request), BOOTSTRAP_SCHEMA)
        present, hour = data.get("present"), data.get("start_hour")
        return Extraction(
            entities=_entities(data.get("entities")),
            facts=_facts(data.get("facts"), "hidden"),
            location=data["location"] if isinstance(data.get("location"), str) else None,
            present=_strs(present) if isinstance(present, list) else None,
            start_hour=hour if isinstance(hour, int) and not isinstance(hour, bool) else None,
        )

    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        data = await self._ask("reconcile", self.model, self.effort, render_reconcile(request), RECONCILE_SCHEMA)
        result = ReconcileResult()
        for raw in data.get("labels", []) if isinstance(data.get("labels"), list) else []:
            if isinstance(raw, dict) and isinstance(raw.get("index"), int) and raw.get("label") in LABELS:
                existing, other = raw.get("existing_id"), raw.get("with_proposal")
                result.labels.append(
                    Label(raw["index"], raw["label"], existing if isinstance(existing, str) else None,
                          other if isinstance(other, int) else None)
                )  # fmt: skip
        for raw in data.get("same_as", []) if isinstance(data.get("same_as"), list) else []:
            if isinstance(raw, dict) and isinstance(raw.get("name"), str) and isinstance(raw.get("entity_id"), str):
                result.same_as[raw["name"]] = raw["entity_id"]
        return result

    async def expand(self, request: ExpandRequest) -> Extraction:
        user = render_expand(request, self.guides)
        data = await self._ask("expand", self.expand_model, self.expand_effort, user, EXPAND_SCHEMA)
        return Extraction(entities=_entities(data.get("entities")), facts=_facts(data.get("facts"), "hidden"))

    async def judge_independence(self, texts: list[str]) -> list[int]:
        numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
        data = await self._ask("independence", self.model, self.effort, numbered, JUDGE_SCHEMA)
        found = data.get("violations")
        return [v["index"] for v in found if isinstance(v, dict) and isinstance(v.get("index"), int)] if isinstance(found, list) else []
