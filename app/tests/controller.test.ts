import { GameController, Prompter } from "../src/core/controller";
import { ChatSession } from "../src/core/session";
import { FakeTransport, apiWith, sse, turn } from "./helpers";

class FakePrompter implements Prompter {
  confirms: boolean[] = [];
  saveName: string | null = "mygame";
  loadName: string | null = "old";
  newChoice: "save" | "discard" | null = "discard";
  asked: string[] = [];
  panels: unknown[] = [];
  async confirm(message: string) {
    this.asked.push(message);
    return this.confirms.shift() ?? true;
  }
  async chooseSave() {
    return this.saveName;
  }
  async chooseLoad() {
    return this.loadName;
  }
  async chooseNew() {
    return this.newChoice;
  }
  openPanel(panel: string, where?: object) {
    this.panels.push([panel, where]);
  }
}

const HEALTH = { status: 200, body: { debug: true, compendium: true, status: true, thinking: true } };
const EMPTY = { status: 200, body: { messages: [], phase: "session_zero", ruleset_name: "5.5e" } };

function setup(routes: Record<string, (body?: unknown) => { status: number; body: unknown }> = {}) {
  const t = new FakeTransport((method, url, body) => {
    const path = url.replace("http://x", "").split("?")[0];
    const key = `${method} ${path}`;
    if (routes[key]) return routes[key](body);
    if (path === "/health") return HEALTH;
    if (path === "/chat/history") return EMPTY;
    return { status: 200, body: {} };
  });
  const prompter = new FakePrompter();
  const c = new GameController(apiWith(t), new ChatSession(), prompter);
  return { t, c, prompter, s: c.session };
}

const texts = (s: ChatSession) => s.blocks.map((b) => (b.kind === "system" ? b.text : b.kind));

describe("startup", () => {
  test("reads health and shows the intro for an empty game", async () => {
    const { c, s } = setup();
    await c.startup();
    expect(c.connected && c.debugServer && c.hasCompendium && c.hasStatus).toBe(true);
    expect(s.showMetrics).toBe(true);
    expect(s.phase).toBe("session_zero");
    expect(s.dirty).toBe(false);
    expect(texts(s)[0]).toMatch(/Welcome! This is Session 0/);
  });
  test("an unreachable server is explained", async () => {
    const { c, s, t } = setup();
    t.handler = () => {
      throw new Error("refused");
    };
    await c.startup();
    expect(c.connected).toBe(false);
    expect(texts(s)[0]).toMatch(/Cannot reach server.*\nStart the server|Cannot reach server/);
  });
  test("a game in progress starts dirty, with its transcript", async () => {
    const { c, s } = setup({
      "GET /chat/history": () => ({ status: 200, body: { phase: "adventure", messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }] } }),
    });
    await c.startup();
    expect(s.dirty).toBe(true);
    expect(s.blocks[0]).toMatchObject({ kind: "user", text: "hi" });
  });
});

describe("a turn", () => {
  test("plain text goes to /chat and the reply streams in", async () => {
    const { c, t, s } = setup();
    t.streamBody = turn("Hello, traveller.");
    await c.submit("hello");
    expect(s.blocks.map((b) => b.kind)).toEqual(["user", "markdown"]);
    expect(s.busy).toBe(false);
  });
  test("a rejected turn is reported", async () => {
    const { c, t, s } = setup();
    t.streamStatus = 409;
    t.streamBody = JSON.stringify({ error: { code: "conflict", message: "x" } });
    await c.submit("hello");
    expect(texts(s).pop()).toMatch(/already in progress/);
    expect(s.busy).toBe(false);
  });
  test("cancelling marks the turn as interrupted", async () => {
    const { c, t, s } = setup();
    t.streamBody = sse(["message_start", {}], ["text", { delta: "a reply that never ends" }]);
    t.hang = true;
    const run = c.submit("go");
    await new Promise((r) => setTimeout(r, 5));
    c.cancelTurn();
    await run;
    expect(texts(s).pop()).toMatch(/interrupted/);
    expect(s.busy).toBe(false);
  });
  test("input is ignored while a turn is in flight", async () => {
    const { c, s, t } = setup();
    s.busy = true;
    await c.submit("hello");
    expect(t.calls.filter((x) => x.url.endsWith("/chat"))).toHaveLength(0);
  });
});

