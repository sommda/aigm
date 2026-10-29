/** Chat session view-model: applies server events to the transcript. UI-free. A port of the terminal client's
 * `session.py`, so both clients treat the same events the same way. */

import {
  Block, MarkdownBlock, ReasoningBlock, Tone, awardLines, diceBlock, historyToBlocks, markdownBlock, reasoningBlock,
  systemBlock, userBlock,
} from "./blocks";
import { GameEvent, Json } from "./events";

export const PHASE_LABELS: Record<string, string> = { session_zero: "Session 0", adventure: "Adventure" };
const INTRO: Record<string, string> = {
  session_zero:
    "Welcome! This is Session 0, where we choose the rules (D&D 5.5e by default, or any older D&D or Pathfinder edition) " +
    "and set up your world and your party. Say hello to begin. Type /help for commands.",
  adventure: "Welcome back. Describe what you do. Type /help for commands.",
};

export const introText = (phase: string): string =>
  INTRO[phase] ?? "Welcome, adventurer. Describe what you do. Type /help for commands.";

const seconds = (ms: unknown) => (typeof ms === "number" ? `${(ms / 1000).toFixed(1)}s` : "-");
const count = (n: unknown) =>
  typeof n === "number" ? (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)) : "-";

/** One dim line for a finished turn (debug servers only): how long it took and what it cost. */
export function metricsLine(m: Json): string {
  return (
    `first text ${seconds(m.first_text_ms)} · total ${seconds(m.total_ms)} · ` +
    `in ${count(m.input_tokens)} (cached ${count(m.cache_read_tokens)}, written ${count(m.cache_write_tokens)}) · ` +
    `out ${count(m.output_tokens)} · ${m.model_calls ?? "?"} call(s)`
  );
}

/** "short story, chapter 2: The road" for a saved or live story game; "" for an endless game. */
export function storyNote(story: Json | null | undefined): string {
  if (!story) return "";
  const length = String(story.length ?? "");
  if (story.ended) return `${length} story, finished`.trim();
  const title = story.chapter_title ? String(story.chapter_title) : "";
  return `${length} story, chapter ${story.chapter ?? "?"}` + (title ? `: ${title}` : "");
}

type Listener = () => void;

export class ChatSession {
  blocks: Block[] = [];
  busy = false; // a chat turn is in flight
  thinking = false;
  status = ""; // a long wait the server is reporting ("Preparing the world..."); "" when none
  gameName: string | null = null;
  phase = ""; // "session_zero" | "adventure" | "" (unknown)
  rulesetName = "";
  story: Json | null = null;
  dirty = false; // unsaved changes since the last save/load/new
  compendiumUnread = 0;
  showMetrics = false; // a debug server: print each turn's timings and token use
  /** Bumped on every visible change; the UI re-renders when it changes. */
  version = 0;

  private text: MarkdownBlock | null = null;
  private reasoning: ReasoningBlock | null = null;
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  /** Milliseconds to coalesce notifications by (streaming deltas arrive far faster than a screen can draw). */
  constructor(private throttleMs = 0) {}

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = (): number => this.version;

