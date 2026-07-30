import { readCachedSelectionView } from "./selectionCache";

export function SelectionPage({ selectionId }: { selectionId: string }) {
  const selection = readCachedSelectionView(selectionId);
  if (!selection) return <main className="plugin-frame"><p className="message message-error" role="alert">此选择链接已过期或不可用，请返回插件重新打开。</p></main>;
  return <main className="plugin-frame" aria-labelledby="selection-title">
    <p className="eyebrow">Figma 转 FairyGUI</p><h1 id="selection-title">{selection.display_name}</h1>
    <p className="plugin-copy">选择已提交，可继续准备 FairyGUI 工程并查看更新。</p>
    <ul>{selection.top_level_summaries.map((item, index) => <li key={`${item.name}-${index}`}>{item.name} · {item.type}</li>)}</ul>
    {selection.warnings.map((item, index) => <p className="message" key={`${item.code}-${index}`}>{item.message}</p>)}
  </main>;
}