describe("save, load, new", () => {
  test("save asks for a name, then marks the game saved", async () => {
    const { c, s } = setup({ "PUT /history/mygame/save": () => ({ status: 200, body: { message_count: 4 } }) });
    expect(await c.saveFlow(null)).toBe(true);
    expect(s.gameName).toBe("mygame");
    expect(s.dirty).toBe(false);
    expect(texts(s).pop()).toBe("Saved as 'mygame' (4 messages).");
  });
  test("saving over an existing name asks, then overwrites", async () => {
    let first = true;
    const { c, t } = setup({
      "PUT /history/mygame/save": () => {
        if (first) {
          first = false;
          return { status: 409, body: { error: { code: "already_exists", message: "exists" } } };
        }
        return { status: 200, body: { message_count: 1 } };
      },
    });
    expect(await c.saveFlow("mygame")).toBe(true);
    expect(t.calls.map((x) => x.url)).toContain("http://x/history/mygame/save?session_id=default&overwrite=true");
  });
  test("a bad name never reaches the server", async () => {
    const { c, t } = setup();
    expect(await c.saveFlow("bad name!")).toBe(false);
    expect(t.calls).toHaveLength(0);
  });
  test("load confirms when there are unsaved changes, then rebuilds the transcript", async () => {
    const { c, s, prompter } = setup({
      "GET /chat/history": () => ({ status: 200, body: { phase: "adventure", messages: [{ role: "assistant", content: [{ type: "text", text: "Back again." }] }] } }),
    });
    s.dirty = true;
    await c.loadFlow(null);
    expect(prompter.asked[0]).toMatch(/Discard the current game and load 'old'/);
    expect(s.gameName).toBe("old");
    expect(s.blocks[0]).toMatchObject({ kind: "markdown" });
    expect(s.dirty).toBe(false);
  });
  test("declining the discard keeps the game", async () => {
    const { c, s, prompter, t } = setup();
    prompter.confirms = [false];
    s.dirty = true;
    await c.loadFlow("old");
    expect(t.calls.some((x) => x.url.includes("/restore"))).toBe(false);
  });
  test("new game: save first, discard, or cancel", async () => {
    const { c, s, prompter, t } = setup({
      "POST /chat/new": () => ({ status: 200, body: { phase: "session_zero", ruleset_name: "5.5e" } }),
      "PUT /history/mygame/save": () => ({ status: 200, body: { message_count: 1 } }),
    });
    s.beginTurn("hello");
    s.apply({ type: "message_end", messageId: "", stopReason: "", usage: {}, phase: "", rulesetName: "", metrics: {}, story: null, compendium: null });
    prompter.newChoice = null;
    await c.newFlow();
    expect(t.calls.some((x) => x.url.includes("/chat/new"))).toBe(false);
    prompter.newChoice = "save";
    await c.newFlow();
    expect(t.calls.some((x) => x.url.includes("/chat/new"))).toBe(true);
    expect(s.blocks.map((b) => b.kind)).toEqual(["system"]);
    expect(s.gameName).toBeNull();
  });
});

describe("slash commands", () => {
  test("panels open through the prompter", async () => {
    const { c, prompter } = setup();
    await c.startup();
    await c.submit("/compendium wren");
    await c.submit("/compendium hidden");
    await c.submit("/sheet toby");
    await c.submit("/status");
    expect(prompter.panels).toEqual([
      ["compendium", { tab: undefined, name: "wren" }],
      ["compendium", { tab: "hidden", name: undefined }],
      ["status", { character: "toby" }],
      ["status", { character: undefined }],
    ]);
  });
  test("panels are refused on a server without them", async () => {
    const { c, s } = setup({ "GET /health": () => ({ status: 200, body: {} }) });
    await c.startup();
    await c.submit("/status");
    await c.submit("/compendium");
    expect(texts(s).slice(-2)).toEqual(["This server does not offer the status page.", "This server does not offer the compendium."]);
  });
  test("saves, info, delete and unknown commands", async () => {
    const { c, s } = setup({
      "GET /history": () => ({ status: 200, body: { histories: [{ name: "a", message_count: 3, saved_at: "t" }] } }),
      "GET /history/a": () => ({ status: 200, body: { name: "a", message_count: 3, saved_at: "t", model: "m" } }),
      "DELETE /history/a": () => ({ status: 200, body: {} }),
    });
    await c.submit("/saves");
    await c.submit("/info a");
    await c.submit("/delete a");
    await c.submit("/nope");
    await c.submit("/info");
    const t = texts(s);
    expect(t).toContain("  a  (3 messages, t)");
    expect(t).toContain("Deleted 'a'.");
    expect(t).toContain("Unknown command: /nope. Type /help.");
    expect(t).toContain("Usage: /info NAME");
  });
  test("debug commands need a debug server", async () => {
    const { c, s } = setup({ "GET /health": () => ({ status: 200, body: {} }) });
    await c.startup();
    await c.submit("/thinking off");
    expect(texts(s).pop()).toMatch(/not in debug mode/);
  });
});
