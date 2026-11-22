// ESLint flat config for the RoboProbe dashboard (doc 16 §4): typescript-eslint strict (type-aware),
// react-hooks, jsx-a11y, Prettier compatibility, and a ban on raw HTML injection (doc 31 TM-05).
import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import playwright from 'eslint-plugin-playwright';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules', 'src/api/schema.d.ts', 'playwright-report', 'e2e-results'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.strictTypeChecked,
      ...tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat.recommended,
      jsxA11y.flatConfigs.strict,
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { 'react-refresh': reactRefresh },
    rules: {
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: 'Raw HTML injection is forbidden (doc 31 TM-05); render text through React.',
        },
        {
          selector: "Property[key.name='dangerouslySetInnerHTML']",
          message: 'Raw HTML injection is forbidden (doc 31 TM-05); render text through React.',
        },
      ],
    },
  },
  {
    files: ['vite.config.ts'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended, prettier],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['e2e/**/*.ts', 'playwright.config.ts'],
    extends: [playwright.configs['flat/recommended']],
    rules: { 'playwright/no-wait-for-timeout': 'error' },
  },
);
