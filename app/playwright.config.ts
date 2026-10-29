import { defineConfig } from "@playwright/test";
import * as os from "os";
import * as path from "path";

// A throwaway save folder, so the tests never touch real saves.
const saves = path.join(os.tmpdir(), `aigm-e2e-saves-${process.pid}`);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1, // one scripted server, one session
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8082", channel: "chrome", viewport: { width: 1280, height: 900 }, screenshot: "only-on-failure" },
  webServer: [
    {
      command: `cd ../server && AIGM_SAVE_DIR=${saves} AIGM_TEST_DELAY=0 uv run aigm --test --debug --port 8765`,
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "python3 -m http.server 8082 --directory dist --bind 127.0.0.1",
      url: "http://127.0.0.1:8082/",
      reuseExistingServer: false,
    },
  ],
});
