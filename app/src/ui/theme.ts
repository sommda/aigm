/** Design tokens. Every component reads these; none hard-codes a colour (docs/ART.md 8). */

import { Platform, TextStyle } from "react-native";

export const color = {
  bg: "#14110f",
  panel: "#1c1814",
  panelAlt: "#241f19",
  border: "#3a3128",
  text: "#e8dfcf",
  dim: "#8c8374",
  accent: "#c9a44c",
  user: "#7fb4c9",
  green: "#7fae6a",
  red: "#d46a5a",
  yellow: "#d9b45a",
  magenta: "#b98ac2",
  code: "#1a1713",
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
export const radius = { sm: 4, md: 8 };

export const font = {
  story: Platform.select({ web: "Georgia, 'Times New Roman', serif", ios: "Georgia", default: "serif" }) as string,
  ui: Platform.select({ web: "system-ui, -apple-system, 'Segoe UI', sans-serif", default: undefined }) as string | undefined,
  mono: Platform.select({ web: "ui-monospace, Menlo, Consolas, monospace", ios: "Menlo", default: "monospace" }) as string,
};

export const text = {
  body: { color: color.text, fontFamily: font.story, fontSize: 17, lineHeight: 26 } as TextStyle,
  small: { color: color.dim, fontFamily: font.ui, fontSize: 13 } as TextStyle,
  label: { color: color.text, fontFamily: font.ui, fontSize: 14 } as TextStyle,
};

export const selectable = Platform.select({ web: { userSelect: "text" } as object, default: {} });
