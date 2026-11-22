import { api } from '../../../api/client';
import type { MapGeometry } from '../../../components/TrajectoryPlot/transform';
import { number, object } from '../runData';

const MAX_CELLS = 1_000_000;

export function parseWorld(value: unknown): MapGeometry | undefined {
  const data = object(value);
  const shape = data['shape'],
    origin = data['origin'],
    rle = data['rle'];
  if (
    data['schema_version'] !== 1 ||
    !Array.isArray(shape) ||
    !Array.isArray(origin) ||
    !Array.isArray(rle) ||
    shape.length !== 2 ||
    origin.length !== 2
  )
    return undefined;
  const height = number(shape[0]),
    width = number(shape[1]),
    x = number(origin[0]),
    y = number(origin[1]);
  const resolution = number(data['resolution']);
  if (
    width === undefined ||
    height === undefined ||
    x === undefined ||
    y === undefined ||
    resolution === undefined ||
    resolution <= 0 ||
    !Number.isSafeInteger(width) ||
    !Number.isSafeInteger(height) ||
    width <= 0 ||
    height <= 0 ||
    width * height > MAX_CELLS ||
    rle.length > width * height
  )
    return undefined;
  const paths: string[] = [];
  let cursor = 0;
  for (const run of rle) {
    if (!Array.isArray(run) || run.length !== 2) return undefined;
    const occupied = number(run[0]),
      count = number(run[1]);
    if (
      (occupied !== 0 && occupied !== 1) ||
      count === undefined ||
      !Number.isSafeInteger(count) ||
      count <= 0 ||
      cursor + count > width * height
    )
      return undefined;
    const end = cursor + count;
    if (occupied === 1) {
      while (cursor < end) {
        const column = cursor % width;
        const row = height - 1 - Math.floor(cursor / width);
        const length = Math.min(end - cursor, width - column);
        paths.push(`M${String(column)} ${String(row)}h${String(length)}v1h-${String(length)}z`);
        cursor += length;
      }
    } else cursor = end;
  }
  if (cursor !== width * height) return undefined;
  const footprintRadius = number(data['footprint_radius']);
  const obstacle = object(data['obstacle']);
  const ox = number(obstacle['x']),
    oy = number(obstacle['y']);
  const ow = number(obstacle['width']),
    oh = number(obstacle['height']),
    yaw = number(obstacle['yaw']);
  return {
    width,
    height,
    resolution,
    origin: [x, y],
    occupancyPath: paths.join(' '),
    ...(footprintRadius !== undefined && footprintRadius > 0 ? { footprintRadius } : {}),
    ...(ox !== undefined &&
    oy !== undefined &&
    ow !== undefined &&
    oh !== undefined &&
    ow > 0 &&
    oh > 0 &&
    yaw !== undefined
      ? { obstacle: { x: ox, y: oy, width: ow, height: oh, yaw } }
      : {}),
  };
}

export async function fetchWorld(id: string, signal: AbortSignal): Promise<MapGeometry | null> {
  const result = await api.GET('/api/v1/artifacts/{artifact_id}/content', {
    params: { path: { artifact_id: id } },
    parseAs: 'text',
    signal,
  });
  if (!result.data) return null;
  return parseWorld(JSON.parse(result.data)) ?? null;
}
