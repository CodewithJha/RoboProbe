import { useState, type SubmitEvent } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ProblemError, requireData, type Schema } from '../../../api/client';
import { useCampaign, useModes, useReplay, useSpace } from '../../../api/hooks';
import { number, object } from '../../runs/runData';
import styles from './CasebookGrid.module.css';

type Mode = Schema['FailureModeOut'];
type ModePage = Schema['Page_FailureModeOut_'];
type Status = NonNullable<Schema['FailureModePatch']['status']>;
const statuses: Status[] = ['open', 'accepted', 'fixed', 'duplicate'];
const format = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });

function display(value: unknown) {
  const n = number(value);
  return n === undefined ? 'Unavailable' : format.format(n);
}

function CaseCard({
  mode,
  modes,
  definitions,
}: {
  mode: Mode;
  modes: Mode[];
  definitions: Readonly<Record<string, unknown>>[];
}) {
  const queryClient = useQueryClient();
  const key = ['campaigns', mode.campaign_id, 'modes'];
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(mode.label);
  const [duplicate, setDuplicate] = useState(false);
  const [target, setTarget] = useState('');
  const [message, setMessage] = useState('');
  const replay = useReplay(mode.medoid_run_id ?? '');
  const interaction = object(mode.interaction);
  const interactionStatus = interaction['status'];
  const patch = useMutation({
    mutationFn: async (body: Schema['FailureModePatch']) =>
      requireData(
        await api.PATCH('/api/v1/modes/{mode_id}', {
          params: { path: { mode_id: mode.id } },
          headers: { 'If-Match': `W/"${String(mode.version)}"` },
          body,
        }),
      ),
    onMutate: async (body) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient
        .getQueryData<ModePage>(key)
        ?.items.find((item) => item.id === mode.id);
      queryClient.setQueryData<ModePage>(
        key,
        (page) =>
          page && {
            ...page,
            items: page.items.map((row) =>
              row.id === mode.id
                ? { ...row, label: body.label ?? row.label, status: body.status ?? row.status }
                : row,
            ),
          },
      );
      setMessage('');
      return previous;
    },
    onSuccess: (updated) => {
      if (updated.id)
        queryClient.setQueryData<ModePage>(
          key,
          (page) =>
            page && {
              ...page,
              items: page.items.map((row) => (row.id === mode.id ? updated : row)),
            },
        );
    },
    onError: (error, _body, previous) => {
      if (previous)
        queryClient.setQueryData<ModePage>(
          key,
          (page) =>
            page && {
              ...page,
              items: page.items.map((row) => (row.id === mode.id ? previous : row)),
            },
        );
      setMessage(
        error instanceof ProblemError && error.status === 412
          ? 'Changed elsewhere. The latest version is shown.'
          : error.message,
      );
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const confirm = useMutation({
    mutationFn: async () =>
      requireData(
        await api.POST('/api/v1/modes/{mode_id}:confirm-interaction', {
          params: { path: { mode_id: mode.id } },
        }),
      ),
  });
  const best = (mode.rules ?? [])
    .map(object)
    .sort((a, b) => (number(b['precision']) ?? 0) - (number(a['precision']) ?? 0))[0];
  const conditions = Array.isArray(best?.['conditions'])
    ? (best['conditions'] as unknown[]).map(object)
    : [];
  function rename(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (label.trim()) {
      patch.mutate({ label: label.trim() });
      setEditing(false);
    }
  }
  async function exportScenario(runId: string) {
    try {
      const result = await api.GET('/api/v1/runs/{run_id}/scenario.yaml', {
        params: { path: { run_id: runId } },
        parseAs: 'blob',
      });
      const url = URL.createObjectURL(requireData(result));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${runId}-scenario.yaml`;
      anchor.click();
      setTimeout(() => {
        URL.revokeObjectURL(url);
      }, 0);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Scenario export failed');
    }
  }
  return (
    <article className={styles['card']}>
      <header>
        <strong>
          {mode.code} {mode.provisional ? <small>Provisional</small> : null}
        </strong>
        <span>
          {mode.primary_class} · {mode.size} runs
        </span>
      </header>
      {editing ? (
        <form onSubmit={rename}>
          <label>
            Case name{' '}
            <input
              value={label}
              onChange={(event) => {
                setLabel(event.target.value);
              }}
              required
              maxLength={80}
            />
          </label>
          <button type="submit">Save name</button>
          <button
            type="button"
            onClick={() => {
              setEditing(false);
            }}
          >
            Cancel
          </button>
        </form>
      ) : (
        <div className={styles['actions']}>
          <h2>{mode.label}</h2>
          <button
            type="button"
            disabled={patch.isPending}
            onClick={() => {
              setLabel(mode.label);
              setEditing(true);
            }}
          >
            Rename
          </button>
        </div>
      )}
      <label>
        Status{' '}
        <select
          value={duplicate ? 'duplicate' : mode.status}
          disabled={patch.isPending}
          onChange={(event) => {
            const status = statuses.find((choice) => choice === event.target.value);
            setDuplicate(status === 'duplicate');
            if (status && status !== 'duplicate') patch.mutate({ status });
          }}
        >
          {statuses.map((status) => (
            <option key={status}>{status}</option>
          ))}
        </select>
      </label>
      {duplicate ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (target) {
              patch.mutate({ status: 'duplicate', duplicate_of: target });
              setDuplicate(false);
            }
          }}
        >
          <label>
            Duplicate of{' '}
            <select
              required
              value={target}
              onChange={(event) => {
                setTarget(event.target.value);
              }}
            >
              <option value="">Select a case</option>
              {modes
                .filter((other) => other.id !== mode.id)
                .map((other) => (
                  <option key={other.id}>{other.code}</option>
                ))}
            </select>
          </label>
          <button type="submit">Save status</button>
          <button
            type="button"
            onClick={() => {
              setDuplicate(false);
            }}
          >
            Cancel
          </button>
        </form>
      ) : mode.duplicate_of ? (
        <small>Duplicate of {mode.duplicate_of}</small>
      ) : null}
      {(mode.characteristic ?? []).length ? (
        <dl>
          {mode.characteristic?.map((param) => {
            const range = object(mode.param_ranges?.[param]);
            const coverage = number(range['space_coverage']);
            const definition = definitions.find((item) => item['id'] === param);
            const lo = number(definition?.['low']);
            const hi = number(definition?.['high']);
            const a = number(range['q05']);
            const b = number(range['q95']);
            const rangeTrack =
              lo !== undefined && hi !== undefined && hi > lo && a !== undefined && b !== undefined
                ? [
                    Math.min(100, Math.max(0, ((a - lo) / (hi - lo)) * 100)),
                    Math.min(100, Math.max(0, ((b - lo) / (hi - lo)) * 100)),
                  ]
                : undefined;
            return (
              <div key={param}>
                <dt>{param}</dt>
                <dd>
                  {display(range['q05'])}–{display(range['q95'])}{' '}
                  {typeof range['unit'] === 'string' ? range['unit'] : ''}
                  {rangeTrack ? (
                    <svg
                      viewBox="0 0 100 10"
                      preserveAspectRatio="none"
                      className={styles['track']}
                      aria-hidden="true"
                    >
                      <path d="M 0 5 H 100" stroke="var(--ink-muted)" />
                      <path
                        d={`M ${String(rangeTrack[0])} 5 H ${String(rangeTrack[1])}`}
                        stroke="var(--accent)"
                        strokeWidth="7"
                      />
                    </svg>
                  ) : coverage !== undefined ? (
                    <meter
                      min={0}
                      max={1}
                      value={Math.min(1, Math.max(0, coverage))}
                      aria-label={`${param} range coverage`}
                    />
                  ) : null}
                </dd>
              </div>
            );
          })}
        </dl>
      ) : null}
      {best && conditions.length ? (
        <p>
          Rule{' '}
          {conditions
            .map(
              (condition) =>
                `${String(condition['param'])} ${String(condition['op'])} ${display(condition['threshold_physical'])}`,
            )
            .join(' ∧ ')}{' '}
          · Precision {display(best['precision'])} · Support {display(best['support'])}
        </p>
      ) : null}
      {mode.reproducibility != null ? <p>Reproducibility {display(mode.reproducibility)}</p> : null}
      {typeof interactionStatus === 'string' ? (
        <p>
          Interaction {interactionStatus.replaceAll('_', ' ')}
          {interactionStatus === 'CONFIRMED' && typeof interaction['order'] === 'number'
            ? ` ×${String(interaction['order'])}`
            : ''}
        </p>
      ) : null}
      <div className={styles['actions']}>
        {mode.medoid_run_id ? (
          <>
            <Link to={`/runs/${mode.medoid_run_id}`}>Medoid run</Link>
            <button
              type="button"
              disabled={replay.isPending}
              onClick={() => {
                replay.mutate({ repeats: 5, fresh_seeds: false });
              }}
            >
              Replay ×5
            </button>
          </>
        ) : null}
        {mode.minimal_run_id ? (
          <>
            <Link to={`/runs/${mode.minimal_run_id}`}>Minimal scenario</Link>
            <button
              type="button"
              onClick={() => {
                if (mode.minimal_run_id) void exportScenario(mode.minimal_run_id);
              }}
            >
              Export scenario
            </button>
          </>
        ) : null}
        <button
          type="button"
          disabled={confirm.isPending || confirm.isSuccess || typeof interactionStatus === 'string'}
          onClick={() => {
            confirm.mutate();
          }}
        >
          Confirm interaction
        </button>
      </div>
      {(confirm.isSuccess && typeof interactionStatus !== 'string') || replay.isSuccess ? (
        <p role="status">
          {confirm.isSuccess && typeof interactionStatus !== 'string'
            ? 'Confirmation pending'
            : 'Replay queued'}
        </p>
      ) : null}
      {message || confirm.error || replay.error ? (
        <p role="alert">
          {(message || undefined) ?? confirm.error?.message ?? replay.error?.message}
        </p>
      ) : null}
    </article>
  );
}

export function CasebookGrid({ campaignId }: { campaignId: string }) {
  const query = useModes(campaignId);
  const campaign = useCampaign(campaignId);
  const space = useSpace(campaign.data?.space?.id ?? '', campaign.data?.space?.version ?? '');
  const definition = space.data?.definition['parameters'];
  const definitions = Array.isArray(definition) ? definition.map(object) : [];
  const [status, setStatus] = useState('');
  const [failureClass, setFailureClass] = useState('');
  const [sort, setSort] = useState('size');
  const modes = query.data?.items ?? [];
  const rows = modes
    .filter(
      (mode) =>
        (!status || mode.status === status) &&
        (!failureClass || mode.primary_class === failureClass),
    )
    .sort((a, b) =>
      sort === 'size'
        ? b.size - a.size || a.code.localeCompare(b.code)
        : (a.first_seen_ordinal ?? Infinity) - (b.first_seen_ordinal ?? Infinity) ||
          a.code.localeCompare(b.code, undefined, { numeric: true }),
    );
  return (
    <section aria-labelledby="casebook-title">
      <h1 id="casebook-title">Casebook</h1>
      {query.isPending ? <p role="status">Loading cases…</p> : null}
      {query.error ? <p role="alert">{query.error.message}</p> : null}
      {query.isSuccess && !modes.length ? (
        <p>Run campaign analysis to identify failure modes.</p>
      ) : null}
      {modes.length ? (
        <div className={styles['actions']}>
          <label>
            Status{' '}
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
              }}
            >
              <option value="">All</option>
              {statuses.map((choice) => (
                <option key={choice}>{choice}</option>
              ))}
            </select>
          </label>
          <label>
            Failure class{' '}
            <select
              value={failureClass}
              onChange={(event) => {
                setFailureClass(event.target.value);
              }}
            >
              <option value="">All</option>
              {[...new Set(modes.map((mode) => mode.primary_class))].sort().map((choice) => (
                <option key={choice}>{choice}</option>
              ))}
            </select>
          </label>
          <label>
            Sort{' '}
            <select
              value={sort}
              onChange={(event) => {
                setSort(event.target.value);
              }}
            >
              <option value="size">Size</option>
              <option value="first-seen">First seen</option>
            </select>
          </label>
        </div>
      ) : null}
      {modes.length > 0 && !rows.length ? <p>No cases match the selected filters.</p> : null}
      <div className={styles['grid']}>
        {rows.map((mode) => (
          <CaseCard key={mode.id} mode={mode} modes={modes} definitions={definitions} />
        ))}
      </div>
    </section>
  );
}
