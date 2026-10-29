import { useState } from "react";
import { Platform, StyleSheet, TextInput, TextInputKeyPressEvent, View } from "react-native";
import { Button } from "./controls";
import { color, font, radius, space } from "./theme";

/** The player's reply: a multi-line field. Enter sends and Shift+Enter adds a line (on the web); the Send button
 * always works. Slash commands may be typed while a turn is running, but a message waits until it ends. */
export function InputPane({
  busy,
  placeholder,
  onSubmit,
  onCancel,
}: {
  busy: boolean;
  placeholder: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
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
    if (ne.key === "Enter" && !ne.shiftKey && !ne.isComposing) {
      (e as unknown as { preventDefault: () => void }).preventDefault();
      send();
    }
  };

  return (
    <View style={styles.wrap}>
      <TextInput
        testID="input"
        style={styles.input}
        multiline
        value={value}
        onChangeText={setValue}
        onKeyPress={onKeyPress}
        placeholder={placeholder}
        placeholderTextColor={color.dim}
        autoFocus
        blurOnSubmit={false}
        // the field grows a little with long text, then scrolls
        numberOfLines={3}
      />
      <View style={styles.buttons}>
        {busy ? <Button label="Stop" kind="danger" onPress={onCancel} testID="stop" /> : null}
        <Button label="Send" kind="primary" onPress={send} disabled={!value.trim() || (busy && !value.trim().startsWith("/"))} testID="send" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", gap: space.sm, padding: space.sm, borderTopWidth: 1, borderTopColor: color.border, backgroundColor: color.panel, alignItems: "flex-end" },
  input: {
    flex: 1,
    minHeight: 76,
    maxHeight: 160,
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
  buttons: { gap: space.xs },
});
