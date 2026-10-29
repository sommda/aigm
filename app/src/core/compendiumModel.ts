/** The compendium panel's model: the lists and details the server sent, the cursor, which entries have been read.
 * A port of `compendium_model.py` without the terminal drawing (docs/COMPENDIUM.md 6). */

import { Json } from "./events";

export const TABS = ["locations", "characters", "other"] as const;
export const HIDDEN = "hidden"; // the debug-only tab of what the player has not been told (docs/COMPENDIUM.md 11)
export const TITLES: Record<string, string> = {
  locations: "Locations",
  characters: "Characters",
  other: "Other",
  [HIDDEN]: "Hidden",
};
export type Counts = { count: number; new: number; updated: number };
export interface Link {
  heading: string;
  target: Json;
}

const ALL_TABS = [...TABS, HIDDEN];
const emptyCounts = (): Counts => ({ count: 0, new: 0, updated: 0 });
const idOf = (e: Json) => String(e.id);

export class CompendiumModel {
  tabs: string[];
  tab = "locations";
  lists: Record<string, Json[]> = Object.fromEntries(ALL_TABS.map((t) => [t, []]));
  counts: Record<string, Counts> = Object.fromEntries(ALL_TABS.map((t) => [t, emptyCounts()]));
  cursor: Record<string, number> = Object.fromEntries(ALL_TABS.map((t) => [t, 0]));
  details: Record<string, Json> = {};
  hiddenDetails: Record<string, Json> = {}; // apart from `details`: the ids are the same entities
  query = "";
  unseenOnly = false;
  read = new Set<string>(); // read during this opening: their marks stay on screen until it closes
  pending: string[] = []; // read, but not yet sent to the server
  linkMode = false;
  linkIndex = 0;
  trail: [string, string][] = []; // (tab, entity id) to go back to

  constructor(hidden = false) {
    this.tabs = hidden ? [...TABS, HIDDEN] : [...TABS];
  }

  // ---- loading -----------------------------------------------------------------------------

  loadSummary(summary: Json): void {
    for (const c of (Array.isArray(summary.categories) ? summary.categories : []) as Json[]) {
      const id = String(c.id);
      if (id in this.counts)
        this.counts[id] = { count: Number(c.count) || 0, new: Number(c.new) || 0, updated: Number(c.updated) || 0 };
    }
  }

  loadList(category: string, data: Json): void {
    if (!(category in this.lists)) return;
    const keep = category === this.tab ? this.currentId : null;
    this.lists[category] = (Array.isArray(data.entries) ? data.entries : []).filter(
      (e): e is Json => !!e && typeof e === "object",
    );
    this.cursor[category] = keep ? this.indexOf(category, keep) : 0;
    if (category === HIDDEN) {
      this.counts[HIDDEN].count = this.lists[HIDDEN].length;
      this.hiddenDetails = {}; // a secret can change under the cursor: always fetch it again
      return;
    }
    const known = new Set(TABS.flatMap((t) => this.lists[t].map(idOf)));
    // an entry whose portrait is still being painted is always fetched again: the picture may be there by now
    const waiting = (d: Json) => (d.portrait as { state?: string } | null | undefined)?.state === "pending";
    this.details = Object.fromEntries(Object.entries(this.details).filter(([k, d]) => known.has(k) && !waiting(d)));
  }

  indexOf(category: string, id: string | null): number {
    const i = this.lists[category].findIndex((e) => idOf(e) === id);
    return i < 0 ? 0 : i;
  }

  loadDetail(detail: Json, hidden = false): void {
    (hidden ? this.hiddenDetails : this.details)[idOf(detail)] = detail;
  }

  get onHidden(): boolean {
    return this.tab === HIDDEN;
  }

  hasDetail(id: string): boolean {
    return id in (this.onHidden ? this.hiddenDetails : this.details);
  }

  // ---- the cursor --------------------------------------------------------------------------

  get entries(): Json[] {
    const rows = this.lists[this.tab];
    return this.unseenOnly && !this.onHidden ? rows.filter((e) => this.unread(e)) : rows;
  }

  get current(): Json | null {
    const rows = this.entries;
    return rows.length ? rows[Math.min(this.cursor[this.tab], rows.length - 1)] : null;
  }

  get currentId(): string | null {
    return this.current ? idOf(this.current) : null;
  }

  get currentDetail(): Json | null {
    const id = this.currentId;
    if (!id) return null;
    return (this.onHidden ? this.hiddenDetails : this.details)[id] ?? null;
  }

  unread(entry: Json): boolean {
    return !!entry.status && !this.read.has(idOf(entry));
  }

  unreadCount(category?: string): number {
    const rows = category ? this.lists[category] : TABS.flatMap((t) => this.lists[t]);
    return rows.filter((e) => this.unread(e)).length;
  }

