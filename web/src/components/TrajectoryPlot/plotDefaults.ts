/** Typed interaction/layout defaults; doc 13 §3.4 specifies two-second footprint ghosts. */
export const plotDefaults = {
  width: 720, height: 420, ghostIntervalS: 2,
  zoomStep: 1.2, minZoom: 0.25, maxZoom: 12, panStep: 24,
  minimumWorldSpan: 1, pointRadius: 4,
} as const;
