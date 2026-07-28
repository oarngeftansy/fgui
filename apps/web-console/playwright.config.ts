import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  // globalSetup owns a fresh server for every run; an existing server is never reused.
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: "http://127.0.0.1:8766" },
});
