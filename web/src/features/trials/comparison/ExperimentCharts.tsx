import { lazy, Suspense, useSyncExternalStore, type ComponentProps } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, requireData, type Schema } from '../../../api/client';
import { useTheme } from '../../../app/contexts';
import { loadPlotly } from '../../../components/charts/plotly';
import tokens from '../../../styles/tokens.json';
import styles from './ExperimentCharts.module.css';

const Chart = lazy(loadPlotly);
const config = { displaylogo: false, responsive: true, displayModeBar: false } as const;
const systemScheme =
  typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;
const subscribeScheme = (change: () => void) => {
  systemScheme?.addEventListener('change', change);
  return () => {
    systemScheme?.removeEventListener('change', change);
  };
};
const isDarkScheme = () => systemScheme?.matches ?? false;
type Palette = typeof tokens.light;
type Group = Schema['StrategyCharts'];
type ChartProps = ComponentProps<typeof Chart>;
type Traces = NonNullable<ChartProps['data']>;
interface Axis {
  title?: { text: string };
  tickformat?: string;
  rangemode?: 'tozero';
  range?: [number, number];
}

function strategyColor(theme: Palette, index: number) {
  const colors = [
    theme['--strategy-1'],
    theme['--strategy-2'],
    theme['--strategy-3'],
    theme['--strategy-4'],
    theme['--strategy-5'],
    theme['--strategy-6'],
    theme['--strategy-7'],
    theme['--strategy-8'],
  ];
  return colors[index % colors.length] ?? theme['--ink'];
}

function bandColor(color: string) {
  const rgb = Number.parseInt(color.slice(1), 16);
  return `rgba(${String((rgb >> 16) & 255)}, ${String((rgb >> 8) & 255)}, ${String(rgb & 255)}, 0.16)`;
}

function discoveryTraces(groups: Group[], theme: Palette): Traces {
  return groups.flatMap(({ strategy, discovery }, index): Traces => {
    if (!discovery.length) return [];
    const x = discovery.map(({ simulations }) => simulations);
    const color = strategyColor(theme, index);
    const traces: Traces = [];
    if (discovery.every(({ low, high }) => low != null && high != null)) {
      const interval = {
        type: 'scatter',
        mode: 'lines',
        x,
        showlegend: false,
        hoverinfo: 'skip',
        line: { width: 0, shape: 'hv' },
      } as const;
      traces.push(
        { ...interval, y: discovery.map(({ low }) => low ?? null) },
        {
          ...interval,
          y: discovery.map(({ high }) => high ?? null),
          fill: 'tonexty',
          fillcolor: bandColor(color),
        },
      );
    }
    traces.push({
      type: 'scatter',
      name: strategy,
      mode: 'lines',
      x,
      y: discovery.map(({ median }) => median),
      line: { color, shape: 'hv' },
    });
    return traces;
  });
}

function survivalTraces(groups: Group[], theme: Palette): Traces {
  return groups.flatMap(({ strategy, survival }, index): Traces => {
    if (!survival.length) return [];
    const color = strategyColor(theme, index);
    const censored = survival.filter((point) => point.censored > 0);
    return [
      {
        type: 'scatter',
        name: strategy,
        mode: 'lines',
        x: survival.map(({ simulations }) => simulations),
        y: survival.map(({ probability }) => probability),
        line: { color, shape: 'hv' },
      },
      {
        type: 'scatter',
        name: strategy,
        mode: 'markers',
        x: censored.map(({ simulations }) => simulations),
        y: censored.map(({ probability }) => probability),
        text: censored.map(
          ({ censored: count, simulations }) =>
            `${strategy}, ${String(count)} censored at ${String(simulations)} simulations`,
        ),
        hoverinfo: 'text',
        showlegend: false,
        marker: { color, symbol: 'circle-open', size: 9 },
      },
    ];
  });
}

function EvidenceChart({
  title,
  traces,
  theme,
  description,
  xaxis,
  yaxis,
}: {
  title: string;
  traces: Traces;
  theme: Palette;
  description?: string | undefined;
  xaxis: Axis;
  yaxis?: Axis;
}) {
  return (
    <section className={styles['figure']} aria-label={title}>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      <Chart
        data={traces}
        layout={{
          autosize: true,
          height: 245,
          paper_bgcolor: 'transparent',
          plot_bgcolor: 'transparent',
          font: { color: theme['--ink'] },
          margin: { l: 48, r: 12, b: 50, t: 10 },
          showlegend: false,
          xaxis: { ...xaxis, automargin: true, gridcolor: theme['--grid-line'] },
          yaxis: { ...yaxis, automargin: true, gridcolor: theme['--grid-line'] },
        }}
        config={config}
        style={{ width: '100%' }}
        useResizeHandler
      />
    </section>
  );
}

