import { useEffect, useState } from "react";
import { loadConsolePreview, type FigmaSelectionView } from "../api";

type SelectionSummaryProps = {
  selection: FigmaSelectionView;
  session: string;
  loadPreview?: (session: string, url: string) => Promise<string>;
};

export function SelectionSummary({ selection, session, loadPreview = loadConsolePreview }: SelectionSummaryProps) {
  const [previews, setPreviews] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    const objectUrls: string[] = [];
    void Promise.all(selection.preview_urls.map((url) => loadPreview(session, url))).then((urls) => {
      if (active) { objectUrls.push(...urls); setPreviews(urls); } else urls.forEach(URL.revokeObjectURL);
    }).catch(() => { if (active) setPreviews([]); });
    return () => { active = false; objectUrls.forEach(URL.revokeObjectURL); };
  }, [selection.preview_urls, session, loadPreview]);
  return <section className="workflow-panel selection-summary" aria-labelledby="selection-title" aria-live="polite">
    <p className="eyebrow">步骤 2 / 5</p><h2 id="selection-title">{selection.display_name}</h2>
    <p className="intro">已收到当前 Figma 选择。请确认摘要后上传 FairyGUI 工程。</p>
    <ul className="selection-nodes">{selection.top_level_summaries.map((item, index) => <li key={`${item.name}-${index}`}>{item.name} · {item.type}</li>)}</ul>
    {previews.length > 0 && <div className="selection-previews">{previews.map((url, index) => <img key={url} src={url} alt={`${selection.display_name} 选择预览 ${index + 1}`} />)}</div>}
    {selection.warnings.map((warning, index) => <p className="message message-warning" key={`${warning.code}-${index}`}>{warning.message}</p>)}
  </section>;
}
