"""Prompt text lives in Markdown files next to this module, not in Python code.

    prompts/system/common/*.md        system prompt parts used in every mode
    prompts/system/<phase>/*.md       parts for one phase: session_zero or adventure
    prompts/templates/*.md            fragments filled in with game state (the campaign record)
    prompts/tools/*.md                one tool description per file (<tool name>.md)

A phase's system prompt is the common parts followed by that phase's parts, each in filename
order (01_..., 02_...).

To iterate without editing the package, point `AIGM_PROMPT_DIR` at a directory with the
same layout. Files there replace packaged files of the same name, and extra files are
added (system parts still sort by filename). HTML comments (<!-- ... -->) are stripped, so
prompt files can carry notes to their authors.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aigm.session.state import Phase

PACKAGED_DIR = Path(__file__).parent
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ASPECT_LINE = re.compile(r"^- (\w+): (.+)$")


def _clean(text: str) -> str:
    return _COMMENT.sub("", text).strip()


@dataclass(frozen=True)
class PromptPart:
    """One piece of a prompt and where it came from (a path under prompts/, e.g. system/common/01_role.md)."""

    source: str
    text: str


class PromptLibrary:
    def __init__(self, override_dir: Path | str | None = None) -> None:
        self.dirs = [Path(override_dir)] if override_dir else []
        self.dirs.append(PACKAGED_DIR)  # earlier directories win

    def _files(self, subdir: str) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for base in reversed(self.dirs):  # packaged first, then overrides replace by name
            folder = base / subdir
            if folder.is_dir():
                for path in folder.glob("*.md"):
                    found[path.name] = path
        return found

    def _parts(self, subdir: str) -> list[PromptPart]:
        """The non-empty files of a folder in filename order (an override replaces the packaged file)."""
        files = self._files(subdir)
        parts = [PromptPart(f"{subdir}/{name}", _clean(files[name].read_text(encoding="utf-8"))) for name in sorted(files)]
        return [p for p in parts if p.text]

    def system_parts(self, phase: Phase | str) -> list[PromptPart]:
        """The pieces of a phase's system prompt in order: the common files, then the phase's files."""
        phase = Phase(phase)
        common = self._parts("system/common")
        own = self._parts(f"system/{phase.value}")
        if not own:
            raise ValueError(f"The {phase.value} system prompt is empty: no prompts/system/{phase.value}/*.md files found")
        return [*common, *own]

    def system_prompt(self, phase: Phase | str) -> str:
        """The base system prompt for a phase (without the campaign record)."""
        return "\n\n".join(part.text for part in self.system_parts(phase))

    def _template(self, name: str) -> str:
        path = self._files("templates").get(f"{name}.md")
        if path is None:
            raise ValueError(f"No prompt file prompts/templates/{name}.md")
        return _clean(path.read_text(encoding="utf-8"))

    def campaign_record(self, campaign: dict[str, Any]) -> str:
        """The GM's written record of Session 0, which becomes the first GM entry in the adventure."""
        party = campaign.get("party")
        members = party if isinstance(party, list) else []
        member_template = self._template("party_member")
        rendered = [
            self._fill(
                member_template,
                {
                    "name": str(m.get("name", "")),
                    "sheet": str(m.get("sheet", "")).strip(),
                },
            )
            for m in members
            if isinstance(m, dict)
        ]
        return self._fill(
            self._template("campaign_record"),
            {
                "setting": str(campaign.get("setting", "")).strip(),
                "opening": str(campaign.get("opening", "")).strip(),
                "level": str(campaign.get("level", "?")),
                "party_size": str(len(rendered)),
                "party": "\n\n".join(rendered),
            },
        )

    def gm_notes_section(self, campaign: dict[str, Any] | None) -> str:
        """The private GM notes for the adventure system prompt, or "" if there are none."""
        notes = str((campaign or {}).get("gm_notes") or "").strip()
        return self._fill(self._template("gm_notes"), {"gm_notes": notes}) if notes else ""

    def session_zero_done_note(self) -> str:
        return self._template("session_zero_done")

    def begin_cue(self) -> str:
        return self._template("begin_cue")

    @staticmethod
    def _fill(template: str, values: dict[str, str]) -> str:
        # one pass, so text inside a value is never treated as a placeholder
        return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template).strip()

    def world_prompt(self, name: str) -> str:
        """A prompt for the world curator (prompts/world/<name>.md)."""
        path = self._files("world").get(f"{name}.md")
        if path is None:
            raise ValueError(f"No prompt file prompts/world/{name}.md")
        return _clean(path.read_text(encoding="utf-8"))

    def aspect_guides(self) -> dict[str, dict[str, str]]:
        """What each checklist aspect means, per entity kind (prompts/world/aspects/<kind>.md)."""
        guides: dict[str, dict[str, str]] = {}
        for name, path in self._files("world/aspects").items():
            entries = {}
            for line in _clean(path.read_text(encoding="utf-8")).splitlines():
                match = _ASPECT_LINE.match(line.strip())
                if match:
                    entries[match.group(1)] = match.group(2).strip()
            guides[name.removesuffix(".md")] = entries
        return guides

    def tool_description(self, tool_name: str) -> str:
        path = self._files("tools").get(f"{tool_name}.md")
        if path is None:
            raise ValueError(f"No prompt file prompts/tools/{tool_name}.md for tool {tool_name!r}")
        return _clean(path.read_text(encoding="utf-8"))
