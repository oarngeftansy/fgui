import { useEffect, useState } from "react";
import { getFigmaSelection, safeReviewMessage, type FigmaSelectionView } from "../api";

export function SelectionPage({ selectionId, loadSelection = getFigmaSelection }: { selectionId: string; loadSelection?: (selectionId: string) => Promise<FigmaSelectionView> }) {
  const [selection, setSelection] = useState<FigmaSelectionView>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void loadSelection(selectionId).then((value) => { if (active) setSelection(value); }).catch((reason: unknown) => {
      if (active) setError(safeReviewMessage(reason, "暂时无法加载这个选择，请返回插件后重试"));
    });
    return () => { active = false; };
  }, [loadSelection, selectionId]);
  if (error) return <main className="plugin-frame"><p className="message message-error" role="alert">{error}</p></main>;
  if (!selection) return <main className="plugin-frame"><p aria-live="polite">正在加载当前选择…</p></main>;
  return <main className="plugin-frame" aria-labelledby="selection-title">
    <p className="eyebrow">Figma 转 FairyGUI</p><h1 id="selection-title">{selection.display_name}</h1>
    <p className="plugin-copy">选择已提交，可继续准备 FairyGUI 工程并查看更新。</p>
    <ul>{selection.top_level_summaries.map((item, index) => <li key={`${item.name}-${index}`}>{item.name} · {item.type}</li>)}</ul>
    {selection.warnings.map((item, index) => <p className="message" key={`${item.code}-${index}`}>{item.message}</p>)}
  </main>;
}
