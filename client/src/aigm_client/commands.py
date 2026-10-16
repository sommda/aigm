"""Slash-command parsing. Anything not starting with "/" is a chat message."""

from dataclasses import dataclass, field

KNOWN = {"new", "save", "load", "saves", "info", "delete", "help", "quit", "reconnect"}


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...] = ()
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def arg(self) -> str | None:
        return self.args[0] if self.args else None


def parse_command(line: str) -> Command | None:
    line = line.strip()
    if not line.startswith("/"):
        return None
    parts = line[1:].split()
    if not parts:
        return Command("unknown")
    name = parts[0].lower()
    args = tuple(p for p in parts[1:] if not p.startswith("--"))
    flags = frozenset(p[2:] for p in parts[1:] if p.startswith("--"))
    return Command(name if name in KNOWN else "unknown", args if name in KNOWN else (name,), flags)
