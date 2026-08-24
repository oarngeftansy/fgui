import { useEffect, useState } from "react";
import type { ProjectWorkflowClient } from "../../../figma-plugin/src/project-client";

type PreviewClient = Pick<ProjectWorkflowClient, "newProjectPreview">;
type PreviewCandidate = { buildId: string };
type PreviewReview = {
  imageReviews: ReadonlyArray<{ sourcePreviewUrl?: string; generatedAssetUrl: string }>;
  componentReviews: ReadonlyArray<{ renderedPreviewUrl?: string }>;
};
type PreviewState = "pending" | "ready" | "failed";

function blobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("preview_read_failed"));
    reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("preview_read_failed"));
    reader.readAsDataURL(blob);
  });
}

export function useNewProjectReviewPreviews(
  client: PreviewClient,
  candidate?: PreviewCandidate,
  review?: PreviewReview,
) {
  const [previewObjects, setPreviewObjects] = useState<Record<string, string>>({});
  const [previewBlobs, setPreviewBlobs] = useState<Record<string, Blob>>({});
  const [previewState, setPreviewState] = useState<PreviewState>("pending");

  useEffect(() => {
    if (!review || !candidate) {
      setPreviewObjects({});
      setPreviewBlobs({});
      setPreviewState("pending");
      return;
    }

    setPreviewState("pending");
    const controller = new AbortController();
    const paths = [
      ...review.imageReviews.flatMap((item) => [item.sourcePreviewUrl, item.generatedAssetUrl]),
      ...review.componentReviews.map((item) => item.renderedPreviewUrl),
    ].filter((path): path is string => Boolean(path));
    const objectUrls: string[] = [];

    if (paths.length === 0) {
      setPreviewState("ready");
      return;
    }

    void Promise.all(paths.map(async (path) => {
      try {
        const blob = await client.newProjectPreview(candidate.buildId, path, controller.signal);
        const objectUrl = typeof URL.createObjectURL === "function"
          ? URL.createObjectURL(blob)
          : await blobDataUrl(blob);
        if (objectUrl.startsWith("blob:")) objectUrls.push(objectUrl);
        return [path, objectUrl, blob] as const;
      } catch {
        return undefined;
      }
    })).then((items) => {
      if (controller.signal.aborted) return;
      const loaded = items.filter((item): item is readonly [string, string, Blob] => Boolean(item));
      setPreviewObjects(Object.fromEntries(loaded.map(([path, objectUrl]) => [path, objectUrl])));
      setPreviewBlobs(Object.fromEntries(loaded.map(([path, _objectUrl, blob]) => [path, blob])));
      setPreviewState(items.some((item) => !item) ? "failed" : "ready");
    });

    return () => {
      controller.abort();
      if (typeof URL.revokeObjectURL === "function") objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [candidate?.buildId, client, review]);

  return { previewObjects, previewBlobs, previewState } as const;
}
