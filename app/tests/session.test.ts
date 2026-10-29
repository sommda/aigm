import { parseEvent } from "../src/core/events";
import { ChatSession, metricsLine, storyNote } from "../src/core/session";

const ev = (name: string, data: object) => parseEvent(name, JSON.stringify(data))!;

describe("ChatSession", () => {
  test("a turn: user block, streamed text, end", () => {
    const s = new ChatSession();
    s.beginTurn("I knock");
    expect(s.busy && s.dirty).toBe(true);
    s.apply(ev("message_start", { phase: "adventure", ruleset_name: "5.5e" }));
    s.apply(ev("text", { delta: "The door " }));
    s.apply(ev("text", { delta: "opens." }));
    expect(s.blocks.map((b) => b.kind)).toEqual(["user", "markdown"]);
    expect((s.blocks[1] as { raw: string }).raw).toBe("The door opens.");
    s.apply(ev("message_end", {}));
    expect(s.busy).toBe(false);
    expect((s.blocks[1] as { final: boolean }).final).toBe(true);
    expect(s.phase).toBe("adventure");
    expect(s.rulesetName).toBe("5.5e");
  });

  test("text after a dice roll or thinking phase starts a new block", () => {
    const s = new ChatSession();
    s.beginTurn("x");
    s.apply(ev("text", { delta: "a" }));
    s.apply(ev("dice_roll", { expression: "1d20", total: 5 }));
    s.apply(ev("text", { delta: "b" }));
    s.apply(ev("thinking", { status: "start" }));
    expect(s.thinking).toBe(true);
    s.apply(ev("thinking", { status: "delta", delta: "hmm" }));
    s.apply(ev("thinking", { status: "end" }));
    s.apply(ev("text", { delta: "c" }));
    expect(s.blocks.map((b) => b.kind)).toEqual(["user", "markdown", "dice", "markdown", "reasoning", "markdown"]);
  });

  test("status shows and clears; errors end the turn", () => {
    const s = new ChatSession();
    s.beginTurn("x");
    s.apply(ev("status", { stage: "world", message: "Preparing the world..." }));
    expect(s.status).toBe("Preparing the world...");
    s.apply(ev("status", { done: true }));
    expect(s.status).toBe("");
    s.apply(ev("error", { message: "boom" }));
    expect(s.busy).toBe(false);
    expect(s.blocks[s.blocks.length - 1]).toMatchObject({ kind: "system", tone: "red" });
  });

  test("phase change, chapters and awards print banners; a chapter is announced once", () => {
    const s = new ChatSession();
    s.apply(ev("phase_change", { phase: "adventure" }));
    s.apply(ev("chapter", { previous: 1, chapter: 2, title: "The road" }));
    s.apply(ev("message_end", { story: { chapter: 2, chapter_title: "The road", length: "short" } }));
    s.apply(ev("award", { xp_gained: 50, everyone: true, characters: [{ name: "Kit", level: 2, previous_level: 1, classes: { Rogue: 2 } }] }));
    const texts = s.blocks.map((b) => (b.kind === "system" ? b.text : ""));
    expect(texts.filter((t) => t.startsWith("Chapter 2"))).toHaveLength(1);
    expect(texts).toContain("Session 0 is over. The adventure begins!");
    expect(texts).toContain("  +50 XP to the party");
    expect(texts).toContain("  Kit reaches level 2! (Rogue 2)");
    expect(s.storyLabel).toBe("Ch 2/3: The road");
  });

  test("unread counts come from message_end", () => {
    const s = new ChatSession();
    s.apply(ev("message_end", { compendium: { new: 2, updated: 1 } }));
    expect(s.compendiumUnread).toBe(3);
  });

  test("interrupted turns are marked", () => {
    const s = new ChatSession();
    s.beginTurn("x");
    s.interrupted();
    expect(s.busy).toBe(false);
    expect(s.blocks[s.blocks.length - 1]).toMatchObject({ tone: "yellow" });
  });

  test("history rebuilds the transcript", () => {
    const s = new ChatSession();
    s.loadHistory({
      phase: "adventure",
      messages: [
        { role: "user", content: [{ type: "text", text: "[System: Session 0 is complete]" }] },
        { role: "user", content: [{ type: "text", text: "I look" }] },
        {
          role: "assistant",
          content: [
            { type: "text", text: "You see a room." },
            { type: "tool_use", id: "t1", name: "roll_dice", input: { expression: "1d20", narration: "You search." } },
          ],
        },
        { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "1d20 = 12" }] },
        { role: "assistant", content: [{ type: "thinking", thinking: "hmm" }] },
      ],
    });
    expect(s.blocks.map((b) => b.kind)).toEqual(["system", "user", "markdown", "markdown", "dice"]);
    expect(s.dirty).toBe(false);
  });

  test("notifications can be coalesced", async () => {
    const s = new ChatSession(10);
    let n = 0;
    s.subscribe(() => n++);
    s.beginTurn("x");
    for (let i = 0; i < 20; i++) s.apply(ev("text", { delta: "a" }));
    expect(n).toBe(0);
    await new Promise((r) => setTimeout(r, 30));
    expect(n).toBe(1);
    expect(s.version).toBeGreaterThan(1);
  });

  test("helpers", () => {
    expect(storyNote({ length: "short", chapter: 2, chapter_title: "The road" })).toBe("short story, chapter 2: The road");
    expect(storyNote(null)).toBe("");
    expect(metricsLine({ first_text_ms: 1500, total_ms: 8000, input_tokens: 69000, model_calls: 2 })).toContain("first text 1.5s");
  });
});
