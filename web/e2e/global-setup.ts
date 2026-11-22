import { execFile } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import type { FullConfig } from '@playwright/test';
import { seed } from './seed.ts';

const root = resolve(import.meta.dirname, '../..');
const reportDir = join(root, 'web/e2e-artifacts');
const run = promisify(execFile);
const BUILD_TIMEOUT_MS = 420_000;
const START_TIMEOUT_MS = 180_000;
const SEED_TIMEOUT_MS = 90_000;
const COMMAND_TIMEOUT_MS = 30_000;
const OUTPUT_LIMIT = 8 * 1024 * 1024;
const SEED_SCRIPT = [
  'import sys',
  'from roboprobe.core.settings import load_settings',
  'sys.path.insert(0, "/e2e-seed")',
  'from load_seed import load_seed',
  'settings = load_settings()',
  'load_seed(settings.database.url.get_secret_value(), settings.storage.artifact_root)',
].join('\n');
const HEALTH_SCRIPT = [
  'from urllib.request import Request, urlopen',
  'from roboprobe.core.settings import load_settings',
  'api = load_settings().api',
  'headers = {"Authorization": "Bearer " + api.token.get_secret_value()} if api.token else {}',
  'request = Request(f"http://127.0.0.1:{api.port}/health/ready", headers=headers)',
  'with urlopen(request, timeout=5) as response:',
  '    print(response.read().decode())',
].join('\n');

export async function startE2eStack(baseURL: string) {
  const browserURL = new URL(baseURL);
  if (
    browserURL.protocol !== 'http:' ||
    !['localhost', '127.0.0.1'].includes(browserURL.hostname)
  ) {
    throw new Error('E2E_BASE_URL must use HTTP on localhost or 127.0.0.1.');
  }
  const project = process.env['E2E_COMPOSE_PROJECT'] ?? `roboprobe-e2e-${String(process.pid)}`;
  if (!/^roboprobe-e2e-[a-z0-9-]+$/.test(project)) {
    throw new Error('E2E_COMPOSE_PROJECT must be a dedicated roboprobe-e2e-* project.');
  }
  const secretDir = await mkdtemp(join(tmpdir(), 'roboprobe-e2e-'));
  const apiToken = randomBytes(32).toString('hex');
  const databasePasswordFile = join(secretDir, 'db_password');
  const apiTokenFile = join(secretDir, 'api_token');
  const env = {
    ...process.env,
    ROBOPROBE_IMAGE_TAG: project,
    ROBOPROBE_WEB_PORT: browserURL.port || '80',
    E2E_DB_PASSWORD_FILE: databasePasswordFile,
    E2E_API_TOKEN_FILE: apiTokenFile,
  };
  const composeFlags = [
    'compose',
    '--project-name',
    project,
    '--env-file',
    'docker/e2e.env',
    '-f',
    'docker/compose.yaml',
    '-f',
    'docker/e2e.compose.yaml',
    '--profile',
    'core',
    '--profile',
    'app',
  ];
  const compose = (args: string[], timeout = COMMAND_TIMEOUT_MS) =>
    run('docker', [...composeFlags, ...args], {
      cwd: root,
      env,
      timeout,
      maxBuffer: OUTPUT_LIMIT,
    });
  const cleanup = async () => {
    try {
      await mkdir(reportDir, { recursive: true });
      const logs = await compose(['logs', '--no-color']);
      await writeFile(join(reportDir, 'compose.log'), logs.stdout + logs.stderr);
    } finally {
      try {
        await compose(['down', '--volumes', '--remove-orphans']);
      } finally {
        await rm(secretDir, { recursive: true, force: true });
      }
    }
  };
  try {
    await Promise.all([
      rm(join(reportDir, 'compose.log'), { force: true }),
      rm(join(reportDir, 'compose-setup-error.txt'), { force: true }),
      writeFile(databasePasswordFile, randomBytes(32).toString('hex'), { mode: 0o444 }),
      writeFile(apiTokenFile, apiToken, { mode: 0o444 }),
    ]);
    // The API, orchestrator and workers all use the backend image built for migrate.
    await compose(['build', 'migrate', 'web'], BUILD_TIMEOUT_MS);
    await compose(['up', '--no-build', '-d', '--wait', '--wait-timeout', '150'], START_TIMEOUT_MS);
    await compose(
      [
        'run',
        '--no-deps',
        '--rm',
        '-T',
        '--volume',
        `${join(root, 'backend/tests/fixtures/db')}:/e2e-seed:ro`,
        '--entrypoint',
        'python',
        'api',
        '-c',
        SEED_SCRIPT,
      ],
      SEED_TIMEOUT_MS,
    );
    await compose(['exec', '-T', 'api', 'python', '-c', HEALTH_SCRIPT]);
    const campaigns = await fetch(new URL('/api/v1/campaigns', browserURL), {
      headers: { Authorization: `Bearer ${apiToken}` },
      signal: AbortSignal.timeout(COMMAND_TIMEOUT_MS),
    });
    if (!campaigns.ok || !campaigns.headers.get('content-type')?.includes('application/json')) {
      throw new Error(
        `The dashboard proxy returned ${String(campaigns.status)} instead of campaigns.`,
      );
    }
    // The imported campaign retains its historical space version. Register the shipped
    // definition separately so new Wizard campaigns can run against the current task files.
    const spaceId = seed.campaign.space.id;
    const definition = await readFile(
      join(root, 'configs/scenario_spaces', `${spaceId}.yaml`),
      'utf8',
    );
    const space = await fetch(new URL('/api/v1/spaces', browserURL), {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiToken}`, 'Content-Type': 'application/yaml' },
      body: definition,
      signal: AbortSignal.timeout(COMMAND_TIMEOUT_MS),
    });
    if (!space.ok) {
      throw new Error(`Registering the shipped Wizard space returned ${String(space.status)}.`);
    }
    const registered: unknown = await space.json();
    if (
      !registered ||
      typeof registered !== 'object' ||
      !('id' in registered) ||
      registered.id !== spaceId ||
      !('version' in registered) ||
      typeof registered.version !== 'string' ||
      !registered.version
    ) {
      throw new Error('The Wizard space registration did not return an id and version.');
    }
    return { apiToken, cleanup, wizardSpaceVersion: registered.version };
  } catch (error) {
    const errors: unknown[] = [error];
    try {
      await mkdir(reportDir, { recursive: true });
      const output =
        error instanceof Error && 'stdout' in error && typeof error.stdout === 'string'
          ? error.stdout
          : '';
      await writeFile(join(reportDir, 'compose-setup-error.txt'), `${String(error)}\n${output}`);
    } catch (reportError) {
      errors.push(reportError);
    }
    await cleanup().catch((cleanupError: unknown) => {
      errors.push(cleanupError);
    });
    if (errors.length > 1)
      throw new AggregateError(errors, 'Compose setup and diagnostics failed.');
    throw error;
  }
}

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL;
  if (!baseURL) throw new Error('The Playwright project must declare a base URL.');
  const { apiToken, cleanup, wizardSpaceVersion } = await startE2eStack(baseURL);
  process.env['E2E_API_TOKEN'] = apiToken;
  process.env['E2E_WIZARD_SPACE_VERSION'] = wizardSpaceVersion;
  return cleanup;
}
