import { useEffect, useState } from "react";
import { uploadProject } from "./api";
import { SelectionPage } from "./figma/SelectionPage";
import { ReviewPage } from "./review/ReviewPage";
import { UploadPage } from "./upload/UploadPage";

export function App() {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const match = pathname.match(/^\/jobs\/([^/]+)$/);
  const selectionMatch = pathname.match(/^\/figma\/selections\/([0-9a-f]{32})$/);
  if (selectionMatch) return <SelectionPage selectionId={selectionMatch[1]} />;
  if (match) return <ReviewPage jobId={decodeURIComponent(match[1])} />;
  return <UploadPage uploadProject={uploadProject} />;
}
