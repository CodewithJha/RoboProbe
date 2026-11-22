interface HeatmapAxis {
  type: 'linear' | 'log';
  range: [number, number];
  edges: number[];
  fractions: number[];
}

/** The same cell boundaries drive Plotly and the overlaid SVG, including log axes. */
export function heatmapAxis(centers: number[], logarithmic: boolean): HeatmapAxis {
  const log = logarithmic && centers.every((value) => value > 0);
  const coordinates = log ? centers.map((value) => Math.log10(value)) : centers;
  const low = coordinates[0] ?? 0;
  const high = coordinates.at(-1) ?? low;
  const start = low - ((coordinates[1] ?? low + 1) - low) / 2;
  const end = high + (high - (coordinates.at(-2) ?? high - 1)) / 2;
  const boundaries = coordinates.map((center, index) =>
    index === 0 ? start : (center + (coordinates[index - 1] ?? center)) / 2,
  );
  boundaries.push(end);
  return {
    type: log ? 'log' : 'linear',
    range: [start, end],
    edges: log ? boundaries.map((boundary) => 10 ** boundary) : boundaries,
    fractions: boundaries.map((boundary) => (boundary - start) / (end - start || 1)),
  };
}
