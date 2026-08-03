# Figma to FairyGUI plugin installation

This release ZIP contains only the Figma plugin files. Keep the release archive and its adjacent `checksums.sha256` together until the release owner has verified the SHA-256 value.

## Pilot: Figma development import

1. Extract `Figma-to-FairyGUI-plugin.zip` to a clean local folder.
2. In a Figma file, select **Plugins > Development > Import plugin from manifest**.
3. Select the extracted `manifest.json`, then run the plugin against a current selection.

The plugin is already configured for the approved internal HTTPS service. Designers do not enter a server address, pairing code, or access token.

## Rollout: private organization plugin

After the pilot passes, the Figma publisher opens **Plugins > Manage plugins > Development > Publish**, selects **Organization** as the publishing destination, and publishes the same plugin ID to the intended organization. Confirm Figma displays exactly one restricted HTTPS network domain before publishing. Do not publish this plugin to the Community.

For each update, rebuild with the approved origin, plugin ID, and deployment access token; verify the release SHA-256; then publish the updated private organization plugin.
