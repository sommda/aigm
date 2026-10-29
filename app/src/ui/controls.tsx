import { ReactNode, useEffect, useState } from "react";
import { Image, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { color, font, radius, selectable, space } from "./theme";

export function Button({
  label,
  onPress,
  kind = "plain",
  disabled,
  active,
  testID,
}: {
  label: string;
  onPress: () => void;
  kind?: "plain" | "primary" | "danger";
  disabled?: boolean;
  active?: boolean;
  testID?: string;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled}
      testID={testID}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.button,
        kind === "primary" && styles.primary,
        kind === "danger" && styles.danger,
        active && styles.active,
        hovered && !disabled && styles.hover,
        pressed && !disabled && styles.hover,
        disabled && { opacity: 0.4 },
      ]}
    >
      <Text style={[styles.label, kind === "primary" && { color: color.bg, fontWeight: "700" }, active && { color: color.accent }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function TabBar({
  tabs,
  current,
  onSelect,
}: {
  tabs: { id: string; title: string; badge?: string }[];
  current: string;
  onSelect: (id: string) => void;
}) {
  return (
    <View style={styles.tabs} accessibilityRole="tablist">
      {tabs.map((t) => (
        <Pressable
          key={t.id}
          accessibilityRole="tab"
          accessibilityState={{ selected: t.id === current }}
          onPress={() => onSelect(t.id)}
          testID={`tab-${t.id}`}
          style={[styles.tab, t.id === current && styles.tabOn]}
        >
          <Text style={[styles.tabText, t.id === current && styles.tabTextOn]}>
            {t.title}
            {t.badge ? <Text style={{ color: color.green }}>{"  " + t.badge}</Text> : null}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

export function Spinner({ on }: { on: boolean }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => setI((n) => (n + 1) % FRAMES.length), 90);
    return () => clearInterval(t);
  }, [on]);
  return <Text style={{ color: color.accent, width: 14 }}>{on ? FRAMES[i] : " "}</Text>;
}

export function Heading({ children }: { children: ReactNode }) {
  return <Text style={styles.heading}>{children}</Text>;
}

/** The letters in the frame shown while a portrait is on its way, or when its picture cannot be shown. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

/**
 * A character's portrait (the `portrait` of a character or compendium page): the picture once it is ready, a framed
 * set of initials while it is being painted, and nothing at all when none is coming. A picture that fails to load
 * falls back to the initials, never an error.
 */
export function Portrait({
  portrait,
  name,
  alt,
  resolve,
  maxWidth = 360,
  fitHeight = false,
}: {
  portrait: unknown;
  name: string;
  alt?: string;
  resolve: (path: string) => string;
  /** The widest a landscape picture of a place may be; it is narrower where the column is. */
  maxWidth?: number;
  /** Also keep a landscape picture to about a third of the window's height, so what is under it stays in view. */
  fitHeight?: boolean;
}) {
  const p = portrait as { state?: string; url?: string; shape?: string } | null | undefined;
  const [broken, setBroken] = useState(false);
  const { width, height } = useWindowDimensions();
  useEffect(() => setBroken(false), [p?.url]);
  if (!p || (p.state !== "ready" && p.state !== "pending")) return null;
  const landscape = p.shape === "landscape";
  // a person's portrait is a small square; a place's view is wide (3:2) and as large as the column allows
  const frame = landscape
    ? { width: "100%" as const, maxWidth: fitHeight ? Math.min(maxWidth, Math.round(height * 0.3 * 1.5)) : maxWidth, aspectRatio: 3 / 2 }
    : { width: width < 600 ? 120 : 160, height: width < 600 ? 120 : 160 };
  if (p.state === "ready" && p.url && !broken) {
    return (
      <Image
        testID={landscape ? "view" : "portrait"}
        source={{ uri: resolve(p.url) }}
        style={[styles.portrait, frame]}
        resizeMode="cover"
        accessibilityLabel={alt || name}
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <View testID={landscape ? "view-placeholder" : "portrait-placeholder"} style={[styles.portrait, styles.frame, frame]}>
      <Text style={landscape ? styles.placeName : styles.initials}>{landscape ? name : initials(name)}</Text>
      {p.state === "pending" ? <Text style={styles.painting}>{landscape ? "Painting a view…" : "Painting a portrait…"}</Text> : null}
    </View>
  );
}

/** How a person looks (the `look` of a character or compendium page); nothing when there is none. */
export function LookBlock({ look, title = "Appearance" }: { look: unknown; title?: string }) {
  const l = look as { summary?: string; description?: string } | null | undefined;
  if (!l || !l.description) return null;
  return (
    <View testID="look">
      <Heading>{title}</Heading>
      <Text style={[styles.look, selectable]}>{l.description}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  portrait: { borderRadius: radius.sm, borderWidth: 1, borderColor: color.border, backgroundColor: color.panelAlt },
  frame: { alignItems: "center", justifyContent: "center" },
  initials: { color: color.dim, fontFamily: font.story, fontSize: 40 },
  placeName: { color: color.dim, fontFamily: font.story, fontSize: 22, textAlign: "center", paddingHorizontal: space.md },
  painting: { color: color.dim, fontFamily: font.ui, fontSize: 11, marginTop: space.xs, textAlign: "center" },
  look: { color: color.text, fontFamily: font.story, fontSize: 15, lineHeight: 22 },
  button: {
    paddingHorizontal: space.md,
    paddingVertical: 6,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: color.border,
    backgroundColor: color.panelAlt,
  },
  primary: { backgroundColor: color.accent, borderColor: color.accent },
  danger: { borderColor: color.red },
  active: { borderColor: color.accent },
  hover: { backgroundColor: "#322a21" },
  label: { color: color.text, fontFamily: font.ui, fontSize: 14 },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: 2, paddingHorizontal: space.sm, paddingTop: space.xs },
  tab: { paddingHorizontal: space.md, paddingVertical: 6, borderBottomWidth: 2, borderBottomColor: "transparent" },
  tabOn: { borderBottomColor: color.accent },
  tabText: { color: color.dim, fontFamily: font.ui, fontSize: 14 },
  tabTextOn: { color: color.text, fontWeight: "700" },
  heading: { color: color.accent, fontFamily: font.ui, fontWeight: "700", fontSize: 14, marginTop: space.md, marginBottom: 2 },
});
