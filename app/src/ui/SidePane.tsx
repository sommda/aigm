import { StyleSheet, Text, View } from "react-native";
import { CompendiumPanel, StatusPanel } from "../core/panels";
import { CompendiumView } from "./CompendiumView";
import { Details } from "./Details";
import { StatusSection } from "./StatusSection";
import { Button } from "./controls";
import { color, font, space } from "./theme";

/** The right pane (docs/LAYOUT.md): the status above and the details below it, or the Compendium over both. */
export function SidePane({
  status,
  playing,
  compendium,
  onCloseCompendium,
  npc,
  onChoose,
}: {
  status: StatusPanel;
  /** False in Session 0 and without a status page: there is no party or place to show yet. */
  playing: boolean;
  compendium: CompendiumPanel | null;
  onCloseCompendium: () => void;
  /** The person chosen in the status, whose compendium entry the details show. */
  npc: { name: string; panel: CompendiumPanel } | null;
  onChoose: (npc: string | null) => void;
}) {
  if (compendium) {
    return (
      <View style={styles.pane} testID="side-pane">
        <View style={styles.close}>
          <Button label="Close ✕" onPress={onCloseCompendium} testID="dock-close" />
        </View>
        <CompendiumView panel={compendium} stacked />
      </View>
    );
  }
  if (!playing) {
    return (
      <View style={[styles.pane, { padding: space.md }]} testID="side-pane">
        <Text style={styles.dim}>The place and the party appear here once the adventure begins.</Text>
      </View>
    );
  }
  return (
    <View style={styles.pane} testID="side-pane">
      <View style={styles.top} testID="status-pane">
        <StatusSection panel={status} npc={npc?.name ?? null} onChoose={onChoose} />
      </View>
      <View style={styles.bottom} testID="details-pane">
        {npc ? <CompendiumView key={npc.name} panel={npc.panel} detailOnly /> : <Details panel={status} />}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  dim: { color: color.dim, fontFamily: font.ui, fontSize: 13 },
  pane: { flex: 1, backgroundColor: color.panel },
  top: { flex: 45, minHeight: 80 },
  bottom: { flex: 55, minHeight: 80, borderTopWidth: 1, borderTopColor: color.border },
  close: { position: "absolute", right: space.sm, top: 4, zIndex: 5 },
});
