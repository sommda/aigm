import { useEffect, useMemo, useRef, useState } from "react";
import { Platform, StyleSheet, View } from "react-native";
import { ApiClient } from "../core/api";
import { GameController, PanelKind, Prompter } from "../core/controller";
import { CompendiumPanel, StatusPanel } from "../core/panels";
import { ChatSession } from "../core/session";
import { Config } from "../platform/config";
import { transport } from "../platform/transport";
import { CompendiumView } from "./CompendiumView";
import { DialogHost, DialogResult, DialogSpec } from "./Dialogs";
import { InputPane } from "./InputPane";
import { NavBar, Panel } from "./NavBar";
import { StatusView } from "./StatusView";
import { Transcript } from "./Transcript";
import { Button } from "./controls";
import { color } from "./theme";
import { useStore } from "./useStore";

/** Everything the player sees: the bar on top, an optional tab panel taking the upper half, the story, the reply field. */
export function GameScreen({ config }: { config: Config }) {
  const [dialog, setDialog] = useState<DialogSpec | null>(null);
  const resolver = useRef<((r: DialogResult) => void) | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [status, setStatus] = useState<StatusPanel | null>(null);
  const [comp, setComp] = useState<CompendiumPanel | null>(null);
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

  const openPanel = (kind: PanelKind, where: { character?: string; tab?: string; name?: string } = {}) => {
    const g = gameRef.current as GameController;
    if (kind === "status") {
      setStatus(new StatusPanel(g.api, where.character));
    } else {
      const cp = new CompendiumPanel(g.api, { hidden: g.debugServer, tab: where.tab, name: where.name });
      cp.onCounts = (c) => g.session.setUnread(c);
      setComp(cp);
    }
    setPanel(kind);
  };

  const choosePanel = (p: Panel) => {
    if (p === null) setPanel(null);
    else openPanel(p);
  };

  useEffect(() => {
    void game.startup();
  }, [game]);

  // after each turn, the open panel shows the new state
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !game.session.busy) {
      if (panel === "status") void status?.load();
      if (panel === "compendium") void comp?.load();
    }
    wasBusy.current = game.session.busy;
  });

  // Esc closes a dialog, then cancels a running turn, then closes the panel
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (resolver.current) done(null);
      else if (game.session.busy) game.cancelTurn();
      else if (panel) setPanel(null);
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

  return (
    <View style={styles.screen}>
      <NavBar
        game={game}
        panel={panel}
        onPanel={choosePanel}
        showReasoning={showReasoning}
        onToggleReasoning={() => setShowReasoning((v) => !v)}
        onSave={() => void game.saveFlow(null)}
        onLoad={() => void game.loadFlow(null)}
        onNew={() => void game.newFlow()}
      />
      {panel ? (
        <View style={styles.dock} testID="dock">
          <View style={styles.dockClose}>
            <Button label="Close ✕" onPress={() => setPanel(null)} testID="dock-close" />
          </View>
          {panel === "status" && status ? <StatusView panel={status} /> : null}
          {panel === "compendium" && comp ? <CompendiumView panel={comp} /> : null}
        </View>
      ) : null}
      <View style={styles.story}>
        <Transcript session={s} showReasoning={showReasoning} />
      </View>
      <InputPane busy={s.busy} placeholder={placeholder} onSubmit={(t) => void game.submit(t)} onCancel={() => game.cancelTurn()} />
      <DialogHost api={game.api} spec={dialog} done={done} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  // the open tab takes the upper half of the story area; the story keeps the lower half
  dock: { flex: 1, borderBottomWidth: 2, borderBottomColor: color.accent, backgroundColor: color.panel, minHeight: 120 },
  dockClose: { position: "absolute", right: 8, top: 4, zIndex: 5 },
  story: { flex: 1, minHeight: 120 },
});
