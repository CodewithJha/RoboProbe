import { describe, expect, it } from 'vitest';
import { nearestTime, screenToWorld, worldToScreen } from './transform';

describe('map transforms', () => {
  it('round trips ROS map origins, zoom and pan', () => {
    const map = { resolution: 0.05, origin: [-10, -5] as const, width: 600, height: 400 };
    const viewport = { zoom: 2.5, pan: [12, -30] as const };
    const point = worldToScreen([0.3, 2.7], map, viewport);
    const restored = screenToWorld(point, map, viewport);
    expect(restored[0]).toBeCloseTo(0.3);
    expect(restored[1]).toBeCloseTo(2.7);
    expect(worldToScreen(map.origin, map, {zoom:1, pan:[0,0]})).toEqual([0,400]);
  });
  it('finds the nearest time at boundaries and ties', () => {
    expect(nearestTime([], 0)).toBe(-1);
    expect(nearestTime([0,1,2], -3)).toBe(0);
    expect(nearestTime([0,1,2], 9)).toBe(2);
    expect(nearestTime([0,1,2], 0.5)).toBe(0);
  });
});
