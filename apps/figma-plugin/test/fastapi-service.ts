import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const root = resolve(import.meta.dirname, "../../..");
const healthHeader = "X-Figma-To-FGUI-Instance";

export type FastApiService = {
  baseUrl: string;
  pluginToken: string;
  fetch(path: string, init?: RequestInit): Promise<Response>;
  stop(): Promise<void>;
};

export async function startFastApiService(): Promise<FastApiService> {
  const port = await availablePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const dataDir = await mkdtemp(join(tmpdir(), "figma-to-fgui-plugin-harness-"));
  const nonce = randomBytes(32).toString("hex");
  const secret = randomBytes(32).toString("hex");
  const python = join(root, ".venv", "Scripts", "python.exe");
  const script = [
    "import sys,uvicorn",
    "from pathlib import Path",
    "from figma_to_fgui.api import create_app",
    "uvicorn.run(create_app(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),web_dist=Path(sys.argv[4]),health_instance_token=sys.argv[5],plugin_access_token=sys.argv[6].encode('ascii')),host='127.0.0.1',port=int(sys.argv[7]),log_level='warning')",
  ].join(";");
  const child = spawn(
    python,
    [
      "-c", script, dataDir, join(root, "tests", "fixtures"), join(root, "rules", "default", "classification.yaml"),
      join(root, "apps", "web-console", "dist"), nonce, secret, String(port),
    ],
    { cwd: root, env: { ...process.env, PYTHONPATH: join(root, "src") }, stdio: "ignore", windowsHide: true },
  );
  try {
    await waitForHealth(child, baseUrl, nonce);
  } catch (error) {
    await stopChild(child);
    await removeData(dataDir);
    throw error;
  }
  return {
    baseUrl,
    pluginToken: secret,
    fetch: (path, init) => fetch(new URL(path, baseUrl), init),
    async stop() {
      await stopChild(child);
      await removeData(dataDir);
    },
  };
}

async function availablePort(): Promise<number> {
  const listener = createServer();
  await new Promise<void>((resolve, reject) => {
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", () => resolve());
  });
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("could not reserve a loopback port");
  const port = address.port;
  await new Promise<void>((resolve, reject) => listener.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForHealth(child: ChildProcess, baseUrl: string, nonce: string): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`FastAPI test server exited with ${child.exitCode}`);
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok && response.headers.get(healthHeader) === nonce && child.exitCode === null) return;
    } catch {
      // The new child may not have bound its private loopback port yet.
    }
    await sleep(50);
  }
  throw new Error("FastAPI test server did not become healthy");
}

async function stopChild(child: ChildProcess): Promise<void> {
  const pid = child.pid;
  if (child.exitCode === null) {
    child.kill();
    await waitForProcessExit(pid, 1_000);
  }
  if (await processIsAlive(pid)) {
    await forceTerminate(pid);
    await waitForProcessExit(pid, 5_000);
  }
  if (await processIsAlive(pid)) throw new Error("FastAPI test server could not be terminated");
}

async function forceTerminate(pid: number | undefined): Promise<void> {
  if (pid === undefined) return;
  const killer = spawn("taskkill.exe", ["/pid", String(pid), "/T", "/F"], {
    stdio: "ignore",
    windowsHide: true,
  });
  await Promise.race([once(killer, "close"), sleep(5_000)]);
}

async function waitForProcessExit(pid: number | undefined, timeoutMs: number): Promise<void> {
  for (let elapsed = 0; elapsed < timeoutMs; elapsed += 50) {
    if (!(await processIsAlive(pid))) return;
    await sleep(50);
  }
}

async function processIsAlive(pid: number | undefined): Promise<boolean> {
  if (pid === undefined) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

async function removeData(dataDir: string): Promise<void> {
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
