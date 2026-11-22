import { describe, expect, it } from 'vitest';
import { linearScale, niceTicks } from './scale';

describe('linear chart scales', () => {
  it('maps endpoints and degenerate domains', () => {
    expect(linearScale([0,10],[10,100])(5)).toBe(55);
    expect(linearScale([2,2],[10,100])(2)).toBe(55);
  });
  it('generates bounded readable ticks across scales', () => {
    expect(niceTicks(0,100)).toEqual([0,50,100]);
    expect(niceTicks(-0.03,0.03)).toEqual([-0.02,0,0.02]);
    expect(niceTicks(2,2)).toEqual([2]);
    expect(niceTicks(Number.NaN,2)).toEqual([]);
  });
});
