import { lazy, Suspense, useState } from 'react';
import { ProblemError } from '../../../api/client';
import { useImportance } from '../../../api/hooks';
import { loadPlotly } from '../../../components/charts/plotly';
import { number, object } from '../../runs/runData';

const Chart = lazy(loadPlotly);
const format = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });

function values(raw: unknown): unknown[] {
  return Array.isArray(raw) ? raw : [];
}

function metric(raw: unknown, deviation: unknown) {
  const value = number(raw);
  const spread = number(deviation);
  if (value === undefined) return 'Unavailable';
  return spread === undefined
    ? format.format(value)
    : `${format.format(value)} ± ${format.format(spread)}`;
}

export function InsightsPanel({ campaignId }: { campaignId: string }) {
  const query = useImportance(campaignId);
  const [mode, setMode] = useState('');
  const info = object(query.data?.importance);
  const names = values(info['names']);
  const global = values(info['mean_abs_shap']);
  const byMode = object(info['per_mode']);
  const selectedMode = Object.hasOwn(byMode, mode) ? mode : '';
  const shap = selectedMode ? values(byMode[selectedMode]) : global;
  const gp = values(info['gp_normalized']);
  const disagreements = new Set(values(info['disagreement']));
  const parameters = names.flatMap((name, index) => {
    const value = number(shap[index]);
    return typeof name === 'string' && value !== undefined ? [{ name, index, value }] : [];
  });
  const ranked = [...parameters].sort((a, b) => b.value - a.value);
  const gpRanked = parameters
    .flatMap((param) => {
      const score = number(gp[param.index]);
      return score === undefined ? [] : [{ name: param.name, score }];
    })
    .sort((a, b) => b.score - a.score);
  const matrix = values(info['interactions']);
  const text = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim();
  const layout = {
    autosize: true,
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: text },
    margin: { l: 32, r: 32, b: 40, t: 20 },
  };
  const config = { displaylogo: false, responsive: true, displayModeBar: false } as const;
  if (query.isPending) return <p role="status">Loading explanation…</p>;
  if (query.error && !(query.error instanceof ProblemError && query.error.status === 404))
    return <p role="alert">{query.error.message}</p>;
  if (!parameters.length) return <p>Run full campaign analysis to see parameter importance.</p>;
  return (
    <div>
      <label>
        Importance scope{' '}
        <select
          value={selectedMode}
          onChange={(event) => {
            setMode(event.target.value);
          }}
        >
          <option value="">Campaign</option>
          {Object.keys(byMode)
            .sort()
            .map((code) => (
              <option key={code}>{code}</option>
            ))}
        </select>
      </label>
      <section aria-label="Model quality">
        <h2>Cross-validation</h2>
        <dl>
          <dt>AUC</dt>
          <dd>{metric(info['auc_mean'], info['auc_std'])}</dd>
          <dt>Balanced accuracy</dt>
          <dd>{metric(info['balanced_acc_mean'], info['balanced_acc_std'])}</dd>
        </dl>
        {info['low_confidence'] === true ? (
          <p>
            <strong>Low confidence.</strong> The available cross-validation evidence is limited.
            Treat the rankings as exploratory.
          </p>
        ) : null}
      </section>
      <section aria-label="SHAP parameter importance">
        <h2>Parameter importance</h2>
        <p>
          Highest SHAP importance:{' '}
          {ranked
            .slice(0, 3)
            .map(({ name }) => name)
            .join(', ')}
          .
        </p>

        <table>
          <caption>SHAP and GP lengthscale comparison</caption>
          <thead>
            <tr>
              <th>Parameter</th>
              <th>Mean absolute SHAP</th>
              <th>GP rank</th>
              <th>Agreement</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map(({ name, value }) => {
              const gpRank = gpRanked.findIndex((parameter) => parameter.name === name);
              return (
                <tr key={name}>
                  <th scope="row">{name}</th>
                  <td>
                    <meter
                      min={0}
                      max={Math.max(Number.EPSILON, ranked[0]?.value ?? 0)}
                      value={value}
                      aria-label={`${name} mean absolute SHAP`}
                    />{' '}
                    {format.format(value)}
                  </td>
                  <td>{gpRank < 0 ? 'Unavailable' : gpRank + 1}</td>
                  <td>{disagreements.has(name) ? 'Disagreement' : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {matrix.length ? (
        <section aria-label="Campaign SHAP interactions">
          <h2>Campaign interactions</h2>
          <Suspense fallback={<p role="status">Loading chart…</p>}>
            <Chart
              data={[
                {
                  type: 'heatmap',
                  x: parameters.map(({ name }) => name),
                  y: parameters.map(({ name }) => name),
                  z: parameters.map(({ index }) =>
                    parameters.map(
                      (parameter) => number(values(matrix[index])[parameter.index]) ?? null,
                    ),
                  ),
                },
              ]}
              layout={{ ...layout, yaxis: { automargin: true }, xaxis: { automargin: true } }}
              config={config}
              style={{ width: '100%' }}
              useResizeHandler
            />
          </Suspense>
        </section>
      ) : null}
    </div>
  );
}
