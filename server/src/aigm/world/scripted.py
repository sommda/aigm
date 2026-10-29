"""A deterministic curator for `--test` mode and tests: no model, no network.

It reads directives that the (scripted) GM text contains, so a person can drive the whole pipeline
by hand, for example `echo [[fact: Wren:npc | Wren sells news to the Thorn Guild.]]`:

    [[fact: Subject[:kind] | sentence [| Other, Another]]]     a fact the player was told (kind defaults to npc)
    [[hidden: Subject[:kind] | sentence [| Other, ...]]]       a fact implied but not told
    [[contradict: f0002 | Subject | sentence]]                 a fact that clashes with the existing fact f0002
    [[reveal: f0002]]                                          the narration just told the player f0002
    [[at: Place[:kind]]]  /  [[present: A, B]]                 the party moved / who is with them
    [[elapsed: 3]]                                             in-world hours the narration covered
    [[quest: m01 | done | what happened]]  /  [[goal: x]]      a story quest ended / the player learned the goal

A party member's background may hold `[[knows: Subject[:kind] | sentence]]`: the familiarity step records it as a
fact that character knows (a place goes under the first region in the world).

Expansion writes a plain fact for up to two missing aspects, gives a bare location a cellar and every person a lasting
motive."""

import re
import zlib

