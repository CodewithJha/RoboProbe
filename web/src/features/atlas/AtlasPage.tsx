import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import {
  useCampaign,
  useManualRuns,
  useMeta,
  useModes,
  useRisk,
  useRiskSlice,
  useRun,
  useSpace,
  type SliceQuery,
} from '../../api/hooks';
import { RiskHeatmap } from '../../components/RiskHeatmap/RiskHeatmap';
import { atlasConfig } from './atlasConfig';
import styles from './AtlasPage.module.css';

const REGIONS = ['safe', 'uncertain', 'failure'] as const;
const percentage = (value: number) => `${(100 * value).toFixed(1)}%`;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function parameters(value: unknown, pins: Record<string, unknown>) {
  return (Array.isArray(value) ? value : []).map(record).flatMap((parameter) => {
    const id = parameter['id'];
    return typeof id === 'string' && parameter['enabled'] !== false && !(id in pins)
      ? [
          {
            id,
            title: typeof parameter['name'] === 'string' ? parameter['name'] : id,
            categorical: parameter['type'] === 'categorical',
            integral: parameter['type'] === 'int',
            low: parameter['low'],
            high: parameter['high'],
            choices: parameter['choices'],
            nominal: parameter['nominal'],
          },
        ]
      : [];
  });
}

type AnchorValue = number | string;
type AnchorOverrides = Record<string, AnchorValue>;

function parseOverrides(value: string | null): AnchorOverrides {
  if (!value) return {};
  try {
    return Object.fromEntries(
      Object.entries(record(JSON.parse(value))).filter(
        (entry): entry is [string, AnchorValue] =>
          typeof entry[1] === 'number' || typeof entry[1] === 'string',
      ),
    );
  } catch {
    return {};
  }
}

function sliceSearch(x: string, y: string, anchor: string, values: string | null) {
  const next = new URLSearchParams({ x, y, anchor });
  if (values !== null) next.set('anchor_values', values);
  return next;
}

function Preview({ campaign, query }: { campaign: string; query: SliceQuery }) {
  const slice = useRiskSlice(campaign, query);
  if (slice.data) return <RiskHeatmap slice={slice.data} size="thumb" />;
  return <span>{slice.isError ? 'Preview unavailable' : 'Loading preview…'}</span>;
}

function AnchorSlider({
  id,
  title,
  low,
  high,
  integral,
  value,
  onChange,
}: {
  id: string;
  title: string;
  low: number;
  high: number;
  integral: boolean;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {title}{' '}
      <input
        aria-label={title}
        type="range"
        name={id}
        min={low}
        max={high}
        step={integral ? 1 : 'any'}
        value={value}
        onChange={(event) => {
          onChange(event.target.valueAsNumber);
        }}
      />
      <output>{value}</output>
    </label>
  );
}

function VolumeGauge({ campaign }: { campaign: string }) {
  const { data } = useRisk(campaign);
  const volumes = data?.volumes ?? {};
  const score = data?.robustness_score;
  const available = REGIONS.some((region) => typeof volumes[region] === 'number');
  if (!available) return null;
  return (
    <section aria-label="Operating envelope">
      <h2>Operating envelope</h2>
      <div className={styles['volume']} aria-hidden="true">
        {REGIONS.map((region) => {
          const value = volumes[region];
          return (
            <span
              key={region}
              data-region={region}
              style={{ flexGrow: typeof value === 'number' ? Math.max(value, 0) : 0 }}
            />
          );
        })}
      </div>
      <dl className={styles['statistics']}>
        {REGIONS.map((region) => {
          const value = volumes[region];
          const interval = volumes[`${region}_ci`];
          return (
            <div key={region}>
              <dt>{region}</dt>
              <dd>
                {typeof value === 'number' ? percentage(value) : 'Unavailable'}
                {Array.isArray(interval) &&
                interval.length === 2 &&
                interval.every((bound) => typeof bound === 'number')
                  ? ` (95% CI ${interval.map(percentage).join('–')})`
                  : ''}
              </dd>
            </div>
          );
        })}
      </dl>
      {score !== undefined && score !== null && (
        <p>
          Robustness score <strong>{score.toFixed(3)}</strong>
        </p>
      )}
    </section>
  );
}

