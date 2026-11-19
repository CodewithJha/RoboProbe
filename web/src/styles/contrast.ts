/**
 * WCAG 2.2 contrast maths (https://www.w3.org/TR/WCAG22/#dfn-contrast-ratio), dependency-free.
 */

/** sRGB channel value at or below which the linear segment of the transfer curve applies. */
const SRGB_LINEAR_THRESHOLD = 0.04045;
const SRGB_LINEAR_DIVISOR = 12.92;
const SRGB_GAMMA_OFFSET = 0.055;
const SRGB_GAMMA_SCALE = 1.055;
const SRGB_GAMMA = 2.4;
/** Rec. 709 luminance coefficients for linear R, G, B. */
const LUMINANCE_WEIGHTS = [0.2126, 0.7152, 0.0722] as const;
/** Flare term added to both luminances in the contrast-ratio definition. */
const CONTRAST_FLARE = 0.05;
const CHANNEL_MAX = 255;
const HEX_RADIX = 16;
const HEX_COLOUR = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i;

/** An opaque sRGB colour with 8-bit channels. */
export interface Rgb {
  readonly r: number;
  readonly g: number;
  readonly b: number;
}

/** Parses an opaque `#RRGGBB` colour; throws on any other syntax. */
export function parseHexColour(value: string): Rgb {
  const match = HEX_COLOUR.exec(value.trim());
  if (match === null) {
    throw new Error(`Expected an opaque #RRGGBB colour, got '${value}'`);
  }
  const [, r = '', g = '', b = ''] = match;
  return {
    r: Number.parseInt(r, HEX_RADIX),
    g: Number.parseInt(g, HEX_RADIX),
    b: Number.parseInt(b, HEX_RADIX),
  };
}

function linearise(channel: number): number {
  const c = channel / CHANNEL_MAX;
  return c <= SRGB_LINEAR_THRESHOLD
    ? c / SRGB_LINEAR_DIVISOR
    : ((c + SRGB_GAMMA_OFFSET) / SRGB_GAMMA_SCALE) ** SRGB_GAMMA;
}

/** WCAG relative luminance in [0, 1]. */
export function relativeLuminance({ r, g, b }: Rgb): number {
  const [wr, wg, wb] = LUMINANCE_WEIGHTS;
  return wr * linearise(r) + wg * linearise(g) + wb * linearise(b);
}

/** WCAG contrast ratio in [1, 21]; symmetric in its arguments. */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + CONTRAST_FLARE) / (Math.min(la, lb) + CONTRAST_FLARE);
}
