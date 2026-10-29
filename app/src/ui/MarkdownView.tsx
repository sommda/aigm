import { memo } from "react";
import { StyleSheet, Text, View } from "react-native";
import { MdBlock, Span, parseMarkdown } from "../core/markdown";
import { color, font, selectable, space, text } from "./theme";

function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((s, i) => (
        <Text
          key={i}
          style={[
            s.bold && styles.bold,
            s.italic && styles.italic,
            s.strike && styles.strike,
            s.code && styles.code,
          ]}
        >
          {s.text}
        </Text>
      ))}
    </>
  );
}

function Block({ block }: { block: MdBlock }) {
  switch (block.kind) {
    case "paragraph":
      return (
        <Text style={[text.body, styles.paragraph, selectable]}>
          <Spans spans={block.spans} />
        </Text>
      );
    case "heading":
      return (
        <Text style={[text.body, styles.paragraph, styles.heading, { fontSize: block.level <= 1 ? 22 : block.level === 2 ? 20 : 18 }, selectable]}>
          <Spans spans={block.spans} />
        </Text>
      );
    case "list":
      return (
        <View style={styles.paragraph}>
          {block.items.map((item, i) => (
            <View key={i} style={styles.item}>
              <Text style={[text.body, styles.marker]}>{block.ordered ? `${block.start + i}.` : "•"}</Text>
              <Text style={[text.body, styles.itemText, selectable]}>
                <Spans spans={item} />
              </Text>
            </View>
          ))}
        </View>
      );
    case "quote":
      return (
        <View style={[styles.paragraph, styles.quote]}>
          <Text style={[text.body, styles.italic, { color: color.dim }, selectable]}>
            <Spans spans={block.spans} />
          </Text>
        </View>
      );
    case "code":
      return (
        <View style={[styles.paragraph, styles.codeBlock]}>
          <Text style={[styles.mono, selectable]}>{block.text}</Text>
        </View>
      );
    case "rule":
      return <View style={styles.rule} />;
    case "table": {
      const widths = block.rows[0].map((_, c) => Math.max(...block.rows.map((r) => (r[c] ?? "").length)));
      return (
        <View style={[styles.paragraph, styles.codeBlock]}>
          {block.rows.map((row, r) => (
            <Text key={r} style={[styles.mono, r === 0 && styles.bold, selectable]}>
              {row.map((cell, c) => cell.padEnd(widths[c])).join("   ")}
            </Text>
          ))}
        </View>
      );
    }
  }
}

/** The GM's narration. While a reply is still arriving (`final` false) it is parsed tolerantly. */
export const MarkdownView = memo(function MarkdownView({ raw, final, version }: { raw: string; final: boolean; version: number }) {
  void version; // the block is changed in place; the version tells memo it is different
  const blocks = parseMarkdown(raw, !final);
  return (
    <View style={styles.wrap}>
      {blocks.map((b, i) => (
        <Block key={i} block={b} />
      ))}
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { marginVertical: space.xs },
  paragraph: { marginBottom: space.sm },
  heading: { fontWeight: "700", color: color.accent },
  bold: { fontWeight: "700" },
  italic: { fontStyle: "italic" },
  strike: { textDecorationLine: "line-through" },
  code: { fontFamily: font.mono, backgroundColor: color.code, color: color.yellow },
  mono: { fontFamily: font.mono, fontSize: 14, color: color.text },
  item: { flexDirection: "row" },
  marker: { width: 24 },
  itemText: { flex: 1 },
  quote: { borderLeftWidth: 3, borderLeftColor: color.border, paddingLeft: space.md },
  codeBlock: { backgroundColor: color.code, padding: space.sm, borderRadius: 4 },
  rule: { height: 1, backgroundColor: color.border, marginVertical: space.md },
});
