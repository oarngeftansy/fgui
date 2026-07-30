type ImageComparisonProps = {
  name: string;
  beforeSrc?: string;
  afterSrc?: string;
};

export function ImageComparison({ name, beforeSrc, afterSrc }: ImageComparisonProps) {
  return (
    <section className="image-comparison" data-testid="image-comparison" aria-label={`${name}视觉对比`}>
      <figure>
        {beforeSrc ? <img alt={`当前工程中的${name}视觉效果`} height="360" src={beforeSrc} width="640" /> : <p className="image-empty">新增图片，当前工程中没有对应视觉</p>}
        <figcaption>当前工程</figcaption>
      </figure>
      <figure>
        {afterSrc ? <img alt={`更新以后${name}视觉效果`} height="360" src={afterSrc} width="640" /> : <p className="image-empty">更新后预览暂不可用</p>}
        <figcaption>更新以后</figcaption>
      </figure>
    </section>
  );
}
