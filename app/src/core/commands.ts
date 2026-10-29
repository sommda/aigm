/** Slash-command parsing. Anything not starting with "/" is a chat message. */

const KNOWN = new Set([
  "new", "save", "load", "saves", "info", "delete", "help", "quit", "reconnect",
  "context", "thinking", "story", "compendium", "status", "sheet",
]);
const ALIASES: Record<string, string> = { journal: "compendium", c: "compendium", s: "status", character: "sheet" };

export interface Command {
  name: string;
  args: string[];
  flags: Set<string>;
  arg: string | undefined;
}

export function parseCommand(line: string): Command | null {
  const text = line.trim();
  if (!text.startsWith("/")) return null;
  const parts = text.slice(1).split(/\s+/).filter(Boolean);
  if (!parts.length) return { name: "unknown", args: [], flags: new Set(), arg: undefined };
  const lower = parts[0].toLowerCase();
  const name = ALIASES[lower] ?? lower;
  const known = KNOWN.has(name);
  const args = known ? parts.slice(1).filter((p) => !p.startsWith("--")) : [name];
  const flags = new Set(parts.slice(1).filter((p) => p.startsWith("--")).map((p) => p.slice(2)));
  return { name: known ? name : "unknown", args, flags, arg: args[0] };
}

export const NAME_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** `game-YYYYMMDD-HHMM` for a game that was never saved. */
export function suggestName(now: Date = new Date()): string {
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `game-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}`;
}