export function Component() {
  const { id = '' } = useParams();
  const campaign = useCampaign(id);
  const spaceRef = campaign.data?.space;
  const space = useSpace(spaceRef?.id ?? '', spaceRef?.version ?? '');
  const pins = campaign.data?.pins ?? {};
  const free = parameters(space.data?.definition['parameters'], pins);
  const numerical = free.filter((parameter) => !parameter.categorical);
  const pairs = numerical.flatMap((left, i) =>
    numerical.slice(i + 1).map((right) => ({ left, right })),
  );
  const [search, setSearch] = useSearchParams();
  const location = useLocation();
  const active =
    pairs.find(({ left, right }) => left.id === search.get('x') && right.id === search.get('y')) ??
    pairs[0];
  const anchor = search.get('anchor') ?? 'nominal';
  const encoded = search.get('anchor_values');
  const applied = parseOverrides(encoded);
  const x = active?.left.id ?? '';
  const y = active?.right.id ?? '';
  const [draft, setDraft] = useState<{ locationKey: string; overrides: AnchorOverrides }>();
  // Discard edits when moving to another URL, even if Back later restores this location key.
  if (draft && draft.locationKey !== location.key) setDraft(undefined);
  const localDraft = draft?.locationKey === location.key ? draft.overrides : undefined;
  const nextEncoded =
    localDraft && Object.keys(localDraft).length > 0 ? JSON.stringify(localDraft) : null;
  const pending = localDraft !== undefined && nextEncoded !== encoded;
  useEffect(() => {
    if (!pending) return;
    const timer = window.setTimeout(() => {
      setSearch(sliceSearch(x, y, anchor, nextEncoded), { replace: true });
    }, atlasConfig.anchorDebounceMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [anchor, nextEncoded, pending, setSearch, x, y]);
  const dimensions = free.filter(({ id }) => id !== active?.left.id && id !== active?.right.id);
  const { data: meta } = useMeta();
  const resolution = record(meta?.['defaults'])['risk_slice_resolution'];
  const query: SliceQuery = {
    x,
    y,
    anchor,
    ...(typeof resolution === 'number' ? { resolution } : {}),
    ...(encoded ? { anchor_values: encoded } : {}),
  };
  const slice = useRiskSlice(id, query);
  const modes = useModes(id);
  const mode = modes.data?.items.find((item) => `mode:${item.code}` === anchor);
  const medoid = useRun(mode?.medoid_run_id ?? '');
  const enqueue = useManualRuns(id);
  const [preview, setPreview] = useState<string>();
  const [selection, setSelection] = useState<{ x: number; y: number; key: string }>();
  const [queued, setQueued] = useState(false);
  const key = JSON.stringify(query);
  const probe = !pending && selection?.key === key ? selection : undefined;
  const values = record(medoid.data?.scenario['values']);
  const anchorReady = anchor === 'nominal' || Boolean(medoid.data);
  const base = Object.fromEntries(dimensions.map(({ id, nominal }) => [id, values[id] ?? nominal]));
  function changeOverride(name: string, value: AnchorValue) {
    setDraft((previous) => {
      const existing = previous?.locationKey === location.key ? previous.overrides : applied;
      const overrides =
        value === base[name]
          ? Object.fromEntries(Object.entries(existing).filter(([id]) => id !== name))
          : { ...existing, [name]: value };
      return { locationKey: location.key, overrides };
    });
  }

  return (
    <article className={styles['page']}>
      <header>
        <h1>Risk atlas</h1>
      </header>
      <VolumeGauge campaign={id} />
      {(campaign.isPending || (spaceRef && space.isPending)) && (
        <p role="status">Loading the campaign space…</p>
      )}
      {(campaign.isError || space.isError) && (
        <p role="alert">Unable to load the campaign space.</p>
      )}
      {campaign.data && !spaceRef && (
        <p>The campaign does not have a registered space reference.</p>
      )}
      {space.data && !active && <p>At least two free numeric parameters are needed for a slice.</p>}
      {active && (
        <div className={styles['layout']}>
          <aside aria-label="Parameter pairs">
            <h2>Parameter pairs</h2>
            <div className={styles['pairs']}>
              {pairs.map(({ left, right }) => {
                const pairKey = JSON.stringify([left.id, right.id]);
                const selected = left.id === active.left.id && right.id === active.right.id;
                return (
                  <div key={pairKey}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      onFocus={() => {
                        setPreview(pairKey);
                      }}
                      onMouseEnter={() => {
                        setPreview(pairKey);
                      }}
                      onClick={() => {
                        setSearch({ x: left.id, y: right.id, anchor });
                      }}
                    >
                      {left.title} × {right.title}
                    </button>
                    {preview === pairKey && !selected && (
                      <Preview
                        campaign={id}
                        query={{
                          ...(query.resolution !== undefined
                            ? { resolution: query.resolution }
                            : {}),
                          anchor,
                          x: left.id,
                          y: right.id,
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </aside>
          <section aria-label="Selected risk slice">
            <h2>
              {active.left.title} × {active.right.title}
            </h2>
            <label>
              Anchor{' '}
              <select
                value={anchor}
                onChange={(event) => {
                  setSearch({
                    x: query.x,
                    y: query.y,
                    anchor: event.target.value,
                  });
                }}
              >
                <option value="nominal">Nominal</option>
                {anchor !== 'nominal' && !mode && <option value={anchor}>{anchor}</option>}
                {modes.data?.items
                  .filter((item) => item.medoid_run_id)
                  .map((item) => (
                    <option value={`mode:${item.code}`} key={item.id}>
                      {item.code} · {item.label}
                    </option>
                  ))}
              </select>
            </label>
            {anchorReady && dimensions.length > 0 && (
              <fieldset className={styles['anchors']}>
                <legend>Off-axis parameters</legend>
                {dimensions.map(({ id, title, low, high, integral, choices }) => {
                  const value = (localDraft ?? applied)[id] ?? base[id];
                  if (Array.isArray(choices) && typeof value === 'string') {
                    return (
                      <label key={id}>
                        {title}{' '}
                        <select
                          name={id}
                          value={value}
                          onChange={(event) => {
                            changeOverride(id, event.target.value);
                          }}
                        >
                          {choices
                            .filter((item): item is string => typeof item === 'string')
                            .map((item) => (
                              <option key={item}>{item}</option>
                            ))}
                        </select>
                      </label>
                    );
                  }
                  if (
                    typeof low !== 'number' ||
                    typeof high !== 'number' ||
                    typeof value !== 'number'
                  ) {
                    return null;
                  }
                  return (
                    <AnchorSlider
                      key={id}
                      id={id}
                      title={title}
                      low={low}
                      high={high}
                      integral={integral}
                      value={value}
                      onChange={(next) => {
                        changeOverride(id, next);
                      }}
                    />
                  );
                })}
                {(encoded !== null || pending) && (
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(undefined);
                      if (encoded !== null) {
                        setSearch(sliceSearch(x, y, anchor, null), { replace: true });
                      }
                    }}
                  >
                    Reset values
                  </button>
                )}
              </fieldset>
            )}
            {slice.isPending && <p role="status">Loading risk slice…</p>}
            {slice.isError && <p role="alert">{slice.error.message}</p>}
            {slice.data && (
              <RiskHeatmap
                slice={slice.data}
                onCellClick={(point) => {
                  enqueue.reset();
                  setQueued(false);
                  setSelection({ ...point, key });
                }}
              />
            )}
            {probe && (
              <section aria-label="Confirm manual probe" className={styles['probe']}>
                <h3>Probe here</h3>
                <p>
                  {active.left.title} {probe.x}, {active.right.title} {probe.y}. Other parameters
                  use the selected anchor.
                </p>
                {!anchorReady && <p role="status">Waiting for the medoid values.</p>}
                <button
                  type="button"
                  disabled={!anchorReady || enqueue.isPending || queued}
                  onClick={() => {
                    // Scenario values originate from the generated Run DTO. Current axes override the anchor.
                    const anchorValues = medoid.data?.scenario['values'];
                    const body =
                      anchorValues &&
                      typeof anchorValues === 'object' &&
                      !Array.isArray(anchorValues)
                        ? anchorValues
                        : {};
                    enqueue.mutate(
                      {
                        values: { ...body, ...applied, [query.x]: probe.x, [query.y]: probe.y },
                        repeats: 1,
                      },
                      {
                        onSuccess: () => {
                          setQueued(true);
                        },
                      },
                    );
                  }}
                >
                  Queue manual run
                </button>
                <button
                  type="button"
                  disabled={enqueue.isPending}
                  onClick={() => {
                    setSelection(undefined);
                  }}
                >
                  Dismiss
                </button>
                {queued && (
                  <p role="status">
                    Manual run queued.{' '}
                    <Link to={`/campaigns/${id}/console`}>Open campaign console</Link>
                  </p>
                )}
                {enqueue.isError && <p role="alert">{enqueue.error.message}</p>}
              </section>
            )}
            {medoid.isError && <p role="alert">Unable to load the medoid values.</p>}
            {anchor !== 'nominal' && Object.keys(values).length > 0 && (
              <details>
                <summary>Medoid values</summary>
                <dl>
                  {Object.entries(values).map(([name, value]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            )}
          </section>
        </div>
      )}
    </article>
  );
}
