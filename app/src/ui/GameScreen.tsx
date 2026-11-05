import { useEffect, useMemo, useRef, useState } from "react";
import { LayoutChangeEvent, Platform, StyleSheet, View } from "react-native";
import { ApiClient } from "../core/api";
import { GameController, PanelKind, Prompter } from "../core/controller";
import { CompendiumPanel, StatusPanel } from "../core/panels";
import { ChatSession } from "../core/session";
import { Config } from "../platform/config";
import { transport } from "../platform/transport";
import { CompendiumView } from "./CompendiumView";
import { DialogHost, DialogResult, DialogSpec } from "./Dialogs";
import { InputPane } from "./InputPane";
import { NavBar } from "./NavBar";
import { SidePane } from "./SidePane";
import { Transcript } from "./Transcript";
import { Button } from "./controls";
import { color } from "./theme";
import { useStore } from "./useStore";

/** Below this width the two panes would be cramped, so the screen is one column (docs/LAYOUT.md 2.1). */
const TWO_COLUMNS = 900;

/** Everything the player sees (docs/LAYOUT.md): the bar on top; below it the story with the reply field on the left,
 * and on the right the status above the details, or the Compendium over both. */
export function GameScreen({ config }: { config: Config }) {
  const [dialog, setDialog] = useState<DialogSpec | null>(null);
  const resolver = useRef<((r: DialogResult) => void) | null>(null);
  const [comp, setComp] = useState<CompendiumPanel | null>(null);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [sideHidden, setSideHidden] = useState(false);
  const [npcName, setNpcName] = useState<string | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const gameRef = useRef<GameController | null>(null);

  const ask = (spec: DialogSpec) =>
    new Promise<DialogResult>((resolve) => {
      resolver.current = resolve;
      setDialog(spec);
    });
  const done = (r: DialogResult) => {
    const resolve = resolver.current;
    resolver.current = null;
    setDialog(null);
    resolve?.(r);
  };

  const game = useMemo(() => {
    const prompter: Prompter = {
      confirm: async (message, yes) => (await ask({ kind: "confirm", message, yes })) === true,
      chooseSave: async (suggested) => {
        const r = await ask({ kind: "save", suggested });
        return typeof r === "string" ? r : null;
      },
      chooseLoad: async (dirty) => {
        const r = await ask({ kind: "load", dirty });
        return typeof r === "string" ? r : null;
      },
      chooseNew: async (dirty) => {
        const r = await ask({ kind: "new", dirty });
        return r === "save" || r === "discard" ? r : null;
      },
      openPanel: (kind: PanelKind, where) => openPanel(kind, where),
    };
    const api = new ApiClient(config.url, config.session, transport);
    return new GameController(api, new ChatSession(33), prompter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.url, config.session]);
  gameRef.current = game;
  useStore(game);
  const status = useMemo(() => new StatusPanel(game.api), [game]);

  const openPanel = (kind: PanelKind, where: { character?: string; tab?: string; name?: string } = {}) => {
    const g = gameRef.current as GameController;
    if (kind === "status") {
      setComp(null);
      setNpcName(null);
      setSideHidden(false);
      void status.open(where.character);
    } else {
      const cp = new CompendiumPanel(g.api, { hidden: g.debugServer, tab: where.tab, name: where.name });
      cp.onCounts = (c) => g.session.setUnread(c);
      setComp(cp);
      setSideHidden(false);
    }
  };

  // the entry of a person chosen in the status: the details show it, opened on their name
  const npc = useMemo(() => {
    if (!npcName) return null;
    const panel = new CompendiumPanel(game.api, { hidden: false, tab: "characters", name: npcName });
    panel.onCounts = (c) => game.session.setUnread(c);
    return { name: npcName, panel };
  }, [npcName, game]);

  const toggleCompendium = () => (comp ? setComp(null) : openPanel("compendium"));

  useEffect(() => {
    void game.startup();
  }, [game]);

  // the status is loaded once the server is known to offer it, after each turn, and when the window is looked at again
  const playing = game.hasStatus && game.session.phase === "adventure";
  useEffect(() => {
    if (playing) void status.load();
    else status.reset();
    return () => status.stop();
  }, [status, playing]);
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !game.session.busy) {
      if (playing) void status.load();
      if (comp) void comp.load();
    }
    wasBusy.current = game.session.busy;
  });
  useEffect(() => {
    if (Platform.OS !== "web" || !playing) return;
    const onFocus = () => void status.load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [status, playing]);

  // Esc closes a dialog, then cancels a running turn, then closes the Compendium
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (resolver.current) done(null);
      else if (game.session.busy) game.cancelTurn();
      else if (comp) setComp(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const s = game.session;
  const placeholder = s.busy
    ? "The GM is replying… (slash commands still work)"
    : s.phase === "session_zero"
      ? "Say hello to begin Session 0…  (/help for commands)"
      : "What do you do?  (/help for commands)";

  const wide = size.width >= TWO_COLUMNS;
  const story = (
    <View style={styles.left}>
      <View style={styles.story}>
        <Transcript session={s} showReasoning={showReasoning} />
      </View>
      <InputPane
        busy={s.busy}
        placeholder={placeholder}
        onSubmit={(t) => void game.submit(t)}
        onCancel={() => game.cancelTurn()}
        maxHeight={Math.round(size.height * 0.4)}
      />
    </View>
  );
  const side = <SidePane status={status} playing={playing} compendium={comp} onCloseCompendium={() => setComp(null)} npc={npc} onChoose={setNpcName} />;

  return (
    <View style={styles.screen} onLayout={(e: LayoutChangeEvent) => setSize(e.nativeEvent.layout)}>
      <NavBar
        game={game}
        compendiumOpen={!!comp}
        onCompendium={toggleCompendium}
        showReasoning={showReasoning}
        onToggleReasoning={() => setShowReasoning((v) => !v)}
        onSave={() => void game.saveFlow(null)}
        onLoad={() => void game.loadFlow(null)}
        onNew={() => void game.newFlow()}
      />
      {wide ? (
        <View style={styles.columns}>
          {story}
          <View style={[styles.right, { width: Math.min(560, Math.max(360, Math.round(size.width * 0.4))) }]} testID="right-pane">
            {side}
          </View>
        </View>
      ) : (
        <View style={styles.stack}>
          <View style={styles.hideRow}>
            <Button label={sideHidden ? "Show side panel" : "Hide ✕"} onPress={() => setSideHidden((v) => !v)} testID="side-toggle" />
          </View>
          {sideHidden ? null : (
            <View style={styles.stackSide} testID="right-pane">
              {side}
            </View>
          )}
          {story}
        </View>
      )}
      <DialogHost api={game.api} spec={dialog} done={done} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  columns: { flex: 1, flexDirection: "row" },
  left: { flex: 1, minWidth: 0 },
  right: { borderLeftWidth: 1, borderLeftColor: color.border },
  story: { flex: 1, minHeight: 120 },
  stack: { flex: 1 },
  hideRow: { flexDirection: "row", justifyContent: "flex-end", padding: 4, backgroundColor: color.panel },
  stackSide: { flex: 0.4, minHeight: 160, borderBottomWidth: 2, borderBottomColor: color.accent },
});
