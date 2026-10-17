"""A deterministic curator for `--test` mode and tests: no model, no network.

It reads directives that the (scripted) GM text contains, so a person can drive the whole pipeline
by hand, for example `echo [[fact: Wren:npc | Wren sells news to the Thorn Guild.]]`:

    [[fact: Subject[:kind] | sentence [| Other, Another]]]     a fact the player was told (kind defaults to npc)
    [[hidden: Subject[:kind] | sentence [| Other, ...]]]       a fact implied but not told
    [[contradict: f0002 | Subject | sentence]]                 a fact that clashes with the existing fact f0002
    [[reveal: f0002]]                                          the narration just told the player f0002
    [[at: Place[:kind]]]  /  [[present: A, B]]                 the party moved / who is with them
    [[elapsed: 3]]                                             in-world hours the narration covered

Expansion writes a plain fact for up to two missing aspects, and gives a bare location a cellar."""

import re

from aigm.world.curator import (
    BootstrapRequest,
    EntityProposal,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    Label,
    ReconcileRequest,
    ReconcileResult,
)

_DIRECTIVE = re.compile(r"\[\[(\w+):\s*(.*?)\]\]", re.DOTALL)
_SPEAKER = re.compile(r"^(GM|PLAYER): ")


def _name_kind(token: str, default: str) -> tuple[str, str]:
    name, _, kind = token.strip().partition(":")
    return name.strip(), (kind.strip() or default)


class ScriptedCurator:
    def __init__(self) -> None:
        self.calls: list[str] = []  # "extract" / "reconcile" / "expand", for tests

    async def extract(self, request: ExtractRequest) -> Extraction:
        self.calls.append("extract")
        out = Extraction()
        kinds: dict[str, str] = {}

        def entity(token: str, default: str = "npc") -> str:
            name, kind = _name_kind(token, default)
            if name and name not in kinds:
                kinds[name] = kind
                out.entities.append(EntityProposal(name, kind))
            return name

        speaker = "GM"
        for para in request.transcript.split("\n\n"):
            match = _SPEAKER.match(para)
            if match:
                speaker = match.group(1)
            if speaker != "GM":
                continue
            for name, body in _DIRECTIVE.findall(para):
                parts = [p.strip() for p in body.split("|")]
                if name in ("fact", "hidden") and len(parts) >= 2:
                    about = [entity(parts[0])] + [entity(p, "npc") for p in (parts[2].split(",") if len(parts) > 2 else [])]
                    out.facts.append(FactProposal(parts[1], about, None, "known" if name == "fact" else "hidden"))
                elif name == "contradict" and len(parts) == 3:
                    out.facts.append(FactProposal(parts[2], [entity(parts[1])], None, "known", f"contradicts:{parts[0]}"))
                elif name == "reveal":
                    out.reveals += [p.strip() for p in body.split(",") if p.strip()]
                elif name == "at":
                    out.location = entity(body, "location")
                elif name == "present":
                    out.present = [entity(p) for p in body.split(",") if p.strip()]
                elif name == "elapsed" and body.strip().isdigit():
                    out.elapsed_hours += int(body.strip())
        return out

    async def bootstrap(self, request: BootstrapRequest) -> Extraction:
        """A region from the setting's first words, its first sentence as a known fact, and the
        private notes as hidden facts. Directives in the notes can add more: `[[at: Place:location]]`
        for the opening scene, `[[present: Name]]`, `[[hidden: ...]]`, `[[hour: 18]]`."""
        self.calls.append("bootstrap")
        head = request.setting.split(":", 1)[0].strip()
        region = head if ":" in request.setting[:60] and head else "The Setting"
        out = Extraction(entities=[EntityProposal(region, "location")])
        first = request.setting.split(". ")[0].strip().rstrip(".")
        sentence = " ".join(first.split()[:35]) + "."
        out.facts.append(FactProposal(sentence, [region], None, "known"))
        notes = _DIRECTIVE.sub("", request.gm_notes).strip()
        if notes:
            out.facts.append(FactProposal(" ".join(notes.split()[:35]), [region], None, "hidden"))
        known = {region}

        def entity(token: str, default: str) -> str:
            name, kind = _name_kind(token, default)
            if name not in known:
                known.add(name)
                out.entities.append(EntityProposal(name, kind, parent=region if kind == "location" else None))
            return name

        for name, body in _DIRECTIVE.findall(request.gm_notes):
            parts = [p.strip() for p in body.split("|")]
            if name == "at":
                out.location = entity(body, "location")
            elif name == "present":
                out.present = [entity(p, "npc") for p in body.split(",") if p.strip()]
            elif name == "hour" and body.strip().isdigit():
                out.start_hour = int(body.strip())
            elif name in ("fact", "hidden") and len(parts) >= 2:
                subject = entity(parts[0], "npc")
                out.facts.append(FactProposal(parts[1], [subject], None, "known" if name == "fact" else "hidden"))
        return out

    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        self.calls.append("reconcile")
        result = ReconcileResult()
        for item in request.items:
            evidence = item.proposal.evidence
            if evidence.startswith("contradicts:"):
                result.labels.append(Label(item.index, "contradicts", evidence.split(":", 1)[1]))
            else:
                result.labels.append(Label(item.index, "new"))
        return result

    async def expand(self, request: ExpandRequest) -> Extraction:
        self.calls.append("expand")
        ent = request.entity
        out = Extraction()
        for aspect in request.missing[:2]:
            text = f"The {aspect.replace('_', ' ')} of {ent.name} predates the arrival of any traveler."
            out.facts.append(FactProposal(text, [ent.name], aspect, "hidden"))
        if ent.kind == "location" and request.tier == "full" and not ent.name.endswith("Cellar"):
            cellar = f"{ent.name} Cellar"
            out.entities.append(EntityProposal(cellar, "location", parent=ent.name))
            out.facts.append(
                FactProposal(f"The {cellar} is damp and smells of old brine.", [cellar], "interior", "hidden")
            )
        return out