function MetricBoxes({
  metric,
  groups,
  theme,
}: {
  metric: string;
  groups: Group[];
  theme: Palette;
}) {
  const title = `${metric} per-cell samples`;
  const traces = groups.flatMap((group, index): Traces => {
    const sample = group.metric_samples[metric];
    return sample?.length
      ? [
          {
            type: 'box',
            orientation: 'h',
            name: group.strategy,
            x: sample,
            marker: { color: strategyColor(theme, index) },
            boxpoints: 'outliers',
          },
        ]
      : [];
  });
  const missing = groups.filter((group) => !group.metric_samples[metric]?.length);
  return (
    <div>
      {traces.length > 0 ? (
        <EvidenceChart
          title={title}
          traces={traces}
          theme={theme}
          xaxis={metric === 'MET-01' ? { tickformat: '.0%' } : { title: { text: 'Simulations' } }}
          description={
            metric === 'MET-03'
              ? 'Observed first failures only. Censored cells appear in the survival curve.'
              : undefined
          }
        />
      ) : (
        <h3>{title}</h3>
      )}
      {missing.length > 0 && (
        <p>No observed values for {missing.map(({ strategy }) => strategy).join(', ')}.</p>
      )}
    </div>
  );
}

export function ExperimentCharts({ id }: { id: string }) {
  const { preference } = useTheme();
  const darkScheme = useSyncExternalStore(subscribeScheme, isDarkScheme);
  const theme = tokens[preference === 'system' ? (darkScheme ? 'dark' : 'light') : preference];
  const query = useQuery({
    queryKey: ['experiments', id, 'comparison', 'charts'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/experiments/{experiment_id}/comparison/charts', {
          signal,
          params: { path: { experiment_id: id } },
        }),
      ),
  });
  if (query.isPending) return <p role="status">Loading chart evidence…</p>;
  if (query.isError)
    return <p role="alert">Unable to load chart evidence. {query.error.message}</p>;
  const { groups, metrics, confidence, excluded_cells: excludedCells } = query.data;
  if (!groups.length) return <p>Charts will appear when completed cells have recorded runs.</p>;
  const discovery = discoveryTraces(groups, theme);
  const survival = survivalTraces(groups, theme);
  const simulations = { title: { text: 'Simulations' }, rangemode: 'tozero' } as const;

  return (
    <section className={styles['charts']} aria-label="Comparison charts">
      <h2>Comparison charts</h2>
      <ul className={styles['legend']}>
        {groups.map((group, index) => (
          <li key={group.strategy}>
            <span aria-hidden="true" style={{ backgroundColor: strategyColor(theme, index) }} />
            {group.strategy} ({group.observed_cells} completed, {group.analyzed_cells} analyzed)
          </li>
        ))}
      </ul>
      {excludedCells > 0 && (
        <p>
          {excludedCells} {excludedCells === 1 ? 'cell lacks' : 'cells lack'} completed run
          evidence.
        </p>
      )}
      <Suspense fallback={<p role="status">Loading comparison plots…</p>}>
        {discovery.length ? (
          <EvidenceChart
            title="Mode discovery"
            traces={discovery}
            theme={theme}
            xaxis={simulations}
            yaxis={{ title: { text: 'Unique modes' }, rangemode: 'tozero' }}
            description={`Median counts over the common observed horizon. Shading shows pointwise ${String(Math.round(confidence * 100))}% bootstrap intervals where at least two cells were analyzed.`}
          />
        ) : (
          <p>Discovery curves require a final mode analysis.</p>
        )}
        {survival.length > 0 && (
          <EvidenceChart
            title="Time to first failure (MET-03)"
            traces={survival}
            theme={theme}
            xaxis={simulations}
            yaxis={{ title: { text: 'Without a failure' }, tickformat: '.0%', range: [0, 1.05] }}
            description="Open markers show right-censoring at the last observed simulation."
          />
        )}
        {metrics.map((metric) => (
          <MetricBoxes key={metric} metric={metric} groups={groups} theme={theme} />
        ))}
      </Suspense>
    </section>
  );
}
