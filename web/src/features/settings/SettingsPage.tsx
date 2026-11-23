import { useContext, useState } from 'react';
import { getToken, setToken } from '../../lib/token';
import { useMeta } from '../../api/hooks';
import { SseContext, useRuntimeConfig, useSseStatus, useTheme } from '../../app/contexts';
import { numberLocaleOptions, type NumberLocaleChoice } from '../../lib/numberLocale';
import { useNumberLocale } from '../../lib/NumberLocaleProvider';
import { ProblemView } from '../../app/ProblemView';

export function Component() {
  const config = useRuntimeConfig();
  const meta = useMeta();
  const { preference, setPreference } = useTheme();
  const { choice, setChoice } = useNumberLocale();
  const sse = useContext(SseContext);
  const status = useSseStatus();
  const [token, setTokenInput] = useState(() => getToken() ?? '');
  const [masked, setMasked] = useState(true);
  const [tested, setTested] = useState<'idle' | 'ok' | 'fail'>('idle');

  return (
    <section>
      <p className="page-label">RoboProbe / Settings</p>
      <h1>Settings</h1>
      <p className="page-description">Session credentials, display and live connection.</p>
      <p>
        Local installs: after <code>make up</code>, copy the token from{' '}
        <code>secrets/api_token</code> in the repository root, paste it below, then choose{' '}
        <strong>Save token</strong>.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <fieldset>
          <legend>API token</legend>
          <label htmlFor="api-token">Bearer token (session only)</label>
          <input
            id="api-token"
            type={masked ? 'password' : 'text'}
            autoComplete="off"
            value={token}
            onChange={(event) => {
              setTokenInput(event.target.value);
              setTested('idle');
            }}
          />
          <button
            type="button"
            onClick={() => {
              setMasked((value) => !value);
            }}
          >
            {masked ? 'Show' : 'Hide'}
          </button>
          <button
            type="button"
            onClick={() => {
              setToken(token.trim() || null);
            }}
          >
            Save token
          </button>
          <button
            type="button"
            onClick={() => {
              setToken(token.trim() || null);
              void meta.refetch().then(
                () => {
                  setTested('ok');
                },
                () => {
                  setTested('fail');
                },
              );
            }}
          >
            Test connection
          </button>
          {tested === 'ok' ? <p role="status">Connection OK.</p> : null}
          {tested === 'fail' ? <p role="alert">Connection failed.</p> : null}
          {meta.isError && tested !== 'idle' ? <ProblemView error={meta.error} /> : null}
        </fieldset>
        <fieldset>
          <legend>Theme</legend>
          <label htmlFor="theme">Notebook theme</label>
          <select
            id="theme"
            value={preference}
            onChange={(event) => {
              setPreference(event.target.value as typeof preference);
            }}
          >
            <option value="system">System</option>
            <option value="light">Paper</option>
            <option value="dark">Night Shift</option>
          </select>
        </fieldset>
        <fieldset>
          <legend>Numbers</legend>
          <label htmlFor="number-locale">Number format</label>
          <select
            id="number-locale"
            value={choice}
            onChange={(event) => {
              setChoice(event.target.value as NumberLocaleChoice);
            }}
          >
            {numberLocaleOptions.map((option) => (
              <option key={option} value={option}>
                {option === 'system' ? 'Browser default' : option}
              </option>
            ))}
          </select>
        </fieldset>
        <fieldset>
          <legend>Live updates</legend>
          <p>
            SSE status: <strong>{status}</strong>
          </p>
          <button
            type="button"
            onClick={() => {
              sse?.connect();
            }}
          >
            Reconnect
          </button>
        </fieldset>
        <p>
          API <code>{config.apiBaseUrl}</code> · dashboard theme default {config.defaultTheme} · API
          version {typeof meta.data?.['api_version'] === 'string' ? meta.data['api_version'] : '…'}{' '}
          · RoboProbe {typeof meta.data?.['version'] === 'string' ? meta.data['version'] : '…'}
        </p>
      </form>
    </section>
  );
}
