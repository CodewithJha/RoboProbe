import type { Parameter } from '../../../lib/spaceParameters';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useReplay, type useRuns } from '../../../api/hooks';
import type { Schema } from '../../../api/client';
import { MarginRailSlot } from '../../../app/MarginRailSlot';
import { ProblemView } from '../../../app/ProblemView';
import { ConditionStrip, Spine, VerdictNotch, type Verdict } from '../../../components';
import { componentConfig } from '../../../components/config';
import { initialVirtualWindow } from '../../../components/virtualWindow';
import { registerShortcut } from '../../../lib/keyboard';
import { useRuntimeConfig } from '../../../app/contexts';
import { RationalePopover } from './RationalePopover';
import { prediction, rationaleFor, record } from './rationale';
import styles from '../Console.module.css';

const { rowHeight, viewportRows, overscan } = componentConfig;
const height = rowHeight * viewportRows;

function verdictFor(value: unknown): Verdict | undefined {
  return value === 'PASS' || value === 'FAIL' || value === 'INVALID' ? value : undefined;
}

function RunConditions({
  run,
  parameters,
}: {
  run: Schema['RunOut'];
  parameters: readonly Parameter[];
}) {
  const physical = record(run.scenario['values']);
  const conditions = parameters.flatMap((parameter) => {
    if (!parameter.enabled) return [];
    const value = physical[parameter.id];
    if (typeof value === 'string') {
      const index = parameter.choices.indexOf(value);
      return index < 0
        ? []
        : [
            {
              label: parameter.name,
              formatted: value,
              normalized: (index + 0.5) / parameter.choices.length,
            },
          ];
    }
    const { low, high } = parameter;
    if (typeof value !== 'number' || low === undefined || high === undefined) return [];
    if (parameter.type === 'int')
      return [
        {
          label: parameter.name,
          formatted: [value, parameter.unit].join(' ').trim(),
          normalized: (value - low + 0.5) / (high - low + 1),
        },
      ];
    const convert = parameter.scale === 'log' && low > 0 && value > 0 ? Math.log : (v: number) => v;
    const span = convert(high) - convert(low);
    return [
      {
        label: parameter.name,
        formatted: [value, parameter.unit].join(' ').trim(),
        normalized: span === 0 ? 0 : (convert(value) - convert(low)) / span,
      },
    ];
  });
  return conditions.length ? (
    <ConditionStrip
      size="xs"
      labels={conditions.map(({ label }) => label)}
      values={conditions.map(({ normalized }) => normalized)}
      formatted={conditions.map(({ formatted }) => formatted)}
    />
  ) : null;
}

function ReplayDialog({ run, dismiss }: { run: Schema['RunOut']; dismiss: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const replay = useReplay(run.id);
  const config = useRuntimeConfig();
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog ref={dialog} onClose={dismiss} aria-label={`Replay run ${String(run.ordinal)}`}>
      <h2>Replay run {run.ordinal}?</h2>
      <p>Queue this scenario again with its original seed.</p>
      {replay.isError ? <ProblemView error={replay.error} /> : null}
      <button type="button" onClick={() => dialog.current?.close()}>
        Close
      </button>
      <button
        type="button"
        disabled={replay.isPending}
        onClick={() => {
          replay.mutate(
            { repeats: config.consoleReplayRepeats, fresh_seeds: false },
            { onSuccess: dismiss },
          );
        }}
      >
        {replay.isPending ? 'Queuing…' : 'Queue replay'}
      </button>
    </dialog>
  );
}

