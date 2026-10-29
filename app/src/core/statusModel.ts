/** The status panel's model: the pages the server sent and which tab is showing (docs/STATUS.md 8). The server decides
 * what the pages say; the UI only lays them out. */

import { Json } from "./events";

export const STATUS_TAB = "status";
export const CHARACTER_PREFIX = "c:";

export class StatusModel {
  tab = STATUS_TAB;
  pages: Record<string, Json> = {};
  roster: Json[] = [];

  /** Status, then one tab per party member, by first name. */
  get tabs(): [string, string][] {
    return [
      [STATUS_TAB, "Status"],
      ...this.roster
        .filter((c) => typeof c.name === "string" && c.name)
        .map((c): [string, string] => [CHARACTER_PREFIX + (c.name as string), (c.name as string).split(/\s+/)[0]]),
    ];
  }

  load(tab: string, page: Json): void {
    this.pages[tab] = page;
  }

  loadRoster(data: Json): void {
    this.roster = (Array.isArray(data.characters) ? data.characters : []).filter(
      (c): c is Json => !!c && typeof c === "object",
    );
    if (!this.tabs.some(([t]) => t === this.tab)) this.tab = STATUS_TAB;
  }

  /** The character tab a name or the start of one refers to (`/sheet toby`). */
  findTab(query: string): string | null {
    const wanted = query.trim().toLowerCase();
    if (!wanted) return null;
    const names = this.tabs.filter(([t]) => t !== STATUS_TAB).map(([t]) => t);
    const nameOf = (t: string) => t.slice(CHARACTER_PREFIX.length).toLowerCase();
    return names.find((t) => nameOf(t) === wanted) ?? names.find((t) => nameOf(t).startsWith(wanted)) ?? null;
  }

  /** The name of the character whose tab is showing, or null on the status tab. */
  get character(): string | null {
    return this.tab.startsWith(CHARACTER_PREFIX) ? this.tab.slice(CHARACTER_PREFIX.length) : null;
  }

  get page(): Json | undefined {
    return this.pages[this.tab];
  }

  /** Switch to a tab; returns whether it changed. */
  switchTo(tab: string): boolean {
    if (!this.tabs.some(([t]) => t === tab)) return false;
    const changed = tab !== this.tab;
    this.tab = tab;
    return changed;
  }
}
