import { uploadProject } from "./api";
import { ReviewPage } from "./review/ReviewPage";
import { UploadPage } from "./upload/UploadPage";

export function App() {
  const match = window.location.pathname.match(/^\/jobs\/([^/]+)$/);
  if (match) return <ReviewPage jobId={decodeURIComponent(match[1])} />;
  return <UploadPage uploadProject={uploadProject} />;
}
