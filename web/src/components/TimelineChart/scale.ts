/** Small linear scales and stable nice-number ticks, without a charting runtime. */
export function linearScale(domain: readonly [number, number], range: readonly [number, number]) {
  const span = domain[1] - domain[0];
  return (value: number): number => span === 0 ? (range[0] + range[1]) / 2 : range[0] + (value - domain[0]) / span * (range[1] - range[0]);
}
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count < 2 || max < min) return [];
  if (max === min) return [min];
  const rough = (max - min) / (count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const fraction = rough / magnitude;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step / 100; value += step) ticks.push(Number(value.toPrecision(12)));
  return ticks;
}
