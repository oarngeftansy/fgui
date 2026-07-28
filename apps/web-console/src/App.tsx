import { uploadProject } from "./api";
import { UploadPage } from "./upload/UploadPage";

export function App() {
  return <UploadPage uploadProject={uploadProject} />;
}
