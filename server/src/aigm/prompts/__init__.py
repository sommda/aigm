"""Prompt text lives in Markdown files next to this module, not in Python code.

    prompts/system/*.md   system prompt parts, joined in filename order (01_..., 02_...)
    prompts/tools/*.md    one tool description per file (<tool name>.md)

To iterate without editing the package, point `AIGM_PROMPT_DIR` at a directory with the
same layout. Files there replace packaged files of the same name, and extra files are
added (system parts still sort by filename). HTML comments (<!-- ... -->) are stripped, so
prompt files can carry notes to their authors.
"""

import re
from pathlib import Path

PACKAGED_DIR = Path(__file__).parent
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _clean(text: str) -> str:
    return _COMMENT.sub("", text).strip()


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

    def system_prompt(self) -> str:
        files = self._files("system")
        parts = [_clean(files[name].read_text(encoding="utf-8")) for name in sorted(files)]
        prompt = "\n\n".join(p for p in parts if p)
        if not prompt:
            raise ValueError("The system prompt is empty: no prompts/system/*.md files found")
        return prompt

    def tool_description(self, tool_name: str) -> str:
        path = self._files("tools").get(f"{tool_name}.md")
        if path is None:
            raise ValueError(f"No prompt file prompts/tools/{tool_name}.md for tool {tool_name!r}")
        return _clean(path.read_text(encoding="utf-8"))
