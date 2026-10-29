import { StatusBar } from "expo-status-bar";
import { useMemo } from "react";
import { SafeAreaView } from "react-native";
import { loadConfig } from "./src/platform/config";
import { GameScreen } from "./src/ui/GameScreen";
import { color } from "./src/ui/theme";

export default function App() {
  const config = useMemo(loadConfig, []);
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <StatusBar style="light" />
      <GameScreen config={config} />
    </SafeAreaView>
  );
}
