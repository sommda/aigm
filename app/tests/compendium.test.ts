import { CompendiumModel, HIDDEN, HOLDING_LABELS, holdingView } from "../src/core/compendiumModel";
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
    expect(new CompendiumModel(false).tabs).toEqual(["locations", "characters", "items", "other"]);
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

describe("key items", () => {
  test("rows are labelled by whether the party has the item", () => {
    expect(HOLDING_LABELS).toEqual({ held: "held", known: "to find", used: "used", lost: "lost" });
  });
  test("a known item is not yet found", () => {
    const v = holdingView({ status: "known", since: 2, history: [{ turn: 2, status: "known", note: "" }] });
    expect(v).toEqual({ headline: "Not yet found", gone: false, note: "", history: [] });
  });
  test("a held item says since when, with no history yet", () => {
    const v = holdingView({ status: "held", since: 4, history: [{ turn: 4, status: "held", note: "Found." }] });
    expect(v?.headline).toBe("Held by the party since turn 4");
    expect(v?.history).toEqual([]);
  });
  test("a lost item says how and lists what happened", () => {
    const v = holdingView({
      status: "lost",
      since: 9,
      history: [
        { turn: 3, status: "held", note: "Found." },
        { turn: 9, status: "lost", note: "Stolen by the guard." },
      ],
    });
    expect(v).toEqual({
      headline: "Lost on turn 9",
      gone: true,
      note: "Stolen by the guard.",
      history: ["Turn 3: Had it · Found.", "Turn 9: Lost · Stolen by the guard."],
    });
  });
  test("no holding, or a status it does not know, shows nothing", () => {
    expect(holdingView(null)).toBeNull();
    expect(holdingView({ status: "unfound", since: 0, history: [] })).toBeNull();
  });
});

describe("a detail goes stale when its row changes", () => {
  const row = (extra: object = {}) => ({ id: "e30", name: "Rubbing", kind: "item", fact_count: 1, updated_turn: 51, holding: "known", ...extra });
  const loaded = (r: object) => {
    const m = new CompendiumModel(false);
    m.loadList("items", { entries: [r] });
    return m;
  };

  test("a key item found since its entry was read is fetched again", () => {
    const m = loaded(row());
    m.loadDetail({ id: "e30", name: "Rubbing", holding: { status: "known" } });
    m.loadList("items", { entries: [row()] }); // nothing changed: the cached entry stays
    expect(m.details["e30"]).toBeDefined();
    m.loadList("items", { entries: [row({ holding: "held", fact_count: 3, updated_turn: 56 })] });
    expect(m.details["e30"]).toBeUndefined();
  });
  test("a fact learned about an entry fetches it again, and marking it read does not", () => {
    const m = loaded(row({ holding: null, kind: "npc" }));
    m.loadDetail({ id: "e30", name: "Wren" });
    m.loadList("items", { entries: [row({ holding: null, unseen_count: 0, status: null })] });
    expect(m.details["e30"]).toBeDefined(); // only the read marks moved
    m.loadList("items", { entries: [row({ holding: null, updated_turn: 60 })] });
    expect(m.details["e30"]).toBeUndefined();
  });
});
