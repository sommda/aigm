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
    DigestRequest,
    ChapterProposal,
    EndingProposal,
    EntityProposal,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    FamiliarityRequest,
    Label,
    MotiveProposal,
    MotiveReport,
    PlotProposal,
    PlotRequest,
    ReconcileRequest,
    QuestProposal,
    ReconcileResult,
    SheetRequest,
)
from aigm.sheets import Sheet, clean
from aigm.world.model import ASPECTS, DISCLOSURES, KINDS, MOTIVE_KINDS
from aigm.world.render import (
    render_bootstrap,
    render_digest,
    render_expand,
    render_extract,
    render_familiarity,
    render_sheet,
    render_plot,
    render_reconcile,
)

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

_MOTIVE_REPORT = _obj(
    id=_STR,
    action={"type": "string", "enum": ["shift", "resolve", "hint"]},
    text=_nullable(_STR),
    strength=_nullable({"type": "string", "enum": ["leaning", "driven"]}),
    outcome=_nullable({"type": "string", "enum": ["satisfied", "frustrated"]}),
)
_MOTIVE = _obj(
    owner=_STR,
    text=_STR,
    kind={"type": "string", "enum": list(MOTIVE_KINDS)},
    strength={"type": "string", "enum": ["leaning", "driven", "absolute"]},
    moved_by=_STRS,
    resists=_STRS,
    tells=_STRS,
)

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
    motive_reports={"type": "array", "items": _MOTIVE_REPORT},
)
STORY_EXTRACT_SCHEMA = _obj(
    **EXTRACT_SCHEMA["properties"],
    quest_reports={
        "type": "array",
        "items": _obj(id=_STR, status={"type": "string", "enum": ["done", "skipped", "failed"]}, outcome=_STR),
    },
    goal_revealed={"type": "boolean"},
)  # the extract step of a story game: the same answer plus what happened to the quests
BOOTSTRAP_SCHEMA = _obj(
    entities={"type": "array", "items": _ENTITY},
    facts=EXTRACT_SCHEMA["properties"]["facts"],
    location=_nullable(_STR),
    present=_nullable(_STRS),
    start_hour=_nullable({"type": "integer"}),
)
FAMILIARITY_SCHEMA = _obj(
    entities={"type": "array", "items": _ENTITY},
    facts={"type": "array", "items": _obj(text=_STR, about=_STRS, aspect=_ASPECT, via=_STRS)},
)
SHEET_SCHEMA = _obj(
    headline=_STR,
    hp=_nullable({"type": "integer"}),
    max_hp=_nullable({"type": "integer"}),
    conditions=_STRS,
    sections={"type": "array", "items": _obj(title=_STR, lines=_STRS)},
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
    motives={"type": "array", "items": _MOTIVE},
)
PLOT_SCHEMA = _obj(
    goal_title=_STR,
    goal_summary=_STR,
    min_strength=_STR,
    goal_entities=_STRS,
    chapters={
        "type": "array",
        "items": _obj(title=_STR, purpose=_STR, target_level=_nullable({"type": "integer"})),
    },
    quests={
        "type": "array",
        "items": _obj(
            key=_STR,
            chapter={"type": "integer"},
            title=_STR,
            brief=_STR,
            scale={"type": "string", "enum": ["small", "medium", "large"]},
            gives=_STR,
            requires=_STRS,
            required={"type": "boolean"},
            entities=_STRS,
        ),
    },
    endings={"type": "array", "items": _obj(title=_STR, when=_STR)},
    entities={"type": "array", "items": _ENTITY},
    facts={"type": "array", "items": _obj(text=_STR, about=_STRS, aspect=_ASPECT)},
)
DIGEST_SCHEMA = _obj(digests={"type": "array", "items": _obj(turn={"type": "integer"}, text=_STR)})
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
                _strs(raw.get("via")),
            )
        )
    return out


def _motives(value: Any) -> list[MotiveProposal]:
    out = []
    for raw in value if isinstance(value, list) else []:
        if isinstance(raw, dict) and isinstance(raw.get("owner"), str) and isinstance(raw.get("text"), str):
            out.append(
                MotiveProposal(
                    raw["owner"], raw["text"],
                    raw["kind"] if raw.get("kind") in MOTIVE_KINDS else "want",
                    raw["strength"] if raw.get("strength") in ("leaning", "driven", "absolute") else "leaning",
                    _strs(raw.get("moved_by")), _strs(raw.get("resists")), _strs(raw.get("tells")),
                )  # fmt: skip
            )
    return out


