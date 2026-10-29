import { ComponentRef, memo, useCallback, useEffect, useRef } from "react";
import { NativeScrollEvent, NativeSyntheticEvent, ScrollView, StyleSheet, Text, View } from "react-native";
import { Block, Tone, stripMarkup } from "../core/blocks";
import { ChatSession } from "../core/session";
import { MarkdownView } from "./MarkdownView";
import { color, font, selectable, space, text } from "./theme";

const TONES: Record<Tone, object> = {
  dim: { color: color.dim },
  green: { color: color.green },
  "bold-green": { color: color.green, fontWeight: "700" },
  red: { color: color.red },
  yellow: { color: color.yellow },
};

function DiceLine({ block }: { block: Extract<Block, { kind: "dice" }> }) {
  const ev = block.event;
  return (
    <Text style={[styles.dice, selectable]}>
      {"🎲 "}
      <Text style={styles.diceExpr}>{ev.expression}</Text>
      {ev.dice.length > 0 ? (
        <>
          {"  →  "}
          {ev.dice.map((term, ti) => (
            <Text key={ti}>
              {ti ? "; " : ""}
              {term.notation}:{" "}
              {term.rolls.map((r, ri) => (
                <Text key={ri} style={r.kept ? styles.kept : styles.dropped}>
                  {ri ? " " : ""}[{r.value}]
                </Text>
              ))}
            </Text>
          ))}
        </>
      ) : ev.result ? (
        <>{"  →  " + stripMarkup(ev.result)}</>
      ) : null}
      {ev.total !== null ? <Text style={styles.total}>{"  =  " + ev.total}</Text> : null}
      {ev.crit === "crit" ? <Text style={styles.crit}>{"  CRITICAL!"}</Text> : null}
      {ev.crit === "fail" ? <Text style={styles.fumble}>{"  FUMBLE!"}</Text> : null}
      {ev.comment ? <Text style={{ color: color.dim }}>{"  # " + ev.comment}</Text> : null}
    </Text>
  );
}

const BlockView = memo(
  function BlockView({ block, version, showReasoning }: { block: Block; version: number; showReasoning: boolean }) {
    void version;
    switch (block.kind) {
      case "user":
        return (
          <View style={styles.user}>
            <Text style={[text.body, { color: color.user }, selectable]}>
              <Text style={{ fontWeight: "700" }}>You: </Text>
              {block.text}
            </Text>
          </View>
        );
      case "markdown":
        return <MarkdownView raw={block.raw} final={block.final} version={block.version} />;
      case "reasoning":
        return showReasoning && block.text.trim() ? (
          <Text style={[styles.reasoning, selectable]}>
            <Text style={{ fontWeight: "700" }}>Reasoning: </Text>
            {block.text.trim()}
          </Text>
        ) : null;
      case "system":
        return <Text style={[styles.system, TONES[block.tone], selectable]}>{block.text}</Text>;
      case "dice":
        return <DiceLine block={block} />;
    }
  },
  (a, b) => a.block === b.block && a.version === b.version && a.showReasoning === b.showReasoning,
);

/** The story: one large scrolling pane. It follows the newest text unless the player has scrolled up to read. */
export function Transcript({ session, showReasoning }: { session: ChatSession; showReasoning: boolean }) {
  const ref = useRef<ComponentRef<typeof ScrollView>>(null);
  const stick = useRef(true);
  const blocks = session.blocks;
  const last = blocks[blocks.length - 1];

  const onScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    stick.current = contentSize.height - (contentOffset.y + layoutMeasurement.height) < 48;
  }, []);

  // a new player message always brings the view back to the bottom
  useEffect(() => {
    if (last?.kind === "user") stick.current = true;
  }, [last?.id, last?.kind]);

  return (
    <ScrollView
      ref={ref}
      style={styles.scroll}
      contentContainerStyle={styles.content}
      onScroll={onScroll}
      scrollEventThrottle={32}
      onContentSizeChange={() => {
        if (stick.current) ref.current?.scrollToEnd({ animated: false });
      }}
      testID="transcript"
    >
      {blocks.map((b) => (
        <BlockView key={b.id} block={b} version={b.version} showReasoning={showReasoning} />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: color.bg },
  content: { padding: space.lg, paddingBottom: space.xl, maxWidth: 860, width: "100%", alignSelf: "center" },
  user: { marginTop: space.md, marginBottom: space.sm, paddingLeft: space.md, borderLeftWidth: 3, borderLeftColor: color.user },
  system: { fontFamily: font.ui, fontSize: 14, lineHeight: 20, marginVertical: 2 },
  reasoning: { fontFamily: font.ui, fontSize: 13, fontStyle: "italic", color: color.dim, marginVertical: space.xs },
  dice: { fontFamily: font.ui, fontSize: 15, color: color.yellow, marginVertical: space.xs },
  diceExpr: { fontWeight: "700" },
  kept: { fontWeight: "700", color: color.text },
  dropped: { color: color.dim, textDecorationLine: "line-through" },
  total: { fontWeight: "700", color: color.text },
  crit: { fontWeight: "700", color: color.green },
  fumble: { fontWeight: "700", color: color.red },
});
