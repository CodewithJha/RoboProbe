/** World metres (y up) ↔ image pixels (y down), using the ROS map origin convention. */
export interface MapGeometry {
  readonly resolution: number;
  readonly origin: readonly [number, number];
  readonly width: number;
  readonly height: number;
  readonly imageUrl?: string;
  readonly occupancyPath?: string;
  readonly footprintRadius?: number;
  readonly obstacle?: { x: number; y: number; width: number; height: number; yaw: number };
}
export interface Viewport {
  readonly zoom: number;
  readonly pan: readonly [number, number];
}
export type Point = readonly [number, number];
export function worldToScreen([x, y]: Point, map: MapGeometry, viewport: Viewport): Point {
  return [
    ((x - map.origin[0]) / map.resolution) * viewport.zoom + viewport.pan[0],
    (map.height - (y - map.origin[1]) / map.resolution) * viewport.zoom + viewport.pan[1],
  ];
}
export function screenToWorld([x, y]: Point, map: MapGeometry, viewport: Viewport): Point {
  return [
    ((x - viewport.pan[0]) / viewport.zoom) * map.resolution + map.origin[0],
    (map.height - (y - viewport.pan[1]) / viewport.zoom) * map.resolution + map.origin[1],
  ];
}
export function nearestTime(times: readonly number[], t: number): number {
  if (times.length === 0) return -1;
  let low = 0,
    high = times.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if ((times[mid] ?? 0) < t) low = mid + 1;
    else high = mid;
  }
  return low > 0 && Math.abs((times[low - 1] ?? 0) - t) <= Math.abs((times[low] ?? 0) - t)
    ? low - 1
    : low;
}
