type ImageComparisonProps = {
  name: string;
  beforeSrc?: string;
  afterSrc?: string;
};

const placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='360'/%3E";

export function ImageComparison({ name, beforeSrc, afterSrc }: ImageComparisonProps) {
  return (
    <section className="image-comparison" data-testid="image-comparison" aria-label={`${name}视觉对比`}>
      <figure>
        <img alt={`当前工程中的${name}视觉效果`} height="360" src={beforeSrc || placeholder} width="640" />
        <figcaption>当前工程</figcaption>
      </figure>
      <figure>
        <img alt={`更新以后${name}视觉效果`} height="360" src={afterSrc || placeholder} width="640" />
        <figcaption>更新以后</figcaption>
      </figure>
    </section>
  );
}
