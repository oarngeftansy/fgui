"use strict";
(() => {
  // src/contracts.ts
  function isUiToMainMessage(value) {
    if (!value || typeof value !== "object") return false;
    const message = value;
    return message.type === "unpair" || message.type === "pairing-credential" && typeof message.credential === "string";
  }

  // src/pairing.ts
  var CREDENTIAL_KEY = "figma-to-fairygui-plugin-credential";
  var CredentialStore = class {
    constructor(storage) {
      this.storage = storage;
    }
    async load() {
      const value = await this.storage.getAsync(CREDENTIAL_KEY);
      return typeof value === "string" && value.length > 0 ? value : null;
    }
    save(credential) {
      return this.storage.setAsync(CREDENTIAL_KEY, credential);
    }
    clear() {
      return this.storage.deleteAsync(CREDENTIAL_KEY);
    }
  };
  function createMainPairingController(config, store, post) {
    const send = (message) => post(message, config.serverOrigin);
    return {
      async restore() {
        const credential = await store.load();
        if (credential) {
          send({ type: "credential", credential });
        } else {
          send({ type: "pairing-status", status: "unpaired" });
        }
      },
      async handle(message) {
        if (message.type === "pairing-credential") {
          await store.save(message.credential);
          send({ type: "pairing-status", status: "paired" });
          return;
        }
        await store.clear();
        send({ type: "pairing-status", status: "unpaired" });
      }
    };
  }

  // src/code.ts
  function startPlugin(config, runtime) {
    runtime.showUI('<!doctype html>\n<html lang="zh-CN">\n  <head>\n    <meta charset="utf-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1" />\n    <title>Figma \u8F6C FairyGUI</title>\n  </head>\n  <body>\n    <script>location.replace("https://fgui.corp.example/figma-plugin?pluginId=123456789");<\/script>\n  </body>\n</html>\n', { width: 360, height: 460 });
    const controller = createMainPairingController(config, new CredentialStore(runtime.clientStorage), (message, origin) => {
      runtime.ui.postMessage(message, { origin });
    });
    runtime.ui.onmessage = (message, props) => {
      if (props.origin !== config.serverOrigin) return;
      if (isUiToMainMessage(message)) void controller.handle(message);
    };
    void controller.restore();
  }
  if (typeof figma !== "undefined") {
    startPlugin({ serverOrigin: "https://fgui.corp.example", pluginId: "123456789" }, figma);
  }
})();
