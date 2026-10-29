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

describe("StatusPanel portraits", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function painting(states: (object | null)[]) {
    let n = 0;
    const t = server({
      "GET /characters/Kit%20Harrow": () => ({
        status: 200,
        body: { name: "Kit Harrow", hp: "10/10", portrait: states[Math.min(n++, states.length - 1)] },
      }),
    });
    return { t, count: () => t.calls.filter((c) => c.url.includes("/characters/Kit")).length };
  }

  test("a pending portrait is looked for again until it is ready", async () => {
    const { t, count } = painting([{ state: "pending" }, { state: "pending" }, { state: "ready", url: "/portraits/p.webp" }]);
    const p = new StatusPanel(apiWith(t), "kit");
    await p.load();
    expect(count()).toBe(1);
    await jest.advanceTimersByTimeAsync(5000);
    expect(count()).toBe(2);
    await jest.advanceTimersByTimeAsync(5000);
    expect(count()).toBe(3);
    expect(p.model.page).toMatchObject({ portrait: { state: "ready" } });
    await jest.advanceTimersByTimeAsync(60000); // ready: it stops asking
    expect(count()).toBe(3);
  });

  test("it gives up after five minutes, and starts over when the player refreshes", async () => {
    const { t, count } = painting([{ state: "pending" }]);
    const p = new StatusPanel(apiWith(t), "kit");
    await p.load();
    await jest.advanceTimersByTimeAsync(10 * 60 * 1000);
    expect(count()).toBe(61);
    await p.load();
    await jest.advanceTimersByTimeAsync(5000);
    expect(count()).toBe(63);
    p.stop();
  });

  test("nothing is polled when there is no portrait coming, on the place tab, or after stop()", async () => {
    const none = painting([null]);
    const a = new StatusPanel(apiWith(none.t), "kit");
    await a.load();
    await jest.advanceTimersByTimeAsync(30000);
    expect(none.count()).toBe(1);

    const wait = painting([{ state: "pending" }]);
    const b = new StatusPanel(apiWith(wait.t), "kit");
    await b.load();
    b.stop();
    await jest.advanceTimersByTimeAsync(30000);
    expect(wait.count()).toBe(1);

    const place = new StatusPanel(apiWith(wait.t));
    await place.load();
    await jest.advanceTimersByTimeAsync(30000);
    expect(wait.count()).toBe(1);
  });

  test("a failed look does not show an error and the next one still happens", async () => {
    let n = 0;
    const t = server({
      "GET /characters/Kit%20Harrow": () => (n++ === 1 ? { status: 500, body: {} } : { status: 200, body: { name: "Kit Harrow", portrait: { state: "pending" } } }),
    });
    const p = new StatusPanel(apiWith(t), "kit");
    await p.load();
    await jest.advanceTimersByTimeAsync(5000);
    expect(p.error).toBe("");
    await jest.advanceTimersByTimeAsync(5000);
    expect(n).toBe(3);
    p.stop();
  });

  test("a portrait address is made absolute from the server's", () => {
    const p = new StatusPanel(apiWith(server()));
    expect(p.imageUrl("/portraits/a.webp?session_id=s")).toBe("http://x/portraits/a.webp?session_id=s");
    expect(p.imageUrl("https://cdn.test/a.webp")).toBe("https://cdn.test/a.webp");
  });
});

describe("CompendiumPanel portraits", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function painting(states: (object | null)[]) {
    let n = 0;
    const t = server({
      "GET /compendium/entities/e1": () => ({
        status: 200,
        body: { id: "e1", name: "Ashby", kind: "npc", facts: [], portrait: states[Math.min(n++, states.length - 1)] },
      }),
    });
    return { t, count: () => t.calls.filter((c) => c.url.includes("/compendium/entities/e1")).length };
  }

  test("an entry whose portrait is pending is fetched again until it is ready", async () => {
    const { t, count } = painting([{ state: "pending" }, { state: "ready", url: "/portraits/p.webp" }]);
    const p = new CompendiumPanel(apiWith(t));
    await p.load();
    expect(count()).toBe(1);
    await jest.advanceTimersByTimeAsync(5000);
    expect(count()).toBe(2);
    expect(p.model.currentDetail).toMatchObject({ portrait: { state: "ready" } });
    await jest.advanceTimersByTimeAsync(60000);
    expect(count()).toBe(2);
    await p.close();
  });

  test("after it gave up, a refresh fetches the entry again and finds the picture", async () => {
    let ready = false;
    const t = server({
      "GET /compendium/entities/e1": () => ({
        status: 200,
        body: { id: "e1", name: "Ashby", kind: "npc", facts: [], portrait: ready ? { state: "ready", url: "/portraits/p.webp" } : { state: "pending" } },
      }),
    });
    const p = new CompendiumPanel(apiWith(t));
    await p.load();
    await jest.advanceTimersByTimeAsync(10 * 60 * 1000); // five minutes of looking, nothing yet
    ready = true; // the next turn's sweep made it
    expect(p.model.currentDetail).toMatchObject({ portrait: { state: "pending" } });
    await p.load(); // the refresh after a turn
    expect(p.model.currentDetail).toMatchObject({ portrait: { state: "ready" } });
    await p.close();
  });

  test("it stops after five minutes, when there is no portrait, and when the panel closes", async () => {
    const wait = painting([{ state: "pending" }]);
    const a = new CompendiumPanel(apiWith(wait.t));
    await a.load();
    await jest.advanceTimersByTimeAsync(10 * 60 * 1000);
    expect(wait.count()).toBe(61);
    await a.close();

    const none = painting([null]);
    const b = new CompendiumPanel(apiWith(none.t));
    await b.load();
    await jest.advanceTimersByTimeAsync(30000);
    expect(none.count()).toBe(1);
    await b.close();

    const closed = painting([{ state: "pending" }]);
    const c = new CompendiumPanel(apiWith(closed.t));
    await c.load();
    await c.close();
    await jest.advanceTimersByTimeAsync(30000);
    expect(closed.count()).toBe(1);
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
