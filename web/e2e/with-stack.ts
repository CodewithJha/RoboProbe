import { spawn } from 'node:child_process';
import { startE2eStack } from './global-setup.ts';

const [command, ...args] = process.argv.slice(2);
if (!command || command === 'up' || command === 'down') {
  throw new Error('Pass the command to run inside the isolated E2E stack.');
}

const { apiToken, cleanup } = await startE2eStack(
  process.env['E2E_BASE_URL'] ?? 'http://127.0.0.1:8080',
);
try {
  const result = await new Promise<number>((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      env: { ...process.env, E2E_API_TOKEN: apiToken },
    });
    child.once('error', reject);
    child.once('close', (code) => {
      resolve(code ?? 1);
    });
  });
  process.exitCode = result;
} finally {
  await cleanup();
}
