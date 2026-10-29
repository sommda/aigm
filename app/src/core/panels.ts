/** The status and compendium panels' logic: what to ask the server for, and when. No UI in it; a panel component
 * subscribes and draws the model. Ports of the terminal client's two screens. */

import { ApiClient, ApiError } from "./api";
import { CompendiumModel, HIDDEN, TABS } from "./compendiumModel";
import { Json } from "./events";
import { CHARACTER_PREFIX, STATUS_TAB, StatusModel } from "./statusModel";

const DWELL_MS = 1000; // how long the cursor rests on an entry before it counts as read
const FLUSH_MS = 3000; // read marks are sent in batches

type Listener = () => void;

class Notifier {
  version = 0;
  private listeners = new Set<Listener>();
  subscribe = (fn: Listener) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = () => this.version;
  protected changed() {
    this.version++;
    for (const fn of [...this.listeners]) fn();
  }
}

function unavailable(e: unknown, what: string): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return `This server does not offer the ${what}.`;
    return `Could not load the ${what}: ${e.message}`;
  }
  return `Could not load the ${what}: ${String(e)}`;
}

const PORTRAIT_POLL_MS = 5000;
const PORTRAIT_POLLS = 60; // five minutes

export class StatusPanel extends Notifier {
  model = new StatusModel();
  error = "";
  loading = false;
  private startCharacter: string | undefined;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private polls = 0;

  constructor(
    private api: ApiClient,
    character?: string,
  ) {
    super();
    this.startCharacter = character;
  }

  /** Where a portrait's server path can be fetched from. */
  imageUrl(path: string): string {
    return this.api.imageUrl(path);
  }

  /** Stop waiting for a portrait (the tab is closing). */
  stop(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.pollTimer = null;
  }

  /** While the open character's portrait is still being painted, look again every few seconds, for a few minutes. */
  private watch(): void {
    this.stop();
    const page = this.model.page as { portrait?: { state?: string } } | undefined;
    if (this.model.character && page?.portrait?.state === "pending" && this.polls < PORTRAIT_POLLS) {
      this.pollTimer = setTimeout(() => void this.poll(), PORTRAIT_POLL_MS);
    }
  }

  private async poll(): Promise<void> {
    this.polls++;
    const m = this.model;
    const tab = m.tab;
    const name = m.character;
    try {
      if (name) {
        const page = await this.api.character(name);
        if (m.tab === tab) m.load(tab, page);
      }
    } catch {
      // the next look will tell; a failed poll is not shown
    }
    this.changed();
    this.watch();
  }

  /** Ask for the party (the tabs) and for the page that is showing. */
  async load(): Promise<void> {
    const m = this.model;
    this.polls = 0;
    this.loading = true;
    this.changed();
    try {
      m.loadRoster(await this.api.characters());
      if (this.startCharacter !== undefined) {
        // "" means the first character
        const first = m.tabs.find(([t]) => t !== STATUS_TAB)?.[0] ?? m.tab;
        m.tab = m.findTab(this.startCharacter) ?? first;
        this.startCharacter = undefined;
      }
      const tab = m.tab;
      const name = m.character;
      m.load(tab, name ? await this.api.character(name) : await this.api.status());
      this.error = "";
    } catch (e) {
      this.error = unavailable(e, "status page");
    }
    this.loading = false;
    this.changed();
    this.watch();
  }

  async switchTo(tab: string): Promise<void> {
    if (this.model.switchTo(tab)) {
      this.changed();
      await this.load();
    }
  }
}

export class CompendiumPanel extends Notifier {
  model: CompendiumModel;
  error = "";
  loading = false;
  private dwell: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private startTab: string | undefined;
  private startName: string | undefined;
  /** Told the unread totals after every server reply ({new, updated}). */
  onCounts: ((counts: Json) => void) | null = null;
  /** Said when something the player asked for is not there. */
  notice = "";
  private portraitTimer: ReturnType<typeof setTimeout> | null = null;
  private portraitPolls = 0;
  private portraitFor: string | null = null;

  constructor(
    private api: ApiClient,
    opts: { hidden?: boolean; tab?: string; name?: string } = {},
  ) {
    super();
    this.model = new CompendiumModel(opts.hidden === true);
    this.startTab = opts.tab;
    this.startName = opts.name;
  }

  start(): void {
    this.flushTimer = setInterval(() => {
      if (this.model.pending.length) void this.flush();
    }, FLUSH_MS);
    void this.load();
  }

  /** Where a portrait's server path can be fetched from. */
  imageUrl(path: string): string {
    return this.api.imageUrl(path);
  }

  /** Stop the timers and send what has been read. */
  async close(): Promise<void> {
    if (this.dwell) clearTimeout(this.dwell);
    if (this.flushTimer) clearInterval(this.flushTimer);
    if (this.portraitTimer) clearTimeout(this.portraitTimer);
    this.dwell = this.flushTimer = this.portraitTimer = null;
    await this.flush();
  }

  private sortFor(tab: string): string {
    return tab === "locations" ? "tree" : "name";
  }

