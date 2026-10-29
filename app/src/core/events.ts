/** Typed events mirroring the SSE events in docs/API.md. Parsing is tolerant: missing fields get defaults and
 * unknown event types become `unknown` (forward compatibility). */

export interface DieRoll {
  value: number;
  kept: boolean;
  values: number[];
}

export interface DiceTerm {
  notation: string;
  count: number;
  sides: number;
  total: number;
  annotation: string | null;
  rolls: DieRoll[];
}

export interface Standing {
  name: string;
  xp: number;
  level: number;
  previousLevel: number;
  classes: [string, number][];
}

export type Json = Record<string, unknown>;

export type GameEvent =
  | { type: "message_start"; messageId: string; sessionId: string; phase: string; rulesetName: string }
  | { type: "thinking"; status: "start" | "delta" | "end"; delta: string; durationMs: number | null }
  | { type: "text"; delta: string }
  | { type: "tool_call"; toolUseId: string; name: string; input: Json }
  | {
      type: "dice_roll";
      toolUseId: string;
      expression: string;
      total: number | null;
      result: string;
      crit: string;
      comment: string | null;
      dice: DiceTerm[];
    }
  | { type: "status"; stage: string; message: string; done: boolean }
  | {
      type: "message_end";
      messageId: string;
      stopReason: string;
      usage: Json;
      phase: string;
      rulesetName: string;
      metrics: Json;
      story: Json | null;
      compendium: Json | null;
    }
  | { type: "phase_change"; previous: string; phase: string }
  | { type: "chapter"; previous: number; chapter: number; title: string }
  | {
      type: "award";
      xpGained: number;
      to: string[];
      everyone: boolean;
      characters: Standing[];
      averageLevel: number;
      reason: string;
    }
  | { type: "error"; code: string; message: string; retryable: boolean }
  | { type: "unknown"; name: string; data: unknown };

const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const num = (v: unknown, d = 0): number => (typeof v === "number" && Number.isFinite(v) ? v : d);
const obj = (v: unknown): Json | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function parseDie(d: Json): DieRoll {
  return { value: num(d.value), kept: d.kept !== false, values: arr(d.values).map((x) => num(x)) };
}

function parseTerm(d: Json): DiceTerm {
  return {
    notation: str(d.notation),
    count: num(d.count),
    sides: num(d.sides),
    total: num(d.total),
    annotation: typeof d.annotation === "string" ? d.annotation : null,
    rolls: arr(d.rolls).flatMap((r) => {
      const o = obj(r);
      return o ? [parseDie(o)] : [];
    }),
  };
}

/** A typed event, or null when `data` is not a JSON object (the event is skipped). */
export function parseEvent(name: string, data: string): GameEvent | null {
  let d: Json | null;
  try {
    d = obj(data ? JSON.parse(data) : {});
  } catch {
    return null;
  }
  if (d === null) return null;
  switch (name) {
    case "message_start":
      return {
        type: "message_start",
        messageId: str(d.message_id),
        sessionId: str(d.session_id),
        phase: str(d.phase),
        rulesetName: str(d.ruleset_name),
      };
    case "thinking": {
      const s = str(d.status, "start");
      return {
        type: "thinking",
        status: s === "delta" || s === "end" ? s : "start",
        delta: str(d.delta),
        durationMs: typeof d.duration_ms === "number" ? d.duration_ms : null,
      };
    }
    case "text":
      return { type: "text", delta: str(d.delta) };
    case "tool_call":
      return { type: "tool_call", toolUseId: str(d.tool_use_id), name: str(d.name), input: obj(d.input) ?? {} };
    case "dice_roll":
      return {
        type: "dice_roll",
        toolUseId: str(d.tool_use_id),
        expression: str(d.expression),
        total: typeof d.total === "number" ? d.total : null,
        result: str(d.result),
        crit: str(d.crit, "none"),
        comment: typeof d.comment === "string" ? d.comment : null,
        dice: arr(d.dice).flatMap((t) => {
          const o = obj(t);
          return o ? [parseTerm(o)] : [];
        }),
      };
    case "status":
      return { type: "status", stage: str(d.stage), message: str(d.message), done: d.done === true };
    case "message_end":
      return {
        type: "message_end",
        messageId: str(d.message_id),
        stopReason: str(d.stop_reason),
        usage: obj(d.usage) ?? {},
        phase: str(d.phase),
        rulesetName: str(d.ruleset_name),
        metrics: obj(d.metrics) ?? {},
        story: obj(d.story),
        compendium: obj(d.compendium),
      };
    case "phase_change":
      return { type: "phase_change", previous: str(d.previous), phase: str(d.phase) };
    case "chapter":
      return { type: "chapter", previous: num(d.previous), chapter: num(d.chapter), title: str(d.title) };
    case "award":
      return {
        type: "award",
        xpGained: num(d.xp_gained),
        to: arr(d.to).map((n) => String(n)),
        everyone: d.everyone === true,
        characters: arr(d.characters).flatMap((c) => {
          const o = obj(c);
          if (!o) return [];
          return [
            {
              name: str(o.name),
              xp: num(o.xp),
              level: num(o.level, 1),
              previousLevel: num(o.previous_level, num(o.level, 1)),
              classes: Object.entries(obj(o.classes) ?? {}).map(([k, v]) => [k, num(v)] as [string, number]),
            },
          ];
        }),
        averageLevel: num(d.average_level, 1),
        reason: str(d.reason),
      };
    case "error":
      return {
        type: "error",
        code: str(d.code, "internal_error"),
        message: str(d.message),
        retryable: d.retryable === true,
      };
    default:
      return { type: "unknown", name, data: d };
  }
}
