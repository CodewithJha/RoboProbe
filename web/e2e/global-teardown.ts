import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

export default function globalTeardown(): void {
  execSync('bash scripts/e2e_stack.sh down', { cwd: root, stdio: 'inherit' });
}
