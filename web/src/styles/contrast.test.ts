import { describe, expect, it } from 'vitest';

import { contrastRatio, parseHexColour, relativeLuminance } from './contrast';

const BLACK = parseHexColour('#000000');
const WHITE = parseHexColour('#FFFFFF');

describe('parseHexColour', () => {
  it('parses upper- and lower-case #RRGGBB', () => {
    expect(parseHexColour('#2F5D8A')).toEqual({ r: 47, g: 93, b: 138 });
    expect(parseHexColour(' #2f5d8a ')).toEqual({ r: 47, g: 93, b: 138 });
  });

  it.each(['#FFF', 'rgba(0,0,0,0.1)', '2F5D8A', '#GGGGGG', ''])('rejects %j', (value) => {
    expect(() => parseHexColour(value)).toThrow(/#RRGGBB/);
  });
});

describe('contrast maths (WCAG 2.2)', () => {
  it('has luminance 0 for black and 1 for white', () => {
    expect(relativeLuminance(BLACK)).toBe(0);
    expect(relativeLuminance(WHITE)).toBeCloseTo(1, 10);
  });

  it('spans 1:1 to 21:1 and is symmetric', () => {
    expect(contrastRatio(BLACK, WHITE)).toBeCloseTo(21, 10);
    expect(contrastRatio(WHITE, BLACK)).toBeCloseTo(21, 10);
    expect(contrastRatio(WHITE, WHITE)).toBe(1);
  });

  it('uses the linear segment for dark channels', () => {
    // #767676 on white is the canonical 4.54:1 AA boundary grey.
    expect(contrastRatio(parseHexColour('#767676'), WHITE)).toBeCloseTo(4.54, 2);
    expect(relativeLuminance(parseHexColour('#0A0A0A'))).toBeCloseTo(10 / 255 / 12.92, 10);
  });
});