  /** Fetch the counts and the lists. Read marks go first, so a refresh does not bring them back. */
  async load(): Promise<void> {
    await this.flush();
    const m = this.model;
    this.portraitPolls = 0; // a refresh starts the wait for a portrait over
    this.loading = true;
    this.changed();
    try {
      const summary = await this.api.compendium();
      m.loadSummary(summary);
      for (const tab of TABS) m.loadList(tab, await this.api.compendiumList(tab, tab === m.tab ? m.query : "", "", this.sortFor(tab)));
      if (m.tabs.includes(HIDDEN)) await this.loadHidden();
      this.error = "";
      this.report(summary);
    } catch (e) {
      this.error = unavailable(e, "compendium");
      this.loading = false;
      this.changed();
      return;
    }
    if (this.startTab && m.tabs.includes(this.startTab)) m.switchTab(this.startTab);
    this.startTab = undefined;
    if (this.startName) {
      const outcome = m.focusName(this.startName);
      if (outcome === "none") this.notice = `Nothing known by the name '${this.startName}'.`;
      else if (outcome === "filtered") await this.reloadTab();
      this.startName = undefined;
    }
    this.loading = false;
    this.changed();
    await this.ensureDetail();
  }

  /** The debug tab. A server that cannot answer leaves it empty, and the other tabs work as usual. */
  private async loadHidden(): Promise<void> {
    const m = this.model;
    try {
      m.loadList(HIDDEN, await this.api.debugHidden(m.onHidden ? m.query : ""));
    } catch (e) {
      m.loadList(HIDDEN, { entries: [] });
      this.notice = `The hidden tab is not available: ${e instanceof ApiError ? e.message : String(e)}`;
    }
  }

  async reloadTab(): Promise<void> {
    const m = this.model;
    try {
      if (m.onHidden) await this.loadHidden();
      else m.loadList(m.tab, await this.api.compendiumList(m.tab, m.query, "", this.sortFor(m.tab)));
      this.error = "";
    } catch (e) {
      this.error = unavailable(e, "compendium");
    }
    this.changed();
    await this.ensureDetail();
  }

  async ensureDetail(): Promise<void> {
    const m = this.model;
    const id = m.currentId;
    if (id === null || m.hasDetail(id)) {
      this.changed();
      this.rest();
      this.watchPortrait();
      return;
    }
    const hidden = m.onHidden;
    try {
      m.loadDetail(await (hidden ? this.api.debugHiddenEntity(id) : this.api.compendiumEntity(id)), hidden);
    } catch {
      return;
    }
    this.changed();
    this.rest();
    this.watchPortrait();
  }

  /** While the open person's portrait is still being painted, fetch the entry again every few seconds, for a few
   * minutes, so the picture appears without the player doing anything. */
  private watchPortrait(): void {
    if (this.portraitTimer) clearTimeout(this.portraitTimer);
    this.portraitTimer = null;
    const m = this.model;
    const id = m.currentId;
    const portrait = (m.onHidden ? null : m.currentDetail)?.portrait as { state?: string } | null | undefined;
    if (id !== this.portraitFor) {
      this.portraitFor = id;
      this.portraitPolls = 0;
    }
    if (id && portrait?.state === "pending" && this.portraitPolls < PORTRAIT_POLLS) {
      this.portraitTimer = setTimeout(() => void this.pollPortrait(id), PORTRAIT_POLL_MS);
    }
  }

  private async pollPortrait(id: string): Promise<void> {
    this.portraitPolls++;
    const m = this.model;
    try {
      if (!m.onHidden && m.currentId === id) m.loadDetail(await this.api.compendiumEntity(id));
    } catch {
      // the next look will tell; a failed poll is not shown
    }
    this.changed();
    this.watchPortrait();
  }

  // ---- actions the panel offers --------------------------------------------------------------

  async switchTab(tab: string): Promise<void> {
    this.model.switchTab(tab);
    this.changed();
    await this.ensureDetail();
  }

  async selectIndex(index: number): Promise<void> {
    this.model.moveTo(index);
    this.model.linkMode = false;
    this.changed();
    await this.ensureDetail();
  }

  async setQuery(query: string): Promise<void> {
    this.model.query = query;
    await this.reloadTab();
  }

  async toggleUnseen(): Promise<void> {
    this.model.unseenOnly = !this.model.unseenOnly;
    this.model.moveTo(0);
    this.changed();
    await this.ensureDetail();
  }

  async nextUnread(): Promise<void> {
    if (!this.model.nextUnread()) this.notice = "Nothing unread.";
    this.changed();
    await this.ensureDetail();
  }

  async follow(target: Json): Promise<void> {
    if (this.model.follow(target) === null) this.notice = "That entry is not in the lists; refresh to see it.";
    this.changed();
    await this.ensureDetail();
  }

  async back(): Promise<void> {
    if (this.model.back()) {
      this.changed();
      await this.ensureDetail();
    }
  }

  async markAllRead(): Promise<void> {
    this.model.markAllRead();
    this.changed();
    try {
      this.report(await this.api.compendiumSeen(null));
    } catch {
      /* the marks are only a convenience; the next opening shows them again */
    }
  }

  // ---- read marks ------------------------------------------------------------------------------

  /** The cursor has settled on an entry: after a moment of being looked at, it counts as read. */
  private rest(): void {
    if (this.dwell) clearTimeout(this.dwell);
    this.dwell = setTimeout(() => this.readCurrent(), DWELL_MS);
  }

  private readCurrent(): void {
    const m = this.model;
    const id = m.currentId;
    if (!m.onHidden && id !== null && id in m.details && m.markRead(id)) this.changed();
  }

  async flush(): Promise<void> {
    const ids = this.model.takePending();
    if (!ids.length) return;
    try {
      this.report(await this.api.compendiumSeen(ids));
    } catch {
      this.model.requeue(ids);
    }
  }

  private report(summary: Json): void {
    this.onCounts?.({ new: summary.new ?? 0, updated: summary.updated ?? 0 });
  }
}

export { CHARACTER_PREFIX };
