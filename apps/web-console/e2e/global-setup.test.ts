// @vitest-environment node
import { createServer } from "node:http";
import type { ChildProcess } from "node:child_process";
import { once } from "node:events";
import { afterEach, describe, expect, it, vi } from "vitest";

import globalSetup, { stopServer, waitForServer } from "./global-setup";

const baseUrl = "http://127.0.0.1:8766";
let occupiedPort: ReturnType<typeof createServer> | undefined;

afterEach(async () => {
  vi.unstubAllGlobals();
  if (occupiedPort) {
    occupiedPort.close();
    await once(occupiedPort, "close");
    occupiedPort = undefined;
  }
});

describe("Playwright server setup", () => {
  it("fails before spawn when the configured port is already occupied", async () => {
    let requests = 0;
    occupiedPort = createServer((_request, response) => {
      requests += 1;
      response.end("existing service");
    });
    occupiedPort.listen(8766, "127.0.0.1");
    await once(occupiedPort, "listening");

    await expect(globalSetup()).rejects.toThrow("127.0.0.1:8766 already accepts connections");
    expect(requests).toBe(0);
    await expect(fetch(baseUrl)).resolves.toMatchObject({ ok: true });
  });

  it("fails readiness when the spawned child has already exited", async () => {
    await expect(waitForServer({ exitCode: 7 } as ChildProcess, "expected-token")).rejects.toThrow(
      "Playwright server exited with 7",
    );
  });

  it("fails readiness when the child exits immediately after health succeeds", async () => {
    let checks = 0;
    const server = {
      get exitCode() {
        checks += 1;
        return checks === 1 ? null : 9;
      },
    } as ChildProcess;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(null, {
          status: 200,
          headers: { "X-Figma-To-FGUI-Instance": "expected-token" },
        }),
      ),
    );

    await expect(waitForServer(server, "expected-token")).rejects.toThrow(
      "Playwright server exited with 9",
    );
  });

  it("rejects a healthy response from a different server instance", async () => {
    let checks = 0;
    const losingServer = {
      get exitCode() {
        checks += 1;
        return checks < 3 ? null : 17;
      },
    } as ChildProcess;
    const fetchHealth = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 200,
        headers: { "X-Figma-To-FGUI-Instance": "winner-token" },
      }),
    );
    vi.stubGlobal("fetch", fetchHealth);

    await expect(waitForServer(losingServer, "loser-token")).rejects.toThrow(
      "Playwright server exited with 17",
    );
    expect(fetchHealth).toHaveBeenCalledTimes(2);
  });

  it("waits for its child to die before teardown can remove the temporary data", async () => {
    let exitCode: number | null = null;
    const server = {
      pid: undefined,
      get exitCode() { return exitCode; },
      kill: vi.fn(() => { exitCode = 0; return true; }),
    } as unknown as ChildProcess;

    await stopServer(server);

    expect(server.kill).toHaveBeenCalledOnce();
    expect(server.exitCode).toBe(0);
  });
});
