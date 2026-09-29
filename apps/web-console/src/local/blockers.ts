const PSD_BLOCKER_LABELS: Record<string, string> = {
  color_mode_not_rgb: "颜色模式不是 RGB，无法按当前链路证明颜色一致",
  unsupported_bit_depth: "PSD 位深不受支持",
  smart_objects_require_equivalence_check: "智能对象需要展开或通过像素等价检查",
  adjustment_layers_require_equivalence_check: "调整图层需要合成结果等价检查",
  layer_effects_require_equivalence_check:
    "图层效果需要转换并验证描边、阴影与叠加效果",
  pixel_layers_require_equivalence_check: "像素图层需要无降质导出与透明度检查",
  shape_styles_require_equivalence_check:
    "形状图层的填充、描边与蒙版需要等价检查",
  text_styles_require_equivalence_check:
    "文字样式需要验证字体资源、字号、颜色、行距与效果",
};

export function blockerLabel(code: string): string {
  return PSD_BLOCKER_LABELS[code] ?? code;
}
