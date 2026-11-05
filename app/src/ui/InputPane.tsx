import { useState } from "react";
import { Platform, StyleSheet, TextInput, TextInputKeyPressEvent, View } from "react-native";
import { Button } from "./controls";
import { color, font, radius, space } from "./theme";

/** Three times the height the field had (76 px): docs/LAYOUT.md 2.1. */
export const INPUT_HEIGHT = 228;

/** The player's reply: a multi-line field. Enter sends and Shift+Enter adds a line (on the web); a Stop button shows
 * over its corner while a turn runs. Slash commands may be typed while a turn is running, but a message waits until it ends. */
export function InputPane({
  busy,
  placeholder,
  onSubmit,
  onCancel,
  maxHeight = 400,
}: {
  busy: boolean;
  placeholder: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
  /** How tall the field may grow (docs/LAYOUT.md 2.1: 40% of the pane). */
  maxHeight?: number;
}) {
  const [value, setValue] = useState("");

  const send = () => {
    const text = value.trim();
    if (!text) return;
    if (busy && !text.startsWith("/")) return;
    setValue("");
    onSubmit(text);
  };

  const onKeyPress = (e: TextInputKeyPressEvent) => {
    if (Platform.OS !== "web") return;
    const ne = e.nativeEvent as unknown as { key: string; shiftKey?: boolean; isComposing?: boolean };
    if (ne.key === "Escape" && busy) {
      onCancel();
      return;
    }
    if (ne.key === "Enter" && !ne.shiftKey && !ne.isComposing) {
      (e as unknown as { preventDefault: () => void }).preventDefault();
      send();
    }
  };

  return (
    <View style={styles.wrap}>
      <TextInput
        testID="input"
        style={[styles.input, { maxHeight: Math.max(INPUT_HEIGHT, maxHeight) }]}
        multiline
        value={value}
        onChangeText={setValue}
        onKeyPress={onKeyPress}
        placeholder={placeholder}
        placeholderTextColor={color.dim}
        autoFocus
        blurOnSubmit={false}
        // the field grows a little with long text, then scrolls
        numberOfLines={9}
      />
      {busy ? (
        <View style={styles.stop}>
          <Button label="Stop" kind="danger" onPress={onCancel} testID="stop" />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: space.sm, borderTopWidth: 1, borderTopColor: color.border, backgroundColor: color.panel },
  input: {
    flex: 1,
    minHeight: INPUT_HEIGHT,
    color: color.text,
    fontFamily: font.story,
    fontSize: 16,
    lineHeight: 22,
    padding: space.sm,
    borderWidth: 1,
    borderColor: color.border,
    borderRadius: radius.md,
    backgroundColor: color.bg,
    textAlignVertical: "top",
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as object) : {}),
  },
  stop: { position: "absolute", right: space.md + 4, bottom: space.md + 4 },
});