def _motive_reports(value: Any) -> list[MotiveReport]:
    out = []
    for raw in value if isinstance(value, list) else []:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str) and isinstance(raw.get("action"), str):
            text, strength, outcome = raw.get("text"), raw.get("strength"), raw.get("outcome")
            out.append(
                MotiveReport(
                    raw["id"], raw["action"], text if isinstance(text, str) else None,
                    strength if isinstance(strength, str) else None, outcome if isinstance(outcome, str) else None,
                )  # fmt: skip
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
        self.system = {n: prompts.world_prompt(n) for n in ("extract", "reconcile", "expand", "independence", "bootstrap", "familiarity", "sheet", "digest", "plot")}
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
        schema = STORY_EXTRACT_SCHEMA if request.quests or request.goal else EXTRACT_SCHEMA
        data = await self._ask("extract", self.model, self.effort, render_extract(request), schema)
        present = data.get("present")
        elapsed = data.get("elapsed_hours")
        reports = [
            (r["id"], r["status"], r["outcome"])
            for r in (data.get("quest_reports") if isinstance(data.get("quest_reports"), list) else [])
            if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("id", "status", "outcome"))
        ]
        return Extraction(
            quest_reports=reports,
            goal_revealed=data.get("goal_revealed") is True,
            entities=_entities(data.get("entities")),
            facts=_facts(data.get("facts"), "hidden"),
            reveals=_strs(data.get("reveals")),
            location=data["location"] if isinstance(data.get("location"), str) else None,
            present=_strs(present) if isinstance(present, list) else None,
            elapsed_hours=elapsed if isinstance(elapsed, int) and not isinstance(elapsed, bool) else 0,
            motive_reports=_motive_reports(data.get("motive_reports")),
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

    async def familiarity(self, request: FamiliarityRequest) -> Extraction:
        # Invention, like expansion, so the stronger model.
        data = await self._ask(
            "familiarity", self.expand_model, self.expand_effort, render_familiarity(request), FAMILIARITY_SCHEMA
        )
        return Extraction(entities=_entities(data.get("entities")), facts=_facts(data.get("facts"), "known"))

    async def sheet(self, request: SheetRequest) -> Sheet:
        # Copying a sheet that is already written: the cheap model is enough.
        data = await self._ask("sheet", self.model, self.effort, render_sheet(request), SHEET_SCHEMA)
        try:
            return clean(data)
        except ValueError as exc:
            raise CuratorError(f"sheet: {exc}") from None

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
        return Extraction(
            entities=_entities(data.get("entities")),
            facts=_facts(data.get("facts"), "hidden"),
            motives=_motives(data.get("motives")),
        )

    async def plot(self, request: PlotRequest) -> PlotProposal:
        # Invention that shapes a whole game: the stronger model.
        data = await self._ask("plot", self.expand_model, self.expand_effort, render_plot(request), PLOT_SCHEMA)
        text = lambda v: v if isinstance(v, str) else ""  # noqa: E731
        whole = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None  # noqa: E731

        def items(key: str) -> list[dict[str, Any]]:
            found = data.get(key)
            return [x for x in found if isinstance(x, dict)] if isinstance(found, list) else []

        return PlotProposal(
            goal_title=text(data.get("goal_title")),
            goal_summary=text(data.get("goal_summary")),
            min_strength=text(data.get("min_strength")),
            goal_entities=_strs(data.get("goal_entities")),
            chapters=[ChapterProposal(text(c.get("title")), text(c.get("purpose")), whole(c.get("target_level"))) for c in items("chapters")],
            quests=[
                QuestProposal(
                    text(q.get("key")), whole(q.get("chapter")) or 0, text(q.get("title")), text(q.get("brief")),
                    text(q.get("scale")), text(q.get("gives")), _strs(q.get("requires")), q.get("required") is not False,
                    _strs(q.get("entities")),
                )
                for q in items("quests")
            ],
            endings=[EndingProposal(text(e.get("title")), text(e.get("when"))) for e in items("endings")],
            entities=_entities(data.get("entities")),
            facts=_facts(data.get("facts"), "hidden"),
        )  # fmt: skip

    async def judge_independence(self, texts: list[str]) -> list[int]:
        numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
        data = await self._ask("independence", self.model, self.effort, numbered, JUDGE_SCHEMA)
        found = data.get("violations")
        return [v["index"] for v in found if isinstance(v, dict) and isinstance(v.get("index"), int)] if isinstance(found, list) else []

    async def digest(self, request: DigestRequest) -> list[str]:
        data = await self._ask("digest", self.model, self.effort, render_digest(request), DIGEST_SCHEMA)
        found = data.get("digests")
        by_number = {
            d["turn"]: d["text"]
            for d in (found if isinstance(found, list) else [])
            if isinstance(d, dict) and isinstance(d.get("turn"), int) and isinstance(d.get("text"), str)
        }
        return [by_number.get(t.number, "") for t in request.turns]
