import { CompendiumPanel, StatusPanel } from "../src/core/panels";
import { FakeTransport, apiWith } from "./helpers";

const ok = (body: object) => ({ status: 200, body });

function server(extra: Record<string, () => { status: number; body: unknown }> = {}) {
  return new FakeTransport((method, url) => {
    const path = url.replace("http://x", "").split("?")[0];
    const key = `${method} ${path}`;
    if (extra[key]) return extra[key]();
    switch (path) {
      case "/compendium":
        return ok({ categories: [{ id: "locations", count: 1, new: 1, updated: 0 }], new: 1, updated: 0 });
      case "/compendium/locations":
        return ok({ entries: [{ id: "e1", name: "Ashby", kind: "place", status: "new" }] });
      case "/compendium/characters":
        return ok({ entries: [{ id: "e2", name: "Wren", kind: "person" }] });
      case "/compendium/other":
        return ok({ entries: [] });
      case "/compendium/entities/e1":
        return ok({ id: "e1", name: "Ashby", kind: "place", facts: [] });
      case "/compendium/seen":
        return ok({ new: 0, updated: 0 });
      case "/characters":
        return ok({ characters: [{ name: "Kit Harrow" }] });
      case "/characters/Kit%20Harrow":
        return ok({ name: "Kit Harrow", hp: "10/10", sections: [] });
      case "/status":
        return ok({ location: { name: "The Rusty Flagon" } });
      case "/debug/hidden":
        return ok({ entries: [{ id: "e2", name: "Wren", kind: "person" }] });
      default:
        return { status: 404, body: { error: { code: "not_found", message: "no" } } };
    }
  });
}

describe("StatusPanel", () => {
  test("loads the party and the status page, then a character on switching", async () => {
    const p = new StatusPanel(apiWith(server()));
    await p.load();
    expect(p.model.page).toMatchObject({ location: { name: "The Rusty Flagon" } });
    await p.switchTo("c:Kit Harrow");
    expect(p.model.page).toMatchObject({ hp: "10/10" });
  });
  test("opens on a named character", async () => {
    const p = new StatusPanel(apiWith(server()), "kit");
    await p.load();
    expect(p.model.character).toBe("Kit Harrow");
  });
  test("a server without the page says so", async () => {
    const p = new StatusPanel(apiWith(server({ "GET /characters": () => ({ status: 404, body: {} }) })));
    await p.load();
    expect(p.error).toBe("This server does not offer the status page.");
  });
});

describe("CompendiumPanel", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  test("loads the lists and the detail of the first entry", async () => {
    const t = server();
    const p = new CompendiumPanel(apiWith(t));
    const counts: object[] = [];
    p.onCounts = (c) => counts.push(c);
    await p.load();
    expect(p.model.currentId).toBe("e1");
    expect(p.model.currentDetail).toMatchObject({ name: "Ashby" });
    expect(counts[0]).toEqual({ new: 1, updated: 0 });
  });

  test("an entry counts as read after the dwell, and the mark is sent on close", async () => {
    const t = server();
    const p = new CompendiumPanel(apiWith(t));
    await p.load();
    expect(p.model.unreadCount("locations")).toBe(1);
    jest.advanceTimersByTime(1100);
    expect(p.model.unreadCount("locations")).toBe(0);
    await p.close();
    const seen = t.calls.find((c) => c.url.includes("/compendium/seen"));
    expect(seen?.body).toEqual({ entities: ["e1"] });
  });

  test("a failed send is kept for next time", async () => {
    const p = new CompendiumPanel(apiWith(server({ "POST /compendium/seen": () => ({ status: 500, body: {} }) })));
    await p.load();
    jest.advanceTimersByTime(1100);
    await p.close();
    expect(p.model.pending).toEqual(["e1"]);
  });

  test("starts on a tab or a name, and the hidden tab loads on a debug server", async () => {
    const p = new CompendiumPanel(apiWith(server()), { hidden: true, tab: "hidden" });
    await p.load();
    expect(p.model.tab).toBe("hidden");
    expect(p.model.lists.hidden).toHaveLength(1);
    const q = new CompendiumPanel(apiWith(server()), { name: "wren" });
    await q.load();
    expect(q.model.currentId).toBe("e2");
    const z = new CompendiumPanel(apiWith(server()), { name: "zzz" });
    await z.load();
    expect(z.notice).toMatch(/Nothing known by the name 'zzz'/);
  });

  test("filter asks the server", async () => {
    const t = server();
    const p = new CompendiumPanel(apiWith(t));
    await p.load();
    await p.setQuery("ash");
    expect(t.calls.some((c) => c.url.includes("/compendium/locations?") && c.url.includes("q=ash"))).toBe(true);
  });

  test("mark all read tells the server", async () => {
    const t = server();
    const p = new CompendiumPanel(apiWith(t));
    await p.load();
    await p.markAllRead();
    expect(t.calls.filter((c) => c.url.includes("/compendium/seen")).pop()?.body).toEqual({ all: true });
    expect(p.model.unreadCount()).toBe(0);
  });
});
