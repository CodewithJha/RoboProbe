import { expect, test } from 'vitest';
import { parameters } from './spaceParameters';
test('parses enabled parameters from a space definition', () => {
  expect(
    parameters({
      parameters: [
        { id: 'speed', name: 'Speed', nominal: 0.4, unit: 'm/s', type: 'real' },
        { id: 'bad', nominal: null },
      ],
    }),
  ).toEqual([
    {
      id: 'speed',
      name: 'Speed',
      nominal: 0.4,
      unit: 'm/s',
      type: 'real',
      enabled: true,
      choices: [],
      scale: '',
    },
  ]);
});

test('returns an empty list when parameters are missing', () => {
  expect(parameters(undefined)).toEqual([]);
  expect(parameters({})).toEqual([]);
});
