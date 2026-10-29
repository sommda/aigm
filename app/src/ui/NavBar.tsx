import { StyleSheet, Text, View } from "react-native";
import { GameController } from "../core/controller";
import { Button, Spinner } from "./controls";
import { color, font, space } from "./theme";

export type Panel = "status" | "compendium" | null;

/** The top bar: controls to open the tabs and the game menu, and the status of the game on the right. */
export function NavBar({
  game,
  panel,
  onPanel,
  showReasoning,
  onToggleReasoning,
  onSave,
  onLoad,
  onNew,
}: {
  game: GameController;
  panel: Panel;
  onPanel: (p: Panel) => void;
  showReasoning: boolean;
  onToggleReasoning: () => void;
  onSave: () => void;
  onLoad: () => void;
  onNew: () => void;
}) {
  const s = game.session;
  const working = s.busy;
  const note = s.status || (s.thinking ? "Thinking…" : working ? "GM is writing…" : "");
  const unread = s.compendiumUnread;
  const meta = [
    s.phaseLabel && s.rulesetName ? `${s.phaseLabel} · ${s.rulesetName}` : s.phaseLabel,
    s.gameName ? `${s.gameName}${s.dirty ? "*" : ""}` : s.dirty ? "unsaved*" : "",
    s.storyLabel ? `story: ${s.storyLabel}` : "",
    unread ? `✦ ${unread} new` : "",
  ].filter(Boolean);

  return (
    <View style={styles.bar}>
      <View style={styles.row}>
        <Text style={styles.title}>AIGM</Text>
        {game.hasStatus ? (
          <Button label="Status" active={panel === "status"} onPress={() => onPanel(panel === "status" ? null : "status")} testID="nav-status" />
        ) : null}
        {game.hasCompendium ? (
          <Button
            label={unread ? `Compendium ✦${unread}` : "Compendium"}
            active={panel === "compendium"}
            onPress={() => onPanel(panel === "compendium" ? null : "compendium")}
            testID="nav-compendium"
          />
        ) : null}
        <View style={styles.sep} />
        <Button label="Save" onPress={onSave} testID="nav-save" />
        <Button label="Load" onPress={onLoad} testID="nav-load" />
        <Button label="New" onPress={onNew} testID="nav-new" />
        <Button label="Reasoning" active={showReasoning} onPress={onToggleReasoning} testID="nav-reasoning" />
      </View>
      <View style={styles.statusRow}>
        <Spinner on={working} />
        <Text style={styles.note} testID="status-note">
          {note}
        </Text>
        <View style={{ flex: 1 }} />
        <Text style={styles.meta} testID="status-meta">
          {[...meta, game.debugServer ? (game.modelThinking ? "DEBUG" : "DEBUG (no thinking)") : "", game.connected ? "connected" : "not connected"]
            .filter(Boolean)
            .join("  ·  ")}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { backgroundColor: color.panel, borderBottomWidth: 1, borderBottomColor: color.border, paddingHorizontal: space.sm, paddingTop: space.sm },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.sm },
  title: { color: color.accent, fontFamily: font.story, fontSize: 20, fontWeight: "700", marginRight: space.sm },
  sep: { width: space.md },
  statusRow: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: 6 },
  note: { color: color.accent, fontFamily: font.ui, fontSize: 13 },
  meta: { color: color.dim, fontFamily: font.ui, fontSize: 13, textAlign: "right", flexShrink: 1 },
});
