/** Where the server is, and which session to play. On the web, `?server=http://host:8000&session=name` in the page
 * address wins (and is remembered); otherwise EXPO_PUBLIC_AIGM_URL, otherwise the local default. */

import { Platform } from "react-native";
import { DEFAULT_URL } from "../core/api";

export interface Config {
  url: string;
  session: string;
}

function remembered(key: string, value: string | null): string | null {
  try {
    if (value) window.localStorage.setItem(key, value);
    return value ?? window.localStorage.getItem(key);
  } catch {
    return value;
  }
}

export function loadConfig(): Config {
  let url = process.env.EXPO_PUBLIC_AIGM_URL || DEFAULT_URL;
  let session = process.env.EXPO_PUBLIC_AIGM_SESSION || "default";
  if (Platform.OS === "web" && typeof window !== "undefined") {
    const q = new URLSearchParams(window.location.search);
    url = remembered("aigm.server", q.get("server")) ?? url;
    session = remembered("aigm.session", q.get("session")) ?? session;
  }
  return { url, session };
}
