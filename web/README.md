# RoboProbe web

The RoboProbe dashboard ("Field Notebook", [doc 13](../docs/13-dashboard-ux-ui-spec.md)): Vite + React +
TypeScript (strict), built with pnpm.

```bash
corepack enable                 # provides the pnpm version pinned in package.json
pnpm --dir web install --frozen-lockfile
pnpm --dir web dev              # http://localhost:5173, proxies /api to VITE_API_PROXY_TARGET
pnpm --dir web lint             # ESLint (0 warnings) + Prettier check
pnpm --dir web typecheck        # tsc --build (strict)
pnpm --dir web test             # Vitest; `test:coverage` enforces the doc 18 §3 gate
pnpm --dir web build            # production bundle in web/dist
```

Environment variables are documented in [`.env.example`](.env.example) and
[doc 27 §4.11](../docs/27-configuration-reference.md#411-web-runtime-configjson-served-by-nginx-from-env).
Source layout follows [doc 13 §5](../docs/13-dashboard-ux-ui-spec.md#5-frontend-architecture).