export function EntryStream({
  runs,
  parameters,
}: {
  runs: ReturnType<typeof useRuns>;
  parameters: readonly Parameter[];
}) {
  const entries = useMemo(() => runs.data?.pages.flatMap((page) => page.items) ?? [], [runs.data]);
  const indexes = useMemo(() => new Map(entries.map((run, index) => [run.id, index])), [entries]);
  const ref = useRef<HTMLDivElement>(null);
  const previousHead = useRef<string | undefined>(undefined);
  const [selected, setSelected] = useState<string>();
  const [replaying, setReplaying] = useState<Schema['RunOut']>();
  const navigate = useNavigate();
  // eslint-disable-next-line react-hooks/incompatible-library -- The virtualizer remains local to this component.
  const virtual = useVirtualizer({
    count: entries.length,
    getScrollElement: () => ref.current,
    estimateSize: () => rowHeight,
    getItemKey: (index) => entries[index]?.id ?? index,
    initialRect: { width: 500, height },
    overscan,
  });
  useLayoutEffect(() => {
    const viewport = ref.current;
    const priorIndex = previousHead.current ? indexes.get(previousHead.current) : undefined;
    if (viewport && viewport.scrollTop > 0 && priorIndex) {
      viewport.scrollTop += priorIndex * rowHeight;
    }
    previousHead.current = entries[0]?.id;
  }, [entries, indexes]);

  useEffect(() => {
    function move(step: number) {
      const from = selected === undefined ? undefined : indexes.get(selected);
      const index = Math.min(entries.length - 1, Math.max(0, from === undefined ? 0 : from + step));
      setSelected(entries[index]?.id);
      if (index >= 0) virtual.scrollToIndex(index, { align: 'auto' });
    }
    function active() {
      return entries[selected === undefined ? 0 : (indexes.get(selected) ?? 0)];
    }
    const inStream = (event: KeyboardEvent) => event.target === ref.current;
    const inPage = (event: KeyboardEvent) =>
      !(event.target instanceof Element && event.target.closest('dialog, [popover]'));
    const unregister = [
      registerShortcut({
        keys: 'j',
        scope: 'feature',
        description: 'Select the next run',
        when: inPage,
        handler: () => {
          move(1);
        },
      }),
      registerShortcut({
        keys: 'k',
        scope: 'feature',
        description: 'Select the previous run',
        when: inPage,
        handler: () => {
          move(-1);
        },
      }),
      registerShortcut({
        keys: 'Enter',
        scope: 'feature',
        description: 'Inspect the selected run',
        when: inStream,
        handler: () => {
          const run = active();
          if (run) void navigate(`/runs/${run.id}`);
        },
      }),
      registerShortcut({
        keys: 'r',
        scope: 'feature',
        description: 'Replay the selected run',
        when: inPage,
        handler: () => {
          setReplaying(active());
        },
      }),
    ];
    return () => {
      unregister.forEach((dispose) => {
        dispose();
      });
    };
  }, [entries, indexes, navigate, selected, virtual]);

  const spineRuns = useMemo(
    () =>
      entries.flatMap((run) => {
        const verdict = verdictFor(run.verdict);
        return verdict ? [{ id: run.id, ordinal: run.ordinal, verdict }] : [];
      }),
    [entries],
  );
  const measured = virtual.getVirtualItems();
  const items = measured.length
    ? measured
    : initialVirtualWindow(entries.length, height, rowHeight);
  return (
    <section>
      <h2>Entry stream</h2>
      {runs.isPending ? <p role="status">Loading run entries…</p> : null}
      {runs.isError ? <ProblemView error={runs.error} /> : null}
      {!runs.isPending && !runs.isError && !entries.length ? (
        <p>No runs yet. Start a campaign to see its entries.</p>
      ) : null}
      <MarginRailSlot>
        <Spine
          runs={spineRuns}
          {...(selected ? { selectedId: selected } : {})}
          onSelect={(id) => {
            setSelected(id);
            const index = indexes.get(id);
            if (index !== undefined) virtual.scrollToIndex(index, { align: 'auto' });
          }}
        />
      </MarginRailSlot>
      {entries.length ? (
        <div
          className={styles['viewport']}
          ref={ref}
          role="region"
          aria-label="Newest campaign runs"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users need to focus the scroll region.
          tabIndex={0}
          style={{ maxHeight: height }}
        >
          <div className={styles['track']} style={{ height: virtual.getTotalSize() }}>
            {items.map((item) => {
              const run = entries[item.index];
              if (!run) return null;
              const verdict = verdictFor(run.verdict);
              const estimate = prediction(rationaleFor(run));
              return (
                <article
                  key={run.id}
                  className={styles['entry']}
                  data-selected={selected === run.id}
                  style={{ transform: `translateY(${String(item.start)}px)`, height: rowHeight }}
                >
                  <Link
                    to={`/runs/${run.id}`}
                    onFocus={() => {
                      setSelected(run.id);
                    }}
                  >
                    Run #{run.ordinal}
                  </Link>
                  {verdict ? <VerdictNotch verdict={verdict} /> : <span>{run.status}</span>}
                  {run.primary_failure ? <span>{run.primary_failure}</span> : null}
                  {typeof run.robustness === 'number' ? (
                    <span>
                      ρ {run.robustness >= 0 ? '+' : ''}
                      {run.robustness.toFixed(2)}
                    </span>
                  ) : null}
                  <RunConditions run={run} parameters={parameters} />
                  <span>{run.phase}</span>
                  {estimate ? <span>μ {estimate}</span> : null}
                  <RationalePopover run={run} />
                </article>
              );
            })}
          </div>
        </div>
      ) : null}
      {runs.hasNextPage ? (
        <button
          type="button"
          disabled={runs.isFetchingNextPage}
          onClick={() => {
            void runs.fetchNextPage();
          }}
        >
          Load older runs
        </button>
      ) : null}
      {replaying ? (
        <ReplayDialog
          run={replaying}
          dismiss={() => {
            setReplaying(undefined);
          }}
        />
      ) : null}
    </section>
  );
}
