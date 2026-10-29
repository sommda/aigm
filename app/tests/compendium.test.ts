import { CompendiumModel, HIDDEN } from "../src/core/compendiumModel";
import { CHARACTER_PREFIX, StatusModel } from "../src/core/statusModel";

const e = (id: string, name: string, status?: string, extra: object = {}) => ({ id, name, kind: "place", status, ...extra });

function model(hidden = false) {
  const m = new CompendiumModel(hidden);
  m.loadList("locations", { entries: [e("e1", "Ashby", "new"), e("e2", "Harrow Mine")] });
  m.loadList("characters", { entries: [e("e3", "Wren", "updated"), e("e4", "Toby")] });
  m.loadList("other", { entries: [] });
  return m;
}

describe("CompendiumModel", () => {
  test("the hidden tab exists only for a debug server", () => {
    expect(new CompendiumModel(false).tabs).toEqual(["locations", "characters", "other"]);
    expect(new CompendiumModel(true).tabs).toContain(HIDDEN);
  });
  test("summary counts and unread totals", () => {
    const m = model();
    m.loadSummary({ categories: [{ id: "locations", count: 2, new: 1, updated: 0 }] });
    expect(m.counts.locations).toEqual({ count: 2, new: 1, updated: 0 });
    expect(m.unreadCount()).toBe(2);
    expect(m.unreadCount("characters")).toBe(1);
  });
  test("the cursor stays inside the list and the unread filter narrows it", () => {
    const m = model();
    m.moveTo(99);
    expect(m.currentId).toBe("e2");
    m.unseenOnly = true;
    expect(m.entries.map((x) => x.id)).toEqual(["e1"]);
  });
  test("reading marks go to the server once", () => {
    const m = model();
    expect(m.markRead("e1")).toBe(true);
    expect(m.markRead("e1")).toBe(false);
    expect(m.markRead("e2")).toBe(false); // nothing unread on it
    expect(m.unreadCount("locations")).toBe(0);
    expect(m.takePending()).toEqual(["e1"]);
    m.requeue(["e1"]);
    expect(m.pending).toEqual(["e1"]);
    m.markAllRead();
    expect(m.unreadCount()).toBe(0);
    expect(m.pending).toEqual([]);
  });
  test("next unread jumps across tabs and wraps", () => {
    const m = model();
    expect(m.nextUnread()).toBe(true);
    expect(m.currentId).toBe("e3"); // e1 is under the cursor, so the next one is Wren
    expect(m.tab).toBe("characters");
    m.markAllRead();
    expect(m.nextUnread()).toBe(false);
  });
  test("focusName: exact, unique prefix, partial filter, none", () => {
    const m = model();
    expect(m.focusName("wren")).toBe("found");
    expect(m.currentId).toBe("e3");
    expect(m.focusName("harr")).toBe("found");
    expect(m.tab).toBe("locations");
    expect(m.focusName("o")).toBe("filtered"); // Toby, Harrow Mine: more than one partial match
    expect(m.query).toBe("o");
    expect(m.focusName("zzz")).toBe("none");
  });
  test("links, follow and back", () => {
    const m = model();
    m.loadDetail({ id: "e1", name: "Ashby", parent: null, children: [{ id: "e2", name: "Harrow Mine", category: "locations" }], related: [{ id: "e3", name: "Wren", category: "characters" }] });
    expect(m.links().map((l) => l.heading)).toEqual(["Places inside", "See also"]);
    expect(m.follow(m.links()[1].target)).toBe("e3");
    expect(m.tab).toBe("characters");
    expect(m.back()).toBe(true);
    expect(m.currentId).toBe("e1");
    expect(m.follow({ id: "zz", name: "Nowhere" })).toBeNull();
  });
  test("a reload keeps the cursor on the same entry and drops stale details", () => {
    const m = model();
    m.moveTo(1);
    m.loadDetail({ id: "e2", name: "Harrow Mine" });
    m.loadList("locations", { entries: [e("e0", "Aardvark"), e("e1", "Ashby"), e("e2", "Harrow Mine")] });
    expect(m.currentId).toBe("e2");
    expect(m.hasDetail("e2")).toBe(true);
    m.loadList("locations", { entries: [e("e1", "Ashby")] });
    expect(m.hasDetail("e2")).toBe(false);
  });
  test("hidden entries have their own details and no links", () => {
    const m = model(true);
    m.loadList(HIDDEN, { entries: [e("e9", "Wren")] });
    m.switchTab(HIDDEN);
    m.loadDetail({ id: "e9", name: "Wren", motives: [] }, true);
    expect(m.currentDetail).toMatchObject({ id: "e9" });
    expect(m.links()).toEqual([]);
    expect(m.counts[HIDDEN].count).toBe(1);
  });
});

describe("StatusModel", () => {
  test("tabs are Status then the party by first name", () => {
    const m = new StatusModel();
    m.loadRoster({ characters: [{ name: "Kit Harrow" }, { name: "Toby" }] });
    expect(m.tabs).toEqual([["status", "Status"], [CHARACTER_PREFIX + "Kit Harrow", "Kit"], [CHARACTER_PREFIX + "Toby", "Toby"]]);
    expect(m.findTab("ki")).toBe("c:Kit Harrow");
    expect(m.findTab("toby")).toBe("c:Toby");
    expect(m.findTab("")).toBeNull();
    expect(m.switchTo("c:Toby")).toBe(true);
    expect(m.character).toBe("Toby");
    m.loadRoster({ characters: [{ name: "Kit Harrow" }] });
    expect(m.tab).toBe("status"); // the tab's character left the party
  });
});
