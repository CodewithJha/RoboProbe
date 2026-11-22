import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

export default function globalSetup(): void {
  execSync('bash scripts/e2e_stack.sh up', {
    cwd: root,
    stdio: 'inherit',
    env: {
      ...process.env,
      E2E_BASE_URL: process.env['E2E_BASE_URL'] ?? 'http://127.0.0.1:8080',
    },
  });
}