  /** Put the cursor on the n-th entry of the current list. */
  moveTo(index: number): void {
    const rows = this.entries;
    if (rows.length) this.cursor[this.tab] = Math.max(0, Math.min(index, rows.length - 1));
  }

  switchTab(tab: string): void {
    if (this.tabs.includes(tab)) {
      this.tab = tab;
      this.linkMode = false;
    }
  }

  /** Put the cursor on an entity of a tab, clearing the filter that could hide it. False when it is not there. */
  select(category: string, id: string): boolean {
    if (!(this.lists[category] ?? []).some((e) => idOf(e) === id)) return false;
    this.tab = category;
    this.linkMode = false;
    this.unseenOnly = false;
    this.cursor[category] = this.indexOf(category, id);
    return true;
  }

  /** Jump to the next entry with an unread mark, across the tabs, after the cursor. False when none is left. */
  nextUnread(): boolean {
    const order = TABS.flatMap((t) => this.lists[t].map((_, i) => [t, i] as [string, number]));
    const hereId = this.currentId;
    const here: [string, number] = hereId ? [this.tab, this.indexOf(this.tab, hereId)] : [TABS[0], -1];
    const at = order.findIndex(([t, i]) => t === here[0] && i === here[1]);
    const start = at >= 0 ? at + 1 : 0;
    for (const [tab, i] of [...order.slice(start), ...order.slice(0, start)]) {
      const entry = this.lists[tab][i];
      if (this.unread(entry)) return this.select(tab, idOf(entry));
    }
    return false;
  }

  /** Open what `/compendium NAME` asked for: an exact or unique-prefix name match across the lists ("found"),
   * otherwise the first tab with a partial match, which also becomes the filter ("filtered"). */
  focusName(text: string): "found" | "filtered" | "none" {
    const wanted = text.trim().toLowerCase();
    const rows = TABS.flatMap((t) => this.lists[t].map((e): [string, Json] => [t, e]));
    const name = (e: Json) => String(e.name).toLowerCase();
    const exact = rows.filter(([, e]) => name(e) === wanted);
    const prefix = rows.filter(([, e]) => name(e).startsWith(wanted));
    for (const found of [exact, prefix.length === 1 ? prefix : []]) {
      if (found.length) {
        this.select(found[0][0], idOf(found[0][1]));
        return "found";
      }
    }
    const partial = rows.filter(([, e]) => name(e).includes(wanted));
    if (partial.length === 1) {
      this.select(partial[0][0], idOf(partial[0][1]));
      return "found";
    }
    if (partial.length) {
      this.tab = partial[0][0];
      this.query = text.trim();
      return "filtered";
    }
    return "none";
  }

  // ---- reading marks -----------------------------------------------------------------------

  /** The player has looked at an entry. Returns true when that is news to send to the server. */
  markRead(id: string): boolean {
    const entry = TABS.flatMap((t) => this.lists[t]).find((e) => idOf(e) === id);
    if (!entry || !entry.status || this.read.has(id)) return false;
    this.read.add(id);
    this.pending.push(id);
    return true;
  }

  markAllRead(): void {
    for (const t of TABS) for (const e of this.lists[t]) if (e.status) this.read.add(idOf(e));
    this.pending = [];
  }

  takePending(): string[] {
    const out = this.pending;
    this.pending = [];
    return out;
  }

  requeue(ids: string[]): void {
    this.pending = [...ids, ...this.pending];
  }

  // ---- links in the detail -----------------------------------------------------------------

  /** What the detail points at: the parent, the children and the related entities, in the order they are drawn. */
  links(): Link[] {
    const d = this.currentDetail;
    if (!d || this.onHidden) return [];
    const out: Link[] = [];
    if (d.parent) out.push({ heading: "Inside", target: d.parent as Json });
    for (const c of (d.children as Json[]) ?? []) out.push({ heading: "Places inside", target: c });
    for (const r of (d.related as Json[]) ?? []) out.push({ heading: "See also", target: r });
    return out;
  }

  /** Jump to a link. Returns its id, or null if it is not in the lists (they are stale). */
  follow(target: Json): string | null {
    const id = idOf(target);
    const category = (target.category as string | undefined) ?? this.categoryOf(id);
    const here: [string, string] = [this.tab, this.currentId ?? ""];
    if (category && this.select(category, id)) {
      this.trail.push(here);
      return id;
    }
    return null;
  }

  private categoryOf(id: string): string | null {
    return TABS.find((t) => this.lists[t].some((e) => idOf(e) === id)) ?? null;
  }

  back(): boolean {
    while (this.trail.length) {
      const [tab, id] = this.trail.pop() as [string, string];
      if (id && this.select(tab, id)) return true;
    }
    return false;
  }
}
