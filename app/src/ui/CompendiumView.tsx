import { useEffect, useRef, useState } from "react";
import { LayoutChangeEvent, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { HIDDEN, TITLES } from "../core/compendiumModel";
import { Json } from "../core/events";
import { CompendiumPanel } from "../core/panels";
import { Button, Heading, LookBlock, TabBar } from "./controls";
import { color, font, radius, selectable, space } from "./theme";
import { useStore } from "./useStore";

const WIDE = 700;
const STATUS_COLOR: Record<string, string> = { new: color.green, updated: color.yellow };

function Row({ entry, selected, read, hidden, onPress }: { entry: Json; selected: boolean; read: boolean; hidden: boolean; onPress: () => void }) {
  const status = entry.status as string | undefined;
  const tint = status && !read ? STATUS_COLOR[status] : read ? color.dim : color.text;
  const total = ["hidden_count", "hinted_count", "motive_count"].reduce((n, k) => n + (Number(entry[k]) || 0), 0);
  return (
    <Pressable onPress={onPress} testID={`entry-${entry.id}`} style={[styles.row, selected && styles.rowOn]}>
      <Text style={[styles.rowText, { color: tint, paddingLeft: (Number(entry.depth) || 0) * 14 }]} numberOfLines={1}>
        {status ? "✦ " : ""}
        {String(entry.name)}
      </Text>
      <Text style={[styles.rowTag, status && !read ? { color: tint } : null]}>
        {hidden ? `${entry.kind ?? ""} ${total}` : status && !read ? status : ""}
      </Text>
    </Pressable>
  );
}

function FactLines({ fact, newMark, indent }: { fact: Json; newMark: boolean; indent: boolean }) {
  const via = (fact.via as string[] | undefined) ?? [];
  return (
    <Text style={[styles.fact, indent && { paddingLeft: space.md }, newMark && { color: color.green }, selectable]}>
      {newMark ? "✦ " : ""}
      {String(fact.text)}
      {via.length ? <Text style={{ color: color.dim }}>{`  · ${via.join(", ")}`}</Text> : null}
    </Text>
  );
}

function Detail({ panel }: { panel: CompendiumPanel }) {
  const m = panel.model;
  const entry = m.current;
  const d = m.currentDetail;
  if (!entry) return <Text style={styles.dim}>Select an entry.</Text>;
  if (!d) return <Text style={styles.dim}>Loading…</Text>;
  if (m.onHidden) return <HiddenDetail d={d} />;
  const facts = ((d.facts as Json[]) ?? []).filter(Boolean);
  const plain = facts.filter((f) => !f.label);
  const labelled = facts.filter((f) => f.label);
  const read = m.read.has(String(d.id));
  const path = ((d.path as Json[]) ?? []).map((p) => p.name).join(" › ");
  let heading: unknown = null;
  let linkHeading: string | null = null;
  return (
    <View testID="compendium-detail">
      <Text style={styles.title}>
        {String(d.name)}
        <Text style={styles.kind}>{`  ${d.kind ?? ""}`}</Text>
      </Text>
      {path ? <Text style={styles.dim}>{"in " + path}</Text> : null}
      {(d.aliases as string[] | undefined)?.length ? <Text style={styles.dim}>{"also called: " + (d.aliases as string[]).join(", ")}</Text> : null}
      <LookBlock look={d.look} />
      {plain.length ? <View style={{ marginTop: space.sm }}>{plain.map((f, i) => <FactLines key={i} fact={f} newMark={!!f.new && !read} indent={false} />)}</View> : null}
      {labelled.map((f, i) => {
        const show = f.label !== heading;
        heading = f.label;
        return (
          <View key={i}>
            {show ? <Heading>{String(f.label)}</Heading> : null}
            <FactLines fact={f} newMark={!!f.new && !read} indent />
          </View>
        );
      })}
      {m.links().map((l, i) => {
        const show = l.heading !== linkHeading;
        linkHeading = l.heading;
        const status = l.target.status as string | undefined;
        return (
          <View key={i}>
            {show ? <Heading>{l.heading}</Heading> : null}
            <Pressable onPress={() => void panel.follow(l.target)} testID={`link-${l.target.id}`}>
              <Text style={styles.link}>
                {"→ " + String(l.target.name)}
                <Text style={{ color: status ? STATUS_COLOR[status] : color.dim }}>{`  ${l.target.kind ?? ""}${status ? "  " + status : ""}`}</Text>
              </Text>
            </Pressable>
          </View>
        );
      })}
    </View>
  );
}

function HiddenDetail({ d }: { d: Json }) {
  const motives = (d.motives as Json[]) ?? [];
  const facts = (d.facts as Json[]) ?? [];
  return (
    <View testID="hidden-detail">
      <Text style={styles.title}>
        {String(d.name)}
        <Text style={styles.kind}>{`  ${d.kind ?? ""}`}</Text>
      </Text>
      <Text style={styles.dim}>
        {[d.discovered ? "the player has met this" : "the player has not discovered this", d.parent ? "in " + (d.parent as Json).name : "", (d.aliases as string[] | undefined)?.length ? "also called: " + (d.aliases as string[]).join(", ") : ""]
          .filter(Boolean)
          .join(" · ")}
      </Text>
      {motives.length ? <Text style={[styles.hHead, { color: color.magenta }]}>Motives</Text> : null}
      {motives.map((m, i) => {
        const quals = ["strength", "scope", "disclosure"].map((k) => m[k]).filter(Boolean);
        if (m.status && m.status !== "active") quals.push(m.status);
        return (
          <View key={i} style={{ marginBottom: space.sm }}>
            <Text style={{ color: color.magenta, fontFamily: font.ui, fontWeight: "700" }}>
              {String(m.kind ?? "motive")}
              <Text style={styles.dim}>{quals.length ? `  (${quals.join(", ")})` : ""}</Text>
            </Text>
            <Text style={[styles.fact, selectable]}>{String(m.text ?? "")}</Text>
            {([["Moved by", "moved_by"], ["Resists", "resists"], ["Tells", "tells"]] as const).map(([label, key]) =>
              (m[key] as string[] | undefined)?.length ? (
                <Text key={key} style={[styles.dim, selectable]}>{`${label}: ${(m[key] as string[]).join("; ")}`}</Text>
              ) : null,
            )}
          </View>
        );
      })}
      {(["hidden", "hinted"] as const).map((level) => {
        const list = facts.filter((f) => f.disclosure === level);
        if (!list.length) return null;
        return (
          <View key={level}>
            <Text style={[styles.hHead, { color: level === "hinted" ? color.yellow : color.accent }]}>{level === "hinted" ? "Hinted facts" : "Hidden facts"}</Text>
            {list.map((f, i) => {
              const others = ((f.about as Json[]) ?? []).filter((a) => a.id !== d.id).map((a) => a.name);
              return (
                <View key={i} style={{ marginBottom: space.sm }}>
                  <Text style={[styles.fact, selectable]}>{(f.label ? `${f.label}: ` : "") + String(f.text)}</Text>
                  <Text style={styles.dim}>
                    {[f.id, f.source, others.length ? "also about " + others.join(", ") : ""].filter(Boolean).join(" · ")}
                  </Text>
                </View>
              );
            })}
          </View>
        );
      })}
      {!motives.length && !facts.length ? <Text style={styles.dim}>Nothing hidden.</Text> : null}
    </View>
  );
}

/** What the player has learned about the world: tabs, a list and the entry under the cursor. */
export function CompendiumView({ panel }: { panel: CompendiumPanel }) {
  useStore(panel);
  const [width, setWidth] = useState(1000);
  const [showDetail, setShowDetail] = useState(false);
  const [query, setQuery] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    panel.start();
    return () => {
      void panel.close();
    };
  }, [panel]);

  const m = panel.model;
  const wide = width >= WIDE;
  const tabs = m.tabs.map((id) => {
    const unread = id === HIDDEN ? 0 : m.unreadCount(id);
    return { id, title: `${TITLES[id]} (${m.counts[id].count})`, badge: unread ? `✦${unread}` : undefined };
  });

  const onQuery = (text: string) => {
    setQuery(text);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void panel.setQuery(text), 250);
  };

  const list = (
    <ScrollView style={wide ? styles.list : { flex: 1 }} testID="compendium-list">
      {m.entries.length === 0 ? (
        <Text style={[styles.dim, { padding: space.md }]}>{m.query || m.unseenOnly ? "No entries match." : "Nothing is known yet."}</Text>
      ) : (
        m.entries.map((e, i) => (
          <Row
            key={String(e.id)}
            entry={e}
            selected={i === Math.min(m.cursor[m.tab], m.entries.length - 1)}
            read={m.read.has(String(e.id))}
            hidden={m.onHidden}
            onPress={() => {
              void panel.selectIndex(i);
              setShowDetail(true);
            }}
          />
        ))
      )}
    </ScrollView>
  );
  const detail = (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: space.lg }}>
      {!wide ? (
        <View style={{ flexDirection: "row", gap: space.sm, marginBottom: space.sm }}>
          <Button label="‹ List" onPress={() => setShowDetail(false)} testID="back-to-list" />
          {m.trail.length ? <Button label="Back" onPress={() => void panel.back()} /> : null}
        </View>
      ) : m.trail.length ? (
        <View style={{ marginBottom: space.sm }}>
          <Button label="‹ Back" onPress={() => void panel.back()} />
        </View>
      ) : null}
      <Detail panel={panel} />
    </ScrollView>
  );

  return (
    <View style={styles.wrap} onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} testID="compendium-view">
      <TabBar tabs={tabs} current={m.tab} onSelect={(id) => { void panel.switchTab(id); setShowDetail(false); }} />
      <View style={styles.tools}>
        <TextInput
          testID="compendium-filter"
          value={query}
          onChangeText={onQuery}
          placeholder="Filter by name"
          placeholderTextColor={color.dim}
          style={styles.filter}
        />
        {!m.onHidden ? <Button label="Unread only" active={m.unseenOnly} onPress={() => void panel.toggleUnseen()} testID="unread-only" /> : null}
        {!m.onHidden ? <Button label="Next unread" onPress={() => void panel.nextUnread()} testID="next-unread" /> : null}
        {!m.onHidden ? <Button label="Mark all read" onPress={() => void panel.markAllRead()} testID="mark-all-read" /> : null}
        <Button label="Refresh" onPress={() => void panel.load()} testID="compendium-refresh" />
      </View>
      {panel.error ? <Text style={{ color: color.red, padding: space.md }}>{panel.error}</Text> : null}
      {panel.notice ? <Text style={{ color: color.yellow, paddingHorizontal: space.md }}>{panel.notice}</Text> : null}
      {wide ? (
        <View style={{ flex: 1, flexDirection: "row" }}>
          {list}
          {detail}
        </View>
      ) : showDetail ? (
        detail
      ) : (
        list
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  tools: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, alignItems: "center", paddingHorizontal: space.sm, paddingVertical: space.sm },
  filter: {
    minWidth: 160,
    color: color.text,
    fontFamily: font.ui,
    fontSize: 14,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    paddingVertical: 5,
    backgroundColor: color.bg,
  },
  list: { width: 300, borderRightWidth: 1, borderRightColor: color.border },
  row: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: space.md, paddingVertical: 6 },
  rowOn: { backgroundColor: color.panelAlt },
  rowText: { flex: 1, color: color.text, fontFamily: font.ui, fontSize: 14 },
  rowTag: { color: color.dim, fontFamily: font.ui, fontSize: 12, marginLeft: space.sm },
  title: { color: color.text, fontFamily: font.story, fontSize: 22, fontWeight: "700" },
  kind: { color: color.dim, fontFamily: font.ui, fontSize: 13, fontWeight: "400" },
  dim: { color: color.dim, fontFamily: font.ui, fontSize: 13 },
  fact: { color: color.text, fontFamily: font.story, fontSize: 15, lineHeight: 22, marginBottom: 4 },
  link: { color: color.text, fontFamily: font.ui, fontSize: 14, paddingVertical: 3 },
  hHead: { fontFamily: font.ui, fontWeight: "700", fontSize: 14, marginTop: space.md, marginBottom: 2 },
});
