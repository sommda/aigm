/** The game controller: the flows of the terminal client's app (startup, a turn, save, load, new game, slash
 * commands), with no UI in it. Anything that needs the player (a dialog, a panel) goes through the `Prompter`. */

import { AbortedError, ApiClient, ApiError } from "./api";
import { Json } from "./events";
import { NAME_RE, Command, parseCommand, suggestName } from "./commands";
import { ChatSession, introText, storyNote } from "./session";

export type PanelKind = "status" | "compendium";

export interface Prompter {
  confirm(message: string, yesLabel: string): Promise<boolean>;
  /** Ask for a save name (prefilled with `suggested`); null when cancelled. */
  chooseSave(suggested: string): Promise<string | null>;
  /** Ask which saved game to load; null when cancelled. */
  chooseLoad(dirty: boolean): Promise<string | null>;
  chooseNew(dirty: boolean): Promise<"save" | "discard" | null>;
  openPanel(panel: PanelKind, where?: { character?: string; tab?: string; name?: string }): void;
}

export const HELP = `Commands:
  /new                  start a new game
  /save [NAME] [--overwrite]  save the game
  /load [NAME]          load a saved game
  /saves                list saved games
  /info NAME            show info about a saved game
  /delete NAME          delete a saved game
  /compendium [TAB|NAME]  what you have learned: locations, characters, items, other
  /status               where you are and who is with you
  /sheet [NAME]         a character's sheet
  /reconnect            retry connecting to the server
Keys: Enter sends, Shift+Enter adds a line, Esc cancels the current turn.`;
export const DEBUG_HELP =
  "\nDebug server:" +
  "\n  /story  prints the whole story plan (spoilers)" +
  "\n  /thinking [on|off]  turn the model's thinking on or off, to compare a move both ways" +
  "\n  /compendium hidden  browses the facts and motives the player has not been told" +
  "\n  (the context viewer is in the terminal client for now)";

type Listener = () => void;

const message = (e: unknown): string => (e instanceof ApiError ? e.message : String(e));

export class GameController {
  connected = false;
  debugServer = false;
  hasCompendium = false;
  hasStatus = false;
  modelThinking = true;
  serverUrl: string;
  /** Bumped whenever anything the UI shows changed, including the session. */
  version = 0;

  private abort: AbortController | null = null;
  private listeners = new Set<Listener>();

  constructor(
    public api: ApiClient,
    public session: ChatSession,
    public prompter: Prompter,
  ) {
    this.serverUrl = api.baseUrl;
    session.subscribe(() => this.touch());
  }

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = (): number => this.version;

  touch(): void {
    this.version++;
    for (const fn of [...this.listeners]) fn();
  }

  // ---- startup -----------------------------------------------------------------------------

  async startup(): Promise<void> {
    const s = this.session;
    try {
      const health = await this.api.health();
      const state = await this.api.chatState();
      this.connected = true;
      this.debugServer = health.debug === true;
      this.hasCompendium = health.compendium === true;
      this.hasStatus = health.status === true;
      this.modelThinking = health.thinking !== false;
      s.showMetrics = this.debugServer;
      s.loadHistory(state);
      s.dirty = ((state.messages as unknown[]) ?? []).length > 0;
      if (!s.dirty) s.addSystem(introText(s.phase));
    } catch (e) {
      this.connected = false;
      s.addSystem(`${message(e)}\nStart the server, then type /reconnect.`, "red");
    }
    this.touch();
  }

  // ---- input -------------------------------------------------------------------------------

  /** What the player submitted: a slash command or a chat message. */
  async submit(raw: string): Promise<void> {
    const text = raw.trim();
    if (!text) return;
    const cmd = parseCommand(text);
    if (cmd) {
      await this.runCommand(cmd);
      return;
    }
    if (!this.session.canInput) return;
    await this.runTurn(text);
  }

