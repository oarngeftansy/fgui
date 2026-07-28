// @vitest-environment node
import { createServer } from "node:http";
import type { ChildProcess } from "node:child_process";
import { once } from "node:events";
import { afterEach, describe, expect, it, vi } from "vitest";

import globalSetup, { waitForServer } from "./global-setup";

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
    await expect(waitForServer({ exitCode: 7 } as ChildProcess)).rejects.toThrow(
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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 200 })));

    await expect(waitForServer(server)).rejects.toThrow("Playwright server exited with 9");
  });
});