  private touch(): void {
    this.version++;
    if (this.throttleMs <= 0) return this.emit();
    if (this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null;
        this.emit();
      }, this.throttleMs);
    }
  }
  private emit(): void {
    for (const fn of [...this.listeners]) fn();
  }

  // ---- derived -----------------------------------------------------------------------------

  get phaseLabel(): string {
    return PHASE_LABELS[this.phase] ?? "";
  }

  /** "Ch 2/3: The road" for a story game, "Story over" once it has ended, "" for an endless game. */
  get storyLabel(): string {
    const s = this.story;
    if (!s) return "";
    if (s.ended) return "Story over";
    const title = s.chapter_title ? String(s.chapter_title) : "";
    return `Ch ${s.chapter ?? "?"}/3` + (title ? `: ${title}` : "");
  }

  get canInput(): boolean {
    return !this.busy;
  }

  // ---- turn lifecycle ----------------------------------------------------------------------

  beginTurn(userText: string): void {
    this.blocks.push(userBlock(userText));
    this.busy = true;
    this.dirty = true;
    this.text = this.reasoning = null;
    this.touch();
  }

  apply(event: GameEvent): void {
    switch (event.type) {
      case "text":
        if (this.text === null) {
          this.text = markdownBlock();
          this.blocks.push(this.text);
        }
        this.text.raw += event.delta;
        this.text.version++;
        break;
      case "thinking":
        if (event.status === "start") {
          this.thinking = true;
          this.text = this.reasoning = null; // text before and after a thinking phase are separate segments
        } else if (event.status === "delta") {
          if (this.reasoning === null) {
            this.reasoning = reasoningBlock();
            this.blocks.push(this.reasoning);
          }
          this.reasoning.text += event.delta;
          this.reasoning.version++;
        } else {
          this.thinking = false;
          this.reasoning = null;
        }
        break;
      case "status":
        this.status = event.done ? "" : event.message;
        break;
      case "tool_call":
        this.text = null;
        break;
      case "dice_roll":
        this.text = null;
        this.blocks.push(diceBlock(event));
        break;
      case "message_start":
        if (event.phase) {
          this.phase = event.phase;
          this.rulesetName = event.rulesetName || this.rulesetName;
        }
        break;
      case "phase_change":
        this.phase = event.phase;
        this.text = this.reasoning = null;
        if (event.phase === "adventure") this.addSystem("Session 0 is over. The adventure begins!", "bold-green");
        break;
      case "chapter":
        this.announceChapter(event.chapter, event.title);
        break;
      case "award": {
        this.text = null;
        const levelled = event.characters
          .filter((c) => c.level > c.previousLevel)
          .map((c): [string, number, string] => [c.name, c.level, c.classes.map(([k, v]) => `${k} ${v}`).join(", ")]);
        for (const line of awardLines(event.xpGained, event.to, event.everyone, levelled, event.reason))
          this.addSystem(line, line.includes("reaches level") ? "bold-green" : "green");
        break;
      }
      case "message_end":
        if (event.compendium !== null) this.setUnread(event.compendium);
        if (event.phase) this.phase = event.phase;
        this.rulesetName = event.rulesetName || this.rulesetName;
        if (event.story !== null) {
          // a chapter that changed between turns shows up only here
          if (this.story && event.story.chapter !== this.story.chapter)
            this.announceChapter(Number(event.story.chapter ?? 0), String(event.story.chapter_title ?? ""));
          this.story = event.story;
        }
        this.finishTurn();
        if (this.showMetrics && Object.keys(event.metrics).length) this.addSystem(metricsLine(event.metrics));
        break;
      case "error":
        this.finishTurn();
        this.addSystem(`Error: ${event.message || "unknown error"} (this turn was discarded; send it again)`, "red");
        break;
      default:
        break; // tool results, unknown events: nothing to show
    }
    this.touch();
  }

  /** Take the unread totals of a server reply ({"new": n, "updated": m}); anything else means none. */
  setUnread(counts: Json | null | undefined): void {
    const c = counts ?? {};
    const n = (k: string) => (typeof c[k] === "number" ? (c[k] as number) : 0);
    const total = n("new") + n("updated");
    if (total !== this.compendiumUnread) {
      this.compendiumUnread = total;
      this.touch();
    }
  }

  /** One banner per chapter: the event and the next message_end both report the same change. */
  private announceChapter(chapter: number, title: string): void {
    if (this.story && this.story.chapter === chapter) return;
    this.story = { ...(this.story ?? {}), chapter, chapter_title: title, ended: chapter > 3 };
    if (chapter > 3) this.addSystem("The story has ended. You can keep playing in this world.", "bold-green");
    else this.addSystem(title ? `Chapter ${chapter}: ${title}` : `Chapter ${chapter}`, "bold-green");
  }

  private finishTurn(): void {
    this.busy = false;
    this.thinking = false;
    this.status = "";
    this.text = this.reasoning = null;
    for (const b of this.blocks) {
      if (b.kind === "markdown" && !b.final) {
        b.final = true;
        b.version++;
      }
    }
  }

  /** A request failed before or outside the event stream. */
  fail(message: string): void {
    this.finishTurn();
    this.addSystem(`Error: ${message}`, "red");
  }

  interrupted(): void {
    this.finishTurn();
    this.addSystem("[interrupted - turn discarded; send it again]", "yellow");
  }

  // ---- other content -----------------------------------------------------------------------

  addSystem(text: string, tone: Tone = "dim"): void {
    for (const line of text.split("\n")) this.blocks.push(systemBlock(line, tone));
    this.touch();
  }

  /** Replace the transcript with a server history. */
  loadHistory(state: Json): void {
    this.phase = String(state.phase ?? "");
    this.rulesetName = String(state.ruleset_name ?? "");
    this.story = (state.story as Json | undefined) ?? null;
    this.setUnread((state.compendium as Json | undefined) ?? null);
    this.blocks = historyToBlocks((state.messages as Json[]) ?? []);
    this.busy = this.thinking = false;
    this.status = "";
    this.text = this.reasoning = null;
    this.dirty = false;
    this.touch();
  }

  newGame(phase = "session_zero", rulesetName = ""): void {
    this.phase = phase;
    this.rulesetName = rulesetName;
    this.story = null;
    this.setUnread(null);
    this.blocks = [];
    this.busy = this.thinking = false;
    this.status = "";
    this.text = this.reasoning = null;
    this.gameName = null;
    this.dirty = false;
    this.touch();
  }

  markSaved(name: string): void {
    this.gameName = name;
    this.dirty = false;
    this.touch();
  }
  markLoaded(name: string): void {
    this.markSaved(name);
  }

  get hasGame(): boolean {
    return this.dirty || this.blocks.some((b) => b.kind === "user" || b.kind === "markdown");
  }
}
