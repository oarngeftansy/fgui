import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const root = resolve(import.meta.dirname, "../../..");
const baseUrl = "http://127.0.0.1:8766";

async function waitForServer(server: ChildProcess): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) throw new Error(`Playwright server exited with ${server.exitCode}`);
    try {
      if ((await fetch(`${baseUrl}/health`)).ok) return;
    } catch {
      // The process may still be binding its loopback port.
    }
    await sleep(100);
  }
  throw new Error("Playwright server did not become healthy");
}

async function stopServer(server: ChildProcess): Promise<void> {
  if (server.exitCode === null) {
    server.kill();
    await Promise.race([once(server, "close"), sleep(5_000)]);
  }
}

async function removeDataDir(dataDir: string): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await rm(dataDir, { force: true, recursive: true });
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EBUSY" || attempt === 19) throw error;
      await sleep(100);
    }
  }
}

export default async function globalSetup() {
  const dataDir = await mkdtemp(join(tmpdir(), "figma-to-fgui-playwright-"));
  const server = spawn(
    join(root, ".venv", "Scripts", "python.exe"),
    [
      "-m",
      "figma_to_fgui.cli",
      "serve",
      "--data-dir",
      dataDir,
      "--port",
      "8766",
      "--web-dist",
      join(root, "apps", "web-console", "dist"),
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: join(root, "src") },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  try {
    await waitForServer(server);
  } catch (error) {
    await stopServer(server);
    await removeDataDir(dataDir);
    throw error;
  }

  return async () => {
    await stopServer(server);
    await removeDataDir(dataDir);
  };
}