  async runTurn(text: string): Promise<void> {
    const s = this.session;
    s.beginTurn(text);
    this.abort = new AbortController();
    try {
      for await (const event of this.api.streamChat(text, this.abort.signal)) s.apply(event);
    } catch (e) {
      if (e instanceof AbortedError) s.interrupted();
      else if (e instanceof ApiError)
        s.fail(e.code === "conflict" ? "A turn is already in progress for this session." : e.message);
      else s.fail(String(e));
    } finally {
      this.abort = null;
      if (s.busy) s.fail("Connection closed unexpectedly");
      this.touch();
    }
  }

  cancelTurn(): void {
    if (this.abort && this.session.busy) this.abort.abort();
  }

  // ---- save / load / new -------------------------------------------------------------------

  private requireIdle(): boolean {
    if (this.session.busy) {
      this.session.addSystem("Wait for the GM to finish, or press Esc to cancel the turn.", "yellow");
      return false;
    }
    return true;
  }

  async saveFlow(name: string | null, overwrite = false): Promise<boolean> {
    const s = this.session;
    if (!this.requireIdle()) return false;
    let chosen = name;
    if (chosen === null) {
      chosen = await this.prompter.chooseSave(s.gameName ?? suggestName());
      if (chosen === null) return false;
    }
    if (!NAME_RE.test(chosen)) {
      s.addSystem("Save failed: a name may use letters, digits, - and _ (up to 64).", "red");
      return false;
    }
    try {
      const info = await this.api.save(chosen, overwrite);
      s.markSaved(chosen);
      s.addSystem(`Saved as '${chosen}' (${info.message_count ?? "?"} messages).`);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.code === "already_exists" && !overwrite) {
        if (await this.prompter.confirm(`'${chosen}' already exists. Overwrite?`, "Overwrite"))
          return this.saveFlow(chosen, true);
        return false;
      }
      s.addSystem(`Save failed: ${message(e)}`, "red");
      return false;
    }
  }

  async loadFlow(name: string | null): Promise<void> {
    const s = this.session;
    if (!this.requireIdle()) return;
    let chosen = name;
    if (chosen === null) {
      chosen = await this.prompter.chooseLoad(s.dirty);
      if (chosen === null) return;
    }
    if (s.dirty && !(await this.prompter.confirm(`Discard the current game and load '${chosen}'?`, "Load anyway")))
      return;
    try {
      await this.api.restore(chosen);
      const state = await this.api.chatState();
      s.loadHistory(state);
      s.markLoaded(chosen);
      s.addSystem(`Loaded '${chosen}'.` + (s.phaseLabel ? ` (${s.phaseLabel})` : ""));
    } catch (e) {
      s.addSystem(`Load failed: ${message(e)}`, "red");
    }
  }

  async newFlow(): Promise<void> {
    const s = this.session;
    if (!this.requireIdle()) return;
    if (s.hasGame) {
      const choice = await this.prompter.chooseNew(s.dirty);
      if (choice === "save") {
        if (!(await this.saveFlow(null))) return;
      } else if (choice !== "discard") return;
    }
    try {
      const result = await this.api.newGame();
      s.newGame(String(result.phase ?? ""), String(result.ruleset_name ?? ""));
      s.addSystem("New game started. " + introText(s.phase));
    } catch (e) {
      s.addSystem(`New game failed: ${message(e)}`, "red");
    }
  }

  // ---- slash commands ----------------------------------------------------------------------

  async runCommand(cmd: Command): Promise<void> {
    const s = this.session;
    switch (cmd.name) {
      case "help":
        s.addSystem(HELP + (this.debugServer ? DEBUG_HELP : ""));
        break;
      case "compendium":
        this.openCompendium(cmd.args.join(" ") || undefined);
        break;
      case "status":
        this.openStatus();
        break;
      case "sheet":
        this.openStatus(cmd.args.join(" "));
        break;
      case "context":
        s.addSystem("The context viewer is not in this client yet; use the terminal client (/context).", "yellow");
        break;
      case "story":
        await this.storyFlow();
        break;
      case "thinking": {
        const words: Record<string, boolean> = { on: true, off: false };
        if (cmd.arg !== undefined && !(cmd.arg.toLowerCase() in words))
          s.addSystem("Use /thinking on, /thinking off, or /thinking to switch.", "yellow");
        else await this.thinkingFlow(cmd.arg === undefined ? null : words[cmd.arg.toLowerCase()]);
        break;
      }
      case "quit":
        s.addSystem("Close the window or tab to quit.", "yellow");
        break;
      case "reconnect":
        await this.startup();
        break;
      case "new":
        await this.newFlow();
        break;
      case "save":
        await this.saveFlow(cmd.arg ?? null, cmd.flags.has("overwrite"));
        break;
      case "load":
        await this.loadFlow(cmd.arg ?? null);
        break;
      case "saves":
        await this.listSaves();
        break;
      case "info":
      case "delete":
        if (!cmd.arg) s.addSystem(`Usage: /${cmd.name} NAME`, "yellow");
        else if (cmd.name === "info") await this.info(cmd.arg);
        else await this.deleteSave(cmd.arg);
        break;
      default:
        s.addSystem(`Unknown command: /${cmd.arg ?? ""}. Type /help.`, "yellow");
    }
  }

  openStatus(character?: string): void {
    if (!this.hasStatus) this.session.addSystem("This server does not offer the status page.", "yellow");
    else this.prompter.openPanel("status", { character });
  }

  openCompendium(where?: string): void {
    if (!this.hasCompendium) {
      this.session.addSystem("This server does not offer the compendium.", "yellow");
      return;
    }
    const tabs = ["locations", "characters", "items", "other", ...(this.debugServer ? ["hidden"] : [])];
    const lower = where?.toLowerCase();
    const tab = lower && tabs.includes(lower) ? lower : undefined;
    this.prompter.openPanel("compendium", { tab, name: where && !tab ? where : undefined });
  }

  private async listSaves(): Promise<void> {
    try {
      const saves = await this.api.listHistories();
      if (!saves.length) this.session.addSystem("No saved games.");
      for (const h of saves) {
        const note = storyNote(h.story as Json | undefined);
        this.session.addSystem(
          `  ${h.name}  (${h.message_count ?? "?"} messages, ${h.saved_at ?? ""})` + (note ? `, ${note}` : ""),
        );
      }
    } catch (e) {
      this.session.addSystem(message(e), "red");
    }
  }

  private async info(name: string): Promise<void> {
    try {
      const info = await this.api.historyInfo(name);
      const note = storyNote(info.story as Json | undefined);
      this.session.addSystem(
        `${info.name}: ${info.message_count} messages, saved ${info.saved_at}, model ${info.model}\n` +
          `  last: ${info.last_message_preview ?? "(none)"}` +
          (note ? `\n  ${note}` : ""),
      );
    } catch (e) {
      this.session.addSystem(message(e), "red");
    }
  }

  async deleteSave(name: string): Promise<void> {
    if (!(await this.prompter.confirm(`Delete saved game '${name}'?`, "Delete"))) return;
    try {
      await this.api.delete(name);
      this.session.addSystem(`Deleted '${name}'.`);
    } catch (e) {
      this.session.addSystem(message(e), "red");
    }
  }

  private async storyFlow(): Promise<void> {
    if (!this.debugServer) {
      this.session.addSystem("The server is not in debug mode (start it with --debug).", "yellow");
      return;
    }
    try {
      this.session.addSystem(JSON.stringify(await this.api.debugStory(), null, 2));
    } catch (e) {
      this.session.addSystem(message(e), "red");
    }
  }

  private async thinkingFlow(enabled: boolean | null): Promise<void> {
    if (!this.debugServer) {
      this.session.addSystem("The server is not in debug mode (start it with --debug).", "yellow");
      return;
    }
    try {
      this.modelThinking = await this.api.setThinking(enabled ?? !this.modelThinking);
      this.session.addSystem(`Model thinking is ${this.modelThinking ? "on" : "off"}.`);
    } catch (e) {
      this.session.addSystem(message(e), "red");
    }
  }
}
