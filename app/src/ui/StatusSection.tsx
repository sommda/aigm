import { useState } from "react";
import { LayoutChangeEvent, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Json } from "../core/events";
import { hpTone, shortHeadline } from "../core/party";
import { StatusPanel } from "../core/panels";
import { CHARACTER_PREFIX, STATUS_TAB } from "../core/statusModel";
import { Portrait } from "./controls";
import { color, font, selectable, space } from "./theme";
import { useStore } from "./useStore";

const TONE = { ok: color.green, low: color.yellow, critical: color.red, unknown: color.dim };

/** The top of the right pane (docs/LAYOUT.md 4): the place with its picture, then one row per party member. Clicking
 * the place or a member chooses what the details below show. */
export function StatusSection({
  panel,
  npc,
  onChoose,
}: {
  panel: StatusPanel;
  /** The person whose compendium entry the details show, if any. */
  npc: string | null;
  /** The player chose something: a person (by name), or the place or a party member (null). */
  onChoose: (npc: string | null) => void;
}) {
  useStore(panel);
  const [height, setHeight] = useState(0);
  const m = panel.model;
  const place = m.place as Json | undefined;
  const loc = place?.location as Json | undefined;
  const path = ((loc?.path as Json[] | undefined) ?? []).map((p) => String(p.name));
  const where = path.length ? "in " + [...path].reverse().join(", ") : "";
  const when = loc?.time ? `${loc.time} · ${loc.period}` : "";
  const sub = [where, when].filter(Boolean).join("  ·  ");
  const here = ((place?.here as Json[] | undefined) ?? []).filter((e) => e && typeof e.name === "string");
  const look = loc?.look as Json | null | undefined;
  return (
    <ScrollView style={styles.wrap} onLayout={(e: LayoutChangeEvent) => setHeight(e.nativeEvent.layout.height)} contentContainerStyle={{ padding: space.md }} testID="status-section">
      {panel.error ? (
        <Text style={{ color: color.red }}>{panel.error}</Text>
      ) : !loc ? (
        <Text style={styles.dim}>{panel.loading ? "Loading…" : "The party's location has not been recorded yet."}</Text>
      ) : (
        <Pressable onPress={() => {
          onChoose(null);
          void panel.showPlace();
        }}
          testID="status-place"
          style={[styles.place, !npc && m.tab === STATUS_TAB && styles.on]}>
          <Text style={[styles.name, selectable]}>{String(loc.name)}</Text>
          {sub ? <Text style={styles.dim}>{sub}</Text> : null}
          {loc.portrait ? (
            <View style={{ marginTop: space.sm }}>
              <Portrait portrait={loc.portrait} name={String(loc.name)} alt={look ? String(look.summary ?? "") : undefined} resolve={(p) => panel.imageUrl(p)} maxWidth={520} maxHeight={height ? Math.round(height * 0.55) : undefined} />
            </View>
          ) : null}
        </Pressable>
      )}
      {m.roster.map((c) => {
        const name = String(c.name);
        const tab = CHARACTER_PREFIX + name;
        const conditions = (c.conditions as string[] | undefined) ?? [];
        return (
          <Pressable key={name} onPress={() => {
              onChoose(null);
              void panel.switchTo(tab);
            }}
            testID={`party-${name}`}
            style={[styles.member, !npc && m.tab === tab && styles.on]}>
            <Text style={styles.memberName} numberOfLines={1}>
              {name.split(/\s+/)[0]}
            </Text>
            <Text style={styles.headline} numberOfLines={1}>
              {shortHeadline(c.headline)}
            </Text>
            <Text style={[styles.hp, { color: TONE[hpTone(c.hp)] }]}>{c.hp ? String(c.hp) : ""}</Text>
            {conditions.length ? <Text style={styles.conditions} numberOfLines={1}>{conditions.join(", ")}</Text> : null}
          </Pressable>
        );
      })}
      {here.length ? (
        <View testID="status-here" style={styles.here}>
          <Text style={styles.hereHead}>Here</Text>
          {here.map((e, i) => (
            <Pressable
              key={String(e.id ?? i)}
              onPress={() => onChoose(String(e.name))}
              testID={`here-${e.name}`}
              style={[styles.hereRow, npc === e.name && styles.on]}
            >
              <Text style={styles.hereName} numberOfLines={1}>
                {String(e.name)}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  place: { paddingBottom: space.sm, marginBottom: space.sm, borderRadius: 6 },
  on: { backgroundColor: color.panelAlt },
  name: { color: color.text, fontFamily: font.story, fontSize: 20, fontWeight: "700" },
  dim: { color: color.dim, fontFamily: font.ui, fontSize: 13 },
  member: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: 5, paddingHorizontal: space.sm, borderRadius: 6 },
  memberName: { color: color.text, fontFamily: font.ui, fontSize: 15, fontWeight: "700", minWidth: 80 },
  headline: { color: color.dim, fontFamily: font.ui, fontSize: 13, flex: 1 },
  hp: { fontFamily: font.ui, fontSize: 14, fontWeight: "700" },
  here: { marginTop: space.sm },
  hereHead: { paddingHorizontal: space.sm, color: color.accent, fontFamily: font.ui, fontWeight: "700", fontSize: 13, marginBottom: 2 },
  hereRow: { paddingHorizontal: space.sm, paddingVertical: 2, borderRadius: 6 },
  hereName: { color: color.text, fontFamily: font.ui, fontSize: 14, paddingVertical: 1 },
  conditions: { color: color.yellow, fontFamily: font.ui, fontSize: 12, maxWidth: 120 },
});
