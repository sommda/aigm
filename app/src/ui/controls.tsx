import { ReactNode, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { color, font, radius, space } from "./theme";

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

const styles = StyleSheet.create({
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
