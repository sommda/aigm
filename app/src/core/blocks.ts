/** Transcript blocks, and the mapping from a server history (GET /chat/history) to blocks. */

import { GameEvent, Json } from "./events";

export type DiceEvent = Extract<GameEvent, { type: "dice_roll" }>;

export type Tone = "dim" | "green" | "bold-green" | "red" | "yellow";

interface Base {
  id: number;
  version: number;
}
export interface UserBlock extends Base {
  kind: "user";
  text: string;
}
export interface MarkdownBlock extends Base {
  kind: "markdown";
  raw: string;
  final: boolean;
}
export interface ReasoningBlock extends Base {
  kind: "reasoning";
  text: string;
}
export interface SystemBlock extends Base {
  kind: "system";
  text: string;
  tone: Tone;
}
export interface DiceBlock extends Base {
  kind: "dice";
  event: DiceEvent;
}
export type Block = UserBlock | MarkdownBlock | ReasoningBlock | SystemBlock | DiceBlock;

let nextId = 1;
const base = () => ({ id: nextId++, version: 0 });

export const userBlock = (text: string): UserBlock => ({ ...base(), kind: "user", text });
export const markdownBlock = (raw = "", final = false): MarkdownBlock => ({ ...base(), kind: "markdown", raw, final });
export const reasoningBlock = (text = ""): ReasoningBlock => ({ ...base(), kind: "reasoning", text });
export const systemBlock = (text: string, tone: Tone = "dim"): SystemBlock => ({ ...base(), kind: "system", text, tone });
export const diceBlock = (event: DiceEvent): DiceBlock => ({ ...base(), kind: "dice", event });

export function emptyDice(over: Partial<DiceEvent>): DiceEvent {
  return {
    type: "dice_roll",
    toolUseId: "",
    expression: "",
    total: null,
    result: "",
    crit: "none",
    comment: null,
    dice: [],
    ...over,
  };
}

/** What the player is told when the party earns something: the XP line, then one line per character who levelled
 * (name, overall level, a note such as "Paladin 2, Rogue 1"). */
export function awardLines(
  xpGained: number,
  to: string[],
  everyone: boolean,
  levelled: [string, number, string][],
  reason: string,
): string[] {
  const lines: string[] = [];
  if (xpGained) {
    const who = everyone ? "the party" : to.join(", ") || "the party";
    lines.push(`  +${xpGained} XP ${!everyone && to.length > 1 ? "each to " : "to "}${who}`);
  }
  for (const [name, level, note] of levelled) lines.push(`  ${name} reaches level ${level}!${note ? ` (${note})` : ""}`);
  if (lines.length && reason) lines[0] += ` for ${reason}`;
  return lines.length ? lines : [reason ? `  Awarded for ${reason}` : "  Awarded"];
}

/** Drop d20's markdown emphasis (**bold**, ~~struck~~, `code`) for plain display. */
export function stripMarkup(s: string): string {
  return s.replace(/\*\*|~~|`/g, "");
}

interface HistoryBlock {
  type?: string;
  text?: string;
  name?: string;
  id?: string;
  input?: Json;
  tool_use_id?: string;
  is_error?: boolean;
  content?: unknown;
}

/** Map an Anthropic-format history to display blocks (docs/CLIENT.md, "Rebuilding the transcript"). */
export function historyToBlocks(messages: Json[]): Block[] {
  const blocks: Block[] = [];
  const rollInputs = new Map<string, string>();
  for (const msg of messages) {
    const raw = msg.content;
    const content: HistoryBlock[] = typeof raw === "string" ? [{ type: "text", text: raw }] : ((raw as HistoryBlock[]) ?? []);
    if (msg.role === "user") {
      const texts = content.filter((b) => b.type === "text").map((b) => b.text ?? "");
      if (texts.length) {
        const text = texts.join("\n");
        if (text.startsWith("[System:")) {
          // a note the server inserted, not something the player typed
          blocks.push(systemBlock(text.replace(/^\[+|\]+$/g, "").replace(/^System: /, ""), "dim"));
        } else blocks.push(userBlock(text));
      }
      for (const b of content) {
        if (b.type !== "tool_result") continue;
        const expr = rollInputs.get(b.tool_use_id ?? "") ?? "";
        if (b.is_error) blocks.push(systemBlock(`  (roll failed: ${expr})`, "dim"));
        else {
          let result = b.content ?? "";
          if (Array.isArray(result)) result = result.map((p: { text?: string }) => p.text ?? "").join("");
          blocks.push(diceBlock(emptyDice({ expression: expr, result: String(result) })));
        }
      }
    } else {
      for (const b of content) {
        if (b.type === "text" && (b.text ?? "").trim()) blocks.push(markdownBlock(b.text as string, true));
        else if (b.type === "tool_use" && b.name === "award") {
          const given = (b.input ?? {}) as Json;
          const xp = typeof given.xp === "number" ? given.xp : 0;
          const who = Array.isArray(given.who) ? given.who.filter((n): n is string => typeof n === "string") : [];
          const ups: [string, number, string][] = (Array.isArray(given.level_up) ? given.level_up : [])
            .filter((u): u is Json => !!u && typeof u === "object")
            .map((u) => [
              String(u.who ?? ""),
              typeof u.level === "number" ? u.level : 0,
              u.class && u.class_level ? `${u.class} ${u.class_level}` : "",
            ]);
          for (const line of awardLines(xp, who, who.length === 0, ups, String(given.reason ?? "").trim()))
            blocks.push(systemBlock(line, "green"));
        } else if (b.type === "tool_use" && b.name === "roll_dice") {
          const given = (b.input ?? {}) as Json;
          rollInputs.set(b.id ?? "", String(given.expression ?? ""));
          const narration = String(given.narration ?? "").trim();
          if (narration) blocks.push(markdownBlock(narration, true)); // shown as story text just before the dice
        }
      }
    }
  }
  return blocks;
}
