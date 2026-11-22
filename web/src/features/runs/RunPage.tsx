import { useQuery } from '@tanstack/react-query';
import * as Dialog from '@radix-ui/react-dialog';
import { useState, type SubmitEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, type Schema } from '../../api/client';
import {
  useCampaign,
  useMeta,
  useReplay,
  useRun,
  useRunArtifacts,
  useRunTrace,
  useSpace,
} from '../../api/hooks';
import { RobustnessBar, VerdictNotch } from '../../components';
import { fetchWorld } from './charts/worldArtifact';
import { RunCharts } from './charts/RunCharts';
import { label, number, object, replayCommand, seconds } from './runData';
import styles from './RunPage.module.css';

function Drawer({
  title,
  button,
  children,
}: {
  title: string;
  button: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button type="button">{button}</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={styles['overlay']} />
        <Dialog.Content className={styles['drawer']} aria-describedby={undefined}>
          <Dialog.Title>{title}</Dialog.Title>
          {children}
          <Dialog.Close asChild>
            <button type="button">Close</button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

function ReplayForm({ run, maximum }: { run: Schema['RunOut']; maximum: number | undefined }) {
  const replay = useReplay(run.id);
  const navigate = useNavigate();
  const [repeats, setRepeats] = useState(1);
  const [fresh, setFresh] = useState(false);
  const [status, setStatus] = useState('');
  const canSubmit =
    Number.isSafeInteger(repeats) && repeats > 0 && (maximum === undefined || repeats <= maximum);

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    replay.mutate(
      { repeats, fresh_seeds: fresh },
      {
        onSuccess(result) {
          const ids = Array.isArray(result['run_ids'])
            ? result['run_ids'].filter((id) => typeof id === 'string')
            : [];
          void navigate(
            `/campaigns/${run.campaign_id}?highlight=${encodeURIComponent(ids.join(','))}`,
          );
        },
      },
    );
  }
  return (
    <form onSubmit={submit} className={styles['form']}>
      <label>
        Repeats{' '}
        <input
          type="number"
          required
          min={1}
          max={maximum}
          value={Number.isNaN(repeats) ? '' : repeats}
          onChange={(event) => {
            setRepeats(event.currentTarget.valueAsNumber);
          }}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={fresh}
          onChange={(event) => {
            setFresh(event.currentTarget.checked);
          }}
        />{' '}
        Use fresh seeds
      </label>
      <button type="submit" disabled={!canSubmit || replay.isPending}>
        {replay.isPending ? 'Queuing replay…' : 'Queue replay'}
      </button>
      <button
        type="button"
        disabled={!canSubmit}
        onClick={() => {
          void navigator.clipboard.writeText(replayCommand(run.id, repeats, fresh)).then(
            () => {
              setStatus('Replay command copied.');
            },
            () => {
              setStatus('Could not copy the replay command.');
            },
          );
        }}
      >
        Copy CLI command
      </button>
      {replay.isError ? <p role="alert">{replay.error.message}</p> : null}
      <p role="status">{status}</p>
    </form>
  );
}

function Parameters({
  run,
}: {
  run: Schema['RunOut'];
  campaign: Schema['CampaignOut'] | undefined;
}) {
  const version = object(object(run.manifest)['space']);
  const spaceId = typeof version['id'] === 'string' ? version['id'] : '';
  const spaceVersion = typeof version['version'] === 'string' ? version['version'] : '';
  const space = useSpace(spaceId, spaceVersion);
  const values = object(run.scenario['values']);
  const parameters = space.data?.definition['parameters'];
  const definitions = Array.isArray(parameters) ? parameters.map(object) : [];
  return (
    <section>
      <h2>Parameters</h2>
      {Object.keys(values).length === 0 ? (
        <p>No scenario values were recorded.</p>
      ) : (
        <dl className={styles['parameters']}>
          {Object.entries(values).map(([key, value]) => {
            const definition = definitions.find((item) => item['id'] === key);
            const low = number(definition?.['low']),
              high = number(definition?.['high']),
              nominal = number(definition?.['nominal']);
            const current = number(value);
            const hasRange =
              low !== undefined &&
              high !== undefined &&
              high > low &&
              nominal !== undefined &&
              current !== undefined;
            const unit = typeof definition?.['unit'] === 'string' ? definition['unit'] : '';
            return (
              <div key={key}>
                <dt>{key}</dt>
                <dd>
                  {label(value)} {unit}
                  {hasRange ? (
                    <>
                      <span
                        className={styles['track']}
                        aria-label={`Range ${String(low)} to ${String(high)}, nominal ${String(nominal)}`}
                      >
                        <i
                          style={{
                            insetInlineStart: `${String(((nominal - low) / (high - low)) * 100)}%`,
                          }}
                        />
                        <b
                          style={{
                            insetInlineStart: `${String(Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100)))}%`,
                          }}
                        />
                      </span>
                      <small>
                        Δ {(current - nominal).toFixed(3)} {unit}
                      </small>
                    </>
                  ) : null}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

function Oracles({ run }: { run: Schema['RunOut'] }) {
  if (run.verdict === 'INVALID') {
    const manifest = object(run.manifest);
    const reason =
      manifest['infra_error'] ?? manifest['invalid_reason'] ?? run.warnings?.join(', ');
    return (
      <section>
        <h2>Validity</h2>
        <p>
          {typeof reason === 'string' && reason.length > 0
            ? reason
            : 'The run failed the infrastructure validity check.'}
        </p>
      </section>
    );
  }
  return (
    <section>
      <h2>Oracles</h2>
      {!run.oracles?.length ? (
        <p>No oracle results were recorded.</p>
      ) : (
        <div className={styles['scroll']}>
          <table>
            <thead>
              <tr>
                <th>Oracle</th>
                <th>Robustness</th>
                <th>Violated</th>
                <th>First violation (s)</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {run.oracles.map((row, index) => (
                <tr key={`${label(row['oracle_id'])}-${String(index)}`}>
                  <th scope="row">{label(row['oracle_id'])}</th>
                  <td>
                    <RobustnessBar
                      value={number(row['robustness']) ?? Number.NaN}
                      label={`${label(row['oracle_id'])} robustness`}
                    />
                  </td>
                  <td>
                    {row['violated'] === true ? 'Yes' : row['violated'] === false ? 'No' : '—'}
                  </td>
                  <td>{label(row['first_violation_t'])}</td>
                  <td>
                    {row['details'] ? (
                      <details>
                        <summary>Details</summary>
                        <pre>{JSON.stringify(row['details'], null, 2)}</pre>
                      </details>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LoadedRun({ run }: { run: Schema['RunOut'] }) {
  const { id } = run;
  const campaign = useCampaign(run.campaign_id);
  const artifacts = useRunArtifacts(id);
  const trace = useRunTrace(id);
  const meta = useMeta();
  const [status, setStatus] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const hash = label(run.scenario['hash']);
  const bag = artifacts.data?.find((artifact) => artifact.kind === 'bag');
  const worldId = artifacts.data?.find((artifact) => artifact.kind === 'world')?.id ?? '';
  const world = useQuery({
    queryKey: ['run-world', worldId],
    enabled: Boolean(worldId),
    queryFn: ({ signal }) => fetchWorld(worldId, signal),
  });
  const verdict =
    run.verdict === 'PASS' || run.verdict === 'FAIL' || run.verdict === 'INVALID'
      ? run.verdict
      : undefined;

  async function downloadArtifact(artifact: Schema['ArtifactOut']) {
    setDownloadError('');
    try {
      const result = await api.GET('/api/v1/artifacts/{artifact_id}/content', {
        params: { path: { artifact_id: artifact.id } },
        parseAs: 'blob',
      });
      if (!result.data) throw new Error('Artifact has no content.');
      save(result.data, artifact.kind === 'bag' ? `${artifact.id}.mcap` : artifact.id);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'Download failed.');
    }
  }
  async function downloadScenario() {
    setDownloadError('');
    try {
      const result = await api.GET('/api/v1/runs/{run_id}/scenario.yaml', {
        params: { path: { run_id: id } },
        parseAs: 'blob',
      });
      if (!result.data) throw new Error('Scenario has no content.');
      save(result.data, `${id}-scenario.yaml`);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'Download failed.');
    }
  }
  return (
    <article className={styles['page']}>
      <header>
        <Link to={`/campaigns/${run.campaign_id}`}>Campaign console</Link>
        <h1>Run entry</h1>
        <p className={styles['verdict']}>
          {verdict ? (
            <>
              <VerdictNotch verdict={verdict} />
              <span aria-hidden="true">{verdict}</span>
            </>
          ) : (
            run.status
          )}
          {run.primary_failure ? <span>{run.primary_failure}</span> : null}
          {run.verdict !== 'INVALID' ? (
            <RobustnessBar value={run.robustness ?? Number.NaN} />
          ) : null}
        </p>
        {run.warnings?.length ? (
          <ul aria-label="Warnings">
            {run.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
        <dl className={styles['metadata']}>
          <div>
            <dt>Seed</dt>
            <dd>{run.seed}</dd>
          </div>
          <div>
            <dt>Scenario hash</dt>
            <dd>
              <button
                type="button"
                title={hash}
                disabled={hash === '—'}
                onClick={() => {
                  void navigator.clipboard.writeText(hash).then(
                    () => {
                      setStatus('Scenario hash copied.');
                    },
                    () => {
                      setStatus('Could not copy the scenario hash.');
                    },
                  );
                }}
              >
                {hash.length > 12 ? hash.slice(0, 12) + '…' : hash}
              </button>
            </dd>
          </div>
          <div>
            <dt>Worker</dt>
            <dd>{run.worker_id ?? '—'}</dd>
          </div>
          <div>
            <dt>Queued</dt>
            <dd>{seconds(run.timing?.['enqueued_at'], run.timing?.['started_at'])}</dd>
          </div>
          <div>
            <dt>Episode</dt>
            <dd>{seconds(run.timing?.['started_at'], run.timing?.['finished_at'])}</dd>
          </div>
        </dl>
        <div className={styles['actions']}>
          <Drawer title="Replay run" button="Replay">
            <ReplayForm
              run={run}
              maximum={number(object(meta.data?.['limits'])['max_manual_repeats'])}
            />
          </Drawer>
          <button
            type="button"
            onClick={() => {
              void downloadScenario();
            }}
          >
            Export scenario
          </button>
          {bag ? (
            <button
              type="button"
              onClick={() => {
                void downloadArtifact(bag);
              }}
            >
              Open bag
            </button>
          ) : null}
          <Drawer title="Run provenance" button="Provenance">
            <h3>Manifest</h3>
            {run.manifest ? (
              <pre>{JSON.stringify(run.manifest, null, 2)}</pre>
            ) : (
              <p>No manifest was recorded.</p>
            )}
            <h3>Artifacts</h3>
            {artifacts.isError ? (
              <p>Artifacts could not be loaded.</p>
            ) : artifacts.isPending ? (
              <p>Loading artifacts…</p>
            ) : artifacts.data.length ? (
              <ul>
                {artifacts.data.map((artifact) => (
                  <li key={artifact.id}>
                    <button
                      type="button"
                      onClick={() => {
                        void downloadArtifact(artifact);
                      }}
                    >
                      Download {artifact.kind}
                    </button>{' '}
                    <code>{artifact.sha256}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No artifacts were recorded.</p>
            )}
          </Drawer>
        </div>
        <p role="status">{status}</p>
        {downloadError ? <p role="alert">{downloadError}</p> : null}
      </header>
      <Parameters run={run} campaign={campaign.data} />
      <Oracles run={run} />
      {trace.data ? (
        <RunCharts trace={trace.data} run={run} {...(world.data ? { startMap: world.data } : {})} />
      ) : (
        <section>
          <h2>Trace</h2>
          <p>{trace.isPending ? 'Loading trace…' : 'The recorded trace is unavailable.'}</p>
        </section>
      )}
    </article>
  );
}

export function Component() {
  const { id = '' } = useParams();
  const run = useRun(id);
  if (run.isPending) return <p role="status">Loading run…</p>;
  if (run.isError) return <p role="alert">{run.error.message}</p>;
  return <LoadedRun key={id} run={run.data} />;
}
