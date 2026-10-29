import { useEffect, useMemo } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { Json } from "../core/events";
import { StatusPanel } from "../core/panels";
import { Button, Heading, TabBar } from "./controls";
import { color, font, selectable, space } from "./theme";
import { useStore } from "./useStore";

const arr = (v: unknown): Json[] => (Array.isArray(v) ? (v as Json[]) : []);

function Named({ name, text }: { name: string; text?: string }) {
  return (
    <Text style={[styles.body, selectable]}>
      {"• "}
      <Text style={styles.strong}>{name}</Text>
      {text ? ` — ${text}` : ""}
    </Text>
  );
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <View style={styles.table}>
      <View style={styles.tr}>
        {columns.map((c, i) => (
          <Text key={i} style={[styles.th, i === columns.length - 1 ? styles.last : styles.cell]}>
            {c}
          </Text>
        ))}
      </View>
      {rows.map((row, r) => (
        <View key={r} style={styles.tr}>
          {row.map((c, i) => (
            <Text key={i} style={[styles.body, i === 0 && styles.strong, i === row.length - 1 ? styles.last : styles.cell, selectable]}>
              {String(c)}
            </Text>
          ))}
        </View>
      ))}
    </View>
  );
}

function Place({ page }: { page: Json }) {
  const loc = page.location as Json | undefined;
  const table = (page.table as Json | undefined) ?? {};
  if (!loc) return <Text style={styles.dim}>The party's location has not been recorded yet.</Text>;
  const path = arr(loc.path).map((p) => String(p.name));
  const where = path.length ? "in " + [...path].reverse().join(", ") : "";
  const when = loc.time ? `${loc.time} · ${loc.period}` : "";
  const sub = [where, when].filter(Boolean).join("  ·  ");
  return (
    <View>
      <Text style={[styles.name, selectable]}>{String(loc.name)}</Text>
      {sub ? <Text style={styles.dim}>{sub}</Text> : null}
      {loc.overview ? <Text style={[styles.body, { marginTop: space.sm }, selectable]}>{String(loc.overview)}</Text> : null}
      {arr(page.here).length ? <Heading>Here</Heading> : null}
      {arr(page.here).map((e, i) => (
        <Named key={i} name={String(e.name)} text={e.summary as string | undefined} />
      ))}
      {arr(page.items).length ? <Heading>Key items</Heading> : null}
      {(page.items as string[] | undefined)?.map((it, i) => (
        <Text key={i} style={[styles.body, selectable]}>
          {"• " + it}
        </Text>
      ))}
      {arr(page.inside).length ? <Heading>Inside</Heading> : null}
      {arr(page.inside).map((e, i) => (
        <Named key={i} name={String(e.name)} text={e.summary as string | undefined} />
      ))}
      {arr(page.exits).length ? <Heading>Ways out</Heading> : null}
      {arr(page.exits).map((e, i) => (
        <Named key={i} name={String(e.name)} text={e.route as string | undefined} />
      ))}
      {arr(table.rows).length || (table.rows as unknown[] | undefined)?.length ? (
        <>
          <Heading>{page.combat ? "The fight" : "Everyone here"}</Heading>
          <Table columns={(table.columns as string[]) ?? []} rows={(table.rows as string[][]) ?? []} />
        </>
      ) : null}
    </View>
  );
}

function Sheet({ page }: { page: Json }) {
  return (
    <View>
      <Text style={[styles.name, selectable]}>{String(page.name)}</Text>
      {page.headline ? <Text style={[styles.body, selectable]}>{String(page.headline)}</Text> : null}
      {page.hp || arr(page.conditions).length || (page.conditions as string[] | undefined)?.length ? (
        <Text style={styles.body}>
          {page.hp ? <Text style={{ color: color.green, fontWeight: "700" }}>{`HP ${page.hp}`}</Text> : null}
          {(page.conditions as string[] | undefined)?.length ? (
            <Text style={{ color: color.yellow }}>{`  ${(page.conditions as string[]).join(", ")}`}</Text>
          ) : null}
        </Text>
      ) : null}
      {page.progress ? <Text style={styles.dim}>{String(page.progress)}</Text> : null}
      {arr(page.sections).map((sec, i) => (
        <View key={i}>
          <Heading>{String(sec.title)}</Heading>
          {(sec.lines as string[]).map((line, j) => (
            <Text key={j} style={[styles.body, { paddingLeft: space.sm }, selectable]}>
              {line}
            </Text>
          ))}
        </View>
      ))}
      {page.text ? (
        <View>
          <Heading>Sheet</Heading>
          <Text style={styles.dim}>No tidy version of this sheet was written; here it is as the GM wrote it.</Text>
          <Text style={[styles.body, selectable]}>{String(page.text)}</Text>
        </View>
      ) : null}
    </View>
  );
}

/** Where the party is, who is there and how everyone is doing. A tab for the place and one for each character. */
export function StatusView({ panel }: { panel: StatusPanel }) {
  useStore(panel);
  useEffect(() => {
    void panel.load();
  }, [panel]);
  const m = panel.model;
  const tabs = useMemo(() => m.tabs.map(([id, title]) => ({ id, title })), [m.tabs]);
  const page = m.page;
  return (
    <View style={styles.wrap} testID="status-view">
      <View style={styles.head}>
        <View style={{ flex: 1 }}>
          <TabBar tabs={tabs} current={m.tab} onSelect={(id) => void panel.switchTo(id)} />
        </View>
        <Button label="Refresh" onPress={() => void panel.load()} testID="status-refresh" />
      </View>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.body_}>
        {panel.error ? (
          <Text style={{ color: color.red }}>{panel.error}</Text>
        ) : !page ? (
          <Text style={styles.dim}>{panel.loading ? "Loading…" : ""}</Text>
        ) : m.character ? (
          <Sheet page={page} />
        ) : (
          <Place page={page} />
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  head: { flexDirection: "row", alignItems: "center", paddingRight: space.sm, gap: space.sm },
  body_: { padding: space.lg, maxWidth: 860, width: "100%", alignSelf: "center" },
  name: { color: color.text, fontFamily: font.story, fontSize: 22, fontWeight: "700" },
  body: { color: color.text, fontFamily: font.story, fontSize: 15, lineHeight: 22 },
  strong: { fontWeight: "700" },
  dim: { color: color.dim, fontFamily: font.ui, fontSize: 13 },
  table: { marginTop: 4 },
  tr: { flexDirection: "row", gap: space.md, paddingVertical: 2 },
  th: { color: color.dim, fontFamily: font.ui, fontSize: 12, fontWeight: "700" },
  cell: { width: 140 },
  last: { flex: 1 },
});
