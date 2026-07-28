import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:8766" },
  webServer: {
    command: ".\\.venv\\Scripts\\python.exe -m figma_to_fgui.cli serve --port 8766 --web-dist apps/web-console/dist",
    cwd: "../..",
    env: { PYTHONPATH: "src" },
    url: "http://127.0.0.1:8766/health",
    reuseExistingServer: !process.env.CI,
  },
});
