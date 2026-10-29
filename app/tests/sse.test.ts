import { LineSplitter, SSEDecoder } from "../src/core/sse";
import { parseEvent } from "../src/core/events";

describe("SSEDecoder", () => {
  test("a message is complete at the blank line", () => {
    const d = new SSEDecoder();
    expect(d.decode("event: text")).toBeNull();
    expect(d.decode('data: {"delta":"hi"}')).toBeNull();
    expect(d.decode("")).toEqual({ event: "text", data: '{"delta":"hi"}' });
  });
  test("comments and stray blank lines are ignored", () => {
    const d = new SSEDecoder();
    expect(d.decode(": ping")).toBeNull();
    expect(d.decode("")).toBeNull();
  });
  test("multi-line data is joined", () => {
    const d = new SSEDecoder();
    d.decode("data: a");
    d.decode("data: b");
    expect(d.decode("")).toEqual({ event: "message", data: "a\nb" });
  });
});

describe("LineSplitter", () => {
  test("lines split across chunks", () => {
    const s = new LineSplitter();
    expect(s.push("event: te")).toEqual([]);
    expect(s.push("xt\ndata: x\n\nev")).toEqual(["event: text", "data: x", ""]);
    expect(s.flush()).toEqual(["ev"]);
  });
  test("CRLF split between chunks", () => {
    const s = new LineSplitter();
    expect(s.push("a\r")).toEqual([]);
    expect(s.push("\nb\r\n")).toEqual(["a", "b"]);
  });
});

describe("parseEvent", () => {
  test("typed events with defaults", () => {
    expect(parseEvent("text", '{"delta":"x"}')).toEqual({ type: "text", delta: "x" });
    expect(parseEvent("message_start", "{}")).toMatchObject({ type: "message_start", phase: "" });
    expect(parseEvent("thinking", '{"status":"delta","delta":"hm"}')).toMatchObject({ status: "delta", delta: "hm" });
  });
  test("dice roll", () => {
    const e = parseEvent(
      "dice_roll",
      JSON.stringify({ expression: "1d20+5", total: 17, crit: "none", dice: [{ notation: "1d20", rolls: [{ value: 12 }] }] }),
    );
    expect(e).toMatchObject({ type: "dice_roll", total: 17 });
    expect((e as { dice: { rolls: { value: number }[] }[] }).dice[0].rolls[0].value).toBe(12);
  });
  test("unknown events and bad data", () => {
    expect(parseEvent("zzz", '{"a":1}')).toMatchObject({ type: "unknown", name: "zzz" });
    expect(parseEvent("text", "not json")).toBeNull();
    expect(parseEvent("text", "[1]")).toBeNull();
  });
  test("award", () => {
    const e = parseEvent("award", JSON.stringify({ xp_gained: 50, everyone: true, characters: [{ name: "Kit", level: 2, previous_level: 1, classes: { Rogue: 2 } }] }));
    expect(e).toMatchObject({ type: "award", xpGained: 50, everyone: true });
  });
});
