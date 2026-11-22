import { parameters } from '../../lib/spaceParameters';
import { isOnline, limit } from '../../lib/workers';
import { useRef, useState, type SubmitEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ProblemError } from '../../api/client';
import {
  useCreateCampaign,
  useMeta,
  useSpace,
  useSpaces,
  useSutProfiles,
  useWorkers,
} from '../../api/hooks';
import { useRuntimeConfig } from '../../app/contexts';
import {
  backends,
  errorStep,
  strategies,
  toYaml,
  validateRequest,
  type CampaignRequest,
  type Json,
} from './wizard/model';
import styles from './wizard/Wizard.module.css';
import { StrategyOptions } from './wizard/StrategyOptions';

const steps = ['Space', 'Robot & backend', 'Strategy', 'Review'] as const;
function freshSeed() {
  return crypto.getRandomValues(new Uint32Array(1))[0] ?? 0;
}

export function Component() {
  const config = useRuntimeConfig();
  const navigate = useNavigate();
  const spaces = useSpaces();
  const profiles = useSutProfiles();
  const workers = useWorkers();
  const meta = useMeta();
  const create = useCreateCampaign();
  const [step, setStep] = useState(0);
  const [selectedSpace, setSpace] = useState('');
  const [selectedBackend, setBackend] = useState('');
  const [selectedProfile, setProfile] = useState('');
  const [selectedStrategy, setStrategy] = useState('');
  const [pins, setPins] = useState<Record<string, number | string>>({});
  const [repeats, setRepeats] = useState(config.wizardDefaultRepeats);
  const [budget, setBudget] = useState<number>();
  const [batch, setBatch] = useState<number>();
  const [seed, setSeed] = useState(freshSeed);
  const [options, setOptions] = useState<Record<string, Json>>({});
  const [name, setName] = useState('');
  const [start, setStart] = useState(true);
  const [messages, setMessages] = useState<string[]>([]);
  const [copyStatus, setCopyStatus] = useState('');
  const title = useRef<HTMLHeadingElement>(null);
  const requestKey = useRef<{ payload: string; id: string } | null>(null);
  const allSpaces = spaces.data?.pages.flatMap((page) => page.items) ?? [];
  const spaceKey = (item: (typeof allSpaces)[number]) => JSON.stringify([item.id, item.version]);
  const space = allSpaces.find((item) => spaceKey(item) === selectedSpace) ?? allSpaces[0];
  const definition = useSpace(space?.id ?? '', space?.version ?? '');
  const params = parameters(definition.data?.definition).filter((param) => param.enabled);
  const backendList = backends(meta.data);
  const online =
    workers.data?.items.filter((worker) =>
      isOnline(worker, limit(meta.data, 'heartbeat_timeout_s')),
    ) ?? [];
  const workerCount = (id: string) => online.filter((worker) => worker.backend === id).length;
  const backend =
    backendList.find((item) => item.id === selectedBackend) ??
    backendList.find((item) => workerCount(item.id) > 0);
  const candidates =
    profiles.data?.pages
      .flatMap((page) => page.items)
      .filter((profile) => profile.backend === backend?.id) ?? [];
  const profile = candidates.find((item) => item.id === selectedProfile) ?? candidates[0];
  const strategyList = strategies(meta.data);
  const strategy = strategyList.find((item) => item.id === selectedStrategy) ?? strategyList[0];
  const maxBudget = limit(meta.data, 'max_budget');
  const maxBatch = limit(meta.data, 'max_batch_size');
  const runBudget = budget ?? Math.min(config.wizardDefaultBudget, maxBudget ?? Infinity);
  const batchSize =
    batch ?? Math.max(1, Math.min(workerCount(backend?.id ?? ''), maxBatch ?? Infinity));
  const payload: CampaignRequest = {
    ...(name.trim() ? { name: name.trim() } : {}),
    space: { id: space?.id ?? '', version: space?.version ?? '' },
    backend: backend?.id ?? '',
    ...(profile ? { sut_profile_id: profile.id } : {}),
    strategy: { id: strategy?.id ?? '', seed, params: options },
    budget: runBudget,
    batch_size: batchSize,
    repeats,
    pins,
    start,
  };
  const yaml = toYaml(payload);
  const duration =
    backend?.typicalSeconds && workerCount(backend.id)
      ? (runBudget * backend.typicalSeconds) / workerCount(backend.id)
      : undefined;

  function goTo(next: number) {
    setStep(next);
    requestAnimationFrame(() => title.current?.focus());
  }
  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessages([]);
    if (step === 0 && (!space || !definition.data)) {
      setMessages(['Choose an available scenario space version.']);
      return;
    }
    if (step === 1 && (!backend || !profile || workerCount(backend.id) === 0)) {
      setMessages(['Select a compatible robot profile and an online backend.']);
      return;
    }
    if (step >= 2) {
      const errors = validateRequest(payload, strategy);
      if (errors.length) {
        setMessages(errors.map((item) => `${item.pointer || '/'}: ${item.detail}`));
        goTo(errorStep(errors[0]?.pointer ?? ''));
        return;
      }
    }
    if (step < 3) {
      goTo(step + 1);
      return;
    }
    const serialized = JSON.stringify(payload);
    if (requestKey.current?.payload !== serialized)
      requestKey.current = { payload: serialized, id: crypto.randomUUID() };
    create.mutate(
      { body: payload, idempotencyKey: requestKey.current.id },
      {
        onSuccess: (campaign) => {
          void navigate(`/campaigns/${campaign.id}/console`);
        },
        onError: (error) => {
          if (error instanceof ProblemError && error.errors.length) {
            setMessages(error.errors.map((field) => `${field.pointer}: ${field.detail}`));
            goTo(errorStep(error.errors[0]?.pointer ?? ''));
          } else setMessages([error.message]);
        },
      },
    );
  }

  return (
    <section className={styles['page']}>
      <h1>New campaign</h1>
      <ol className={styles['steps']} aria-label="Campaign setup progress">
        {steps.map((label, i) => (
          <li key={label} aria-current={step === i ? 'step' : undefined}>
            {label}
          </li>
        ))}
      </ol>
      <form onSubmit={submit} className={styles['form']}>
        <h2 ref={title} tabIndex={-1}>
          {steps[step]}
        </h2>
        {messages.length ? (
          <ul role="alert">
            {messages.map((message, i) => (
              <li key={i}>{message}</li>
            ))}
          </ul>
        ) : null}
        {step === 0 ? (
          <>
            <label>
              Scenario space and version
              <select
                value={space ? spaceKey(space) : ''}
                onChange={(event) => {
                  setSpace(event.target.value);
                  setPins({});
                }}
                required
              >
                {allSpaces.length === 0 ? (
                  <option value="">
                    {spaces.isPending ? 'Loading spaces…' : 'No spaces registered'}
                  </option>
                ) : null}
                {allSpaces.map((item) => (
                  <option key={spaceKey(item)} value={spaceKey(item)}>
                    {item.name} · {item.version}
                  </option>
                ))}
              </select>
            </label>
            {spaces.hasNextPage ? (
              <button
                type="button"
                onClick={() => void spaces.fetchNextPage()}
                disabled={spaces.isFetchingNextPage}
              >
                Load more spaces
              </button>
            ) : null}
            {definition.isFetching ? <p role="status">Loading parameters…</p> : null}
            {spaces.isError || definition.isError ? (
              <p role="alert">Scenario spaces could not be loaded.</p>
            ) : null}
            {params.length ? (
              <p role="status">{params.length - Object.keys(pins).length} free parameters</p>
            ) : null}
            {params.map((param) => (
              <fieldset key={param.id}>
                <legend>
                  {param.name}
                  {param.unit ? ` (${param.unit})` : ''}
                </legend>
                <label className={styles['inline']}>
                  <input
                    type="checkbox"
                    checked={Object.hasOwn(pins, param.id)}
                    onChange={(event) => {
                      const checked = event.target.checked;
                      setPins((previous) => {
                        if (checked) return { ...previous, [param.id]: param.nominal };
                        return Object.fromEntries(
                          Object.entries(previous).filter(([id]) => id !== param.id),
                        );
                      });
                    }}
                  />{' '}
                  Pin {param.name}
                </label>
                {Object.hasOwn(pins, param.id) ? (
                  param.choices.length ? (
                    <label>
                      {param.name} value
                      <select
                        value={String(pins[param.id])}
                        onChange={(event) => {
                          setPins({ ...pins, [param.id]: event.target.value });
                        }}
                      >
                        {param.choices.map((choice) => (
                          <option key={choice}>{choice}</option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <label>
                      {param.name} value <output>{String(pins[param.id])}</output>
                      <input
                        type="range"
                        min={param.low}
                        max={param.high}
                        step={
                          param.type === 'int'
                            ? 1
                            : param.low !== undefined && param.high !== undefined
                              ? (param.high - param.low) / config.wizardSliderSteps
                              : 'any'
                        }
                        value={String(pins[param.id])}
                        onChange={(event) => {
                          setPins({ ...pins, [param.id]: event.target.valueAsNumber });
                        }}
                      />
                    </label>
                  )
                ) : null}
              </fieldset>
            ))}
          </>
        ) : null}
        {step === 1 ? (
          <>
            <label>
              Backend
              <select
                required
                value={backend?.id ?? ''}
                onChange={(event) => {
                  setBackend(event.target.value);
                  setProfile('');
                  setBatch(undefined);
                }}
              >
                {!backend ? <option value="">Select an online backend</option> : null}
                {backendList.map((item) => (
                  <option key={item.id} disabled={!workerCount(item.id)} value={item.id}>
                    {item.id} ·{' '}
                    {workerCount(item.id)
                      ? `${String(workerCount(item.id))} online`
                      : 'no online workers'}
                  </option>
                ))}
              </select>
            </label>
            {meta.isError || workers.isError ? (
              <p role="alert">Worker availability could not be verified.</p>
            ) : null}
            {!backend ? (
              <p>
                Start a worker to enable its backend. <Link to="/workbench">Open Workbench</Link>
              </p>
            ) : null}
            <label>
              Robot profile
              <select
                required
                value={profile?.id ?? ''}
                onChange={(event) => {
                  setProfile(event.target.value);
                }}
              >
                {!profile ? <option value="">No compatible profile on this page</option> : null}
                {candidates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </label>
            {profiles.hasNextPage ? (
              <button
                type="button"
                onClick={() => void profiles.fetchNextPage()}
                disabled={profiles.isFetchingNextPage}
              >
                Load more profiles
              </button>
            ) : null}
            <label>
              Repeats
              <input
                type="number"
                min={1}
                value={repeats || ''}
                required
                onChange={(event) => {
                  setRepeats(event.target.valueAsNumber || 0);
                }}
              />
            </label>
          </>
        ) : null}
        {step === 2 ? (
          <>
            <fieldset>
              <legend>Strategy</legend>
              <div className={styles['cards']}>
                {strategyList.map((item) => (
                  <label key={item.id} className={styles['card']}>
                    <input
                      type="radio"
                      name="strategy"
                      checked={strategy?.id === item.id}
                      onChange={() => {
                        setStrategy(item.id);
                        setOptions({});
                      }}
                    />
                    <span>
                      <strong>{item.id}</strong>
                      <br />
                      {item.description}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <label>
              Budget
              <input
                type="number"
                min={1}
                max={maxBudget}
                required
                value={runBudget || ''}
                onChange={(event) => {
                  setBudget(event.target.valueAsNumber || 0);
                }}
              />
            </label>
            <label>
              Batch size
              <input
                type="number"
                min={1}
                max={maxBatch}
                required
                value={batchSize || ''}
                onChange={(event) => {
                  setBatch(event.target.valueAsNumber || 0);
                }}
              />
            </label>
            <label>
              Seed
              <input
                type="number"
                min={0}
                max={Number.MAX_SAFE_INTEGER}
                required
                value={Number.isFinite(seed) ? seed : ''}
                onChange={(event) => {
                  setSeed(event.target.valueAsNumber);
                }}
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setSeed(freshSeed());
              }}
            >
              Randomize seed
            </button>
            {strategy ? (
              <StrategyOptions
                key={strategy.id}
                schema={strategy.schema}
                values={options}
                onChange={setOptions}
              />
            ) : null}
          </>
        ) : null}
        {step === 3 ? (
          <>
            <label>
              Campaign name (optional)
              <input
                value={name}
                maxLength={120}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            </label>
            <label className={styles['inline']}>
              <input
                type="checkbox"
                checked={start}
                onChange={(event) => {
                  setStart(event.target.checked);
                }}
              />{' '}
              Start now
            </label>
            <p>
              {duration === undefined
                ? 'Duration estimate unavailable'
                : `Estimated duration: ${Math.round(duration).toLocaleString()} seconds`}
            </p>
            <label>
              Campaign YAML
              <textarea readOnly rows={12} value={yaml} />
            </label>
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard
                  .writeText(yaml)
                  .then(() => {
                    setCopyStatus('YAML copied');
                  })
                  .catch(() => {
                    setCopyStatus('Select the YAML to copy it.');
                  });
              }}
            >
              Copy YAML
            </button>
            {copyStatus ? <p role="status">{copyStatus}</p> : null}
          </>
        ) : null}
        <div className={styles['actions']}>
          {step > 0 ? (
            <button
              type="button"
              disabled={create.isPending}
              onClick={() => {
                setMessages([]);
                goTo(step - 1);
              }}
            >
              Back
            </button>
          ) : (
            <Link to="/">Cancel</Link>
          )}
          <button type="submit" disabled={create.isPending}>
            {step < 3 ? 'Continue' : create.isPending ? 'Creating campaign…' : 'Create campaign'}
          </button>
        </div>
      </form>
    </section>
  );
}
