import type { UiToMainMessage } from "./contracts";

export const FIGMA_ORIGIN = "https://www.figma.com";

export type ParentPost = (message: { pluginId: string; pluginMessage: UiToMainMessage }, targetOrigin: string) => void;

export function postToFigma(post: ParentPost, pluginId: string, message: UiToMainMessage): void {
  post({ pluginId, pluginMessage: message }, FIGMA_ORIGIN);
}
