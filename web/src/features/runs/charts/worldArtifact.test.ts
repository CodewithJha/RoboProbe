import { expect, test } from 'vitest';
import { parseWorld } from './worldArtifact';
test('loads recorded occupied cells in y-up world coordinates', () => {
  expect(
    parseWorld({
      schema_version: 1,
      shape: [2, 2],
      origin: [-2, 3],
      resolution: 0.5,
      rle: [
        [1, 3],
        [0, 1],
      ],
    }),
  ).toMatchObject({
    width: 2,
    height: 2,
    origin: [-2, 3],
    occupancyPath: 'M0 1h2v1h-2z M0 0h1v1h-1z',
  });
});
test('rejects overrun and incomplete occupancy encodings', () => {
  const base = { schema_version: 1, shape: [2, 2], origin: [-2, 3], resolution: 0.5 };
  expect(parseWorld({ ...base, rle: [[1, 5]] })).toBeUndefined();
  expect(parseWorld({ ...base, rle: [[1, 3]] })).toBeUndefined();
});
