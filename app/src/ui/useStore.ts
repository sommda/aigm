import { useSyncExternalStore } from "react";

interface Store {
  subscribe: (fn: () => void) => () => void;
  getVersion: () => number;
}

/** Re-render when a store (the controller, a panel) says something changed. */
export function useStore(store: Store): number {
  return useSyncExternalStore(store.subscribe, store.getVersion, store.getVersion);
}