from aigm.world.curator import (
    BootstrapRequest,
    DigestRequest,
    EntityProposal,
    ExpandRequest,
    ExtractRequest,
    Extraction,
    FactProposal,
    FamiliarityRequest,
    Label,
    LookRequest,
    LookRevision,
    MotiveProposal,
    PlotProposal,
    PlotRequest,
    QuestProposal,
    ChapterProposal,
    EndingProposal,
    ReconcileRequest,
    ReconcileResult,
    ReviseRequest,
    SheetRequest,
)
from aigm.looks import CONTROLLED_TAGS, Look
from aigm.sheets import Section, Sheet

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
                elif name == "quest" and len(parts) == 3:
                    out.quest_reports.append((parts[0], parts[1], parts[2]))
                elif name == "goal":
                    out.goal_revealed = True
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

    async def familiarity(self, request: FamiliarityRequest) -> Extraction:
        """The `[[knows: ...]]` directives in the characters' backgrounds, and nothing else."""
        self.calls.append("familiarity")
        region = next((e.name for e in request.entities if e.kind == "location" and e.parent is None), None)
        out = Extraction()
        known = {e.name for e in request.entities}
        for name, _, background in request.party:
            if request.only and name not in request.only:
                continue
            for body in (m[1] for m in _DIRECTIVE.findall(background) if m[0] == "knows"):
                token, _, text = body.partition("|")
                subject, kind = _name_kind(token, "npc")
                if subject not in known:
                    known.add(subject)
                    out.entities.append(EntityProposal(subject, kind, parent=region if kind == "location" else None))
                if text.strip():
                    out.facts.append(FactProposal(text.strip(), [subject], None, "known", via=[name]))
        return out

    async def sheet(self, request: SheetRequest) -> Sheet:
        """The free text split into sentences under one heading, with hit points read from "HP 12" or "HP 12/15"."""
        self.calls.append("sheet")
        text = " ".join(request.text.split())
        lines = [s.strip() for s in re.split(r"(?<=[.;])\s+", text) if s.strip()][:12] or [text[:200]]
        found = re.search(r"\bHP:?\s*(\d+)(?:\s*/\s*(\d+))?", text, re.IGNORECASE)
        hp = max_hp = None
        if found:
            hp = int(found.group(1))
            max_hp = int(found.group(2) or found.group(1))
        return Sheet(f"{request.name}, level {request.level}", hp, max_hp, [], [Section("Sheet", lines)])

    async def look(self, request: LookRequest) -> dict[int, Look]:
        """A deterministic Look for each character: coloring and features chosen from short lists by the name and the
        place in the batch (so a batch is varied), the ancestry and gender read from the text, and every decided
        detail repeated word for word."""
        self.calls.append("look")
        hair = ("white", "black", "chestnut", "copper", "ash blond", "dark brown", "grey", "auburn", "sandy", "red",
                "silver", "straw yellow")  # fmt: skip
        eyes = ("grey", "brown", "green", "hazel", "pale blue", "amber", "black", "dark blue", "light brown", "violet")
        marks = ("a notched left ear", "a pale scar across the chin", "a crooked nose", "freckles across both cheeks",
                 "a missing front tooth", "a burn scar on the left hand", "a heavy brow", "a tattoo of a swallow",
                 "a split lip", "deep dimples", "a bald crown", "a gold hoop earring")  # fmt: skip
        cloth = ("a patched green cloak", "a leather apron", "a long grey coat", "a faded red tunic",
                 "a dark wool jerkin", "a travel-stained blue robe", "a yellow silk sash", "a fur-collared vest",
                 "a canvas smock", "a plain brown habit", "a studded leather coat", "a black velvet doublet")  # fmt: skip
        out: dict[int, Look] = {}
        for i, sub in enumerate(request.subjects):
            step = i + len(request.existing)  # varied within a batch and across sweeps
            seed = zlib.crc32(sub.name.encode())
            text = " ".join([sub.sheet, sub.background, *sub.facts, *sub.given]).lower()
            ancestry = next((a for a in CONTROLLED_TAGS["ancestry"][:-1] if re.search(rf"\b{a}s?\b", text)), "human")
            if re.search(r"\b(she|her|woman|female)\b", text):
                gender = "feminine"
            elif re.search(r"\b(he|his|man|male)\b", text):
                gender = "masculine"
            else:
                gender = CONTROLLED_TAGS["gender"][(seed + step) % 3]
            build = CONTROLLED_TAGS["build"][(seed + 5 * step) % 6]
            tags = {
                "ancestry": ancestry, "age": "adult", "gender": gender, "build": build,
                "height": CONTROLLED_TAGS["height"][(seed + step) % 3], "hair": hair[(seed + 5 * step) % 12],
                "eyes": eyes[(seed + 3 * step) % 10],
                "clothing": cloth[(seed + 7 * step) % 12], "archetype": "traveller", "expression": "calm",
                "marks": [marks[(seed + 5 * step) % 12]], "carries": ["a worn leather satchel"],
            }  # fmt: skip
            decided = " ".join(f"Also: {g.strip()}" for g in sub.given)[:360]
            body = (
                f"{sub.name} is an adult {ancestry} of {build} build and {tags['height']} stature, standing with an "
                f"easy, upright bearing. {sub.name} has {tags['hair']} hair, {tags['eyes']} eyes and a weathered, "
                f"open face marked by {tags['marks'][0]}. Their clothes are practical and well worn: "
                f"{tags['clothing']} over sturdy boots, with {tags['carries'][0]} slung at one hip. "
                f"The expression is calm and attentive, the posture relaxed but ready, the hands steady and "
                f"capable. A faint smile rests on their lips as they study whoever stands in front of them. {decided}"
            ).strip()
            summary = f"A {build} {ancestry} in {tags['clothing']}, with {tags['hair']} hair and {tags['marks'][0]}."
            out[i] = Look(summary, body, tags)
        return out

    async def revise_looks(self, request: ReviseRequest) -> dict[int, LookRevision]:
        """Reads `[[look: adds|lasting|contradicts | text]]` from the sentences that name a character: `adds` and
        `lasting` work the text into the description and the marks, `contradicts` reports it as the note."""
        self.calls.append("revise")
        out: dict[int, LookRevision] = {}
        for i, sub in enumerate(request.subjects):
            for sentence in sub.narration:
                found = re.search(r"\[\[look:\s*(adds|lasting|contradicts)\s*\|\s*(.*?)\]\]", sentence, re.DOTALL)
                if not found:
                    continue
                verdict, text = found.group(1), found.group(2).strip()
                if verdict == "contradicts":
                    out[i] = LookRevision(verdict, None, text)
                else:
                    look = sub.current.copy()
                    look.description = f"{look.description} {text}"
                    look.tags["marks"] = [*look.tags.get("marks", []), text][:5]
                    out[i] = LookRevision(verdict, look)
                break
        return out

    async def plot(self, request: PlotRequest) -> PlotProposal:
        """A plain plan of the size the length asks for: a chain of quests per chapter, each giving something, ending
        at a goal place that is added under the first region. Quest counts are the low end of the range."""
        self.calls.append("plot")
        region = next((e.name for e in request.entities if e.kind == "location" and e.parent is None), None)
        goal_place = "The Sunken Seal"
        out = PlotProposal(
            goal_title="Break the Sunken Seal",
            goal_summary=f"The {goal_place} holds a binding that the old keepers of the region could not undo.",
            min_strength="Level 5 and the help of the old keepers",
            goal_entities=[goal_place],
            chapters=[
                ChapterProposal("The Open Road", "Learn what is at stake.", request.level),
                ChapterProposal("The Way North", "Gather strength and allies.", request.level),
                ChapterProposal("The Seal", "Face the binding.", request.level + 2),
            ],
            endings=[
                EndingProposal("The Seal Holds", "The party mends the binding."),
                EndingProposal("The Seal Breaks", "The party fails or chooses to let it break."),
            ],
        )
        if region and not request.story_so_far:
            out.entities.append(EntityProposal(goal_place, "location", parent=region))
            out.facts.append(FactProposal(f"The {goal_place} was sealed by the old keepers long ago.", [goal_place, region]))
            out.facts.append(FactProposal(f"Travelers in {region} speak of lights beneath the earth.", [region]))
        scale = {"short": "small", "medium": "medium", "long": "large"}[request.length]
        previous: str | None = None
        for chapter in request.chapters:
            for i in range(request.quests[0]):
                key = f"c{chapter}q{i + 1}"
                out.quests.append(
                    QuestProposal(
                        key, chapter, f"Quest {key}", f"Do what quest {key} asks.", scale, f"a boon from {key}",
                        [previous] if previous else [], True, [goal_place] if region else [],
                    )
                )  # fmt: skip
                previous = key
        return out

    async def digest(self, request: DigestRequest) -> list[str]:
        """The first words of what the player did and of what the GM said, with directives removed."""
        self.calls.append("digest")
        out = []
        for turn in request.turns:
            said = {"PLAYER": "", "GM": ""}
            for para in _DIRECTIVE.sub("", turn.text).split("\n\n"):
                match = _SPEAKER.match(para)
                if match and not said[match.group(1)]:
                    said[match.group(1)] = " ".join(para[match.end() :].split()[:14])
            out.append(f"The player: {said['PLAYER'] or '(nothing)'}. The GM: {said['GM'] or '(nothing)'}")
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
        for aspect in [a for a in request.missing if a != "motives"][:2]:
            text = f"The {aspect.replace('_', ' ')} of {ent.name} predates the arrival of any traveler."
            out.facts.append(FactProposal(text, [ent.name], aspect, "hidden"))
        if "motives" in request.missing:  # a lasting want for every person who steps on stage
            out.motives.append(
                MotiveProposal(
                    ent.name, f"Wants to keep {ent.name}'s place in the world safe from any trouble.", "want", "driven",
                    ["steady coin", "a favor owed"], ["loud demands"], [f"{ent.name} glances at the door."],
                )
            )
        if ent.kind == "location" and request.tier == "full" and not ent.name.endswith("Cellar"):
            cellar = f"{ent.name} Cellar"
            out.entities.append(EntityProposal(cellar, "location", parent=ent.name))
            out.facts.append(
                FactProposal(f"The {cellar} is damp and smells of old brine.", [cellar], "interior", "hidden")
            )
        return out
