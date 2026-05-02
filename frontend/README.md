# BagsVault — Frontend

React 19 + Tailwind dApp UI for the BagsVault privacy protocol. All on-chain interactions are mocked client-side via `WalletContext`.

## Stack

- **React 19** + **react-router-dom v7**
- **Tailwind CSS 3.4** + **shadcn/ui** (new-york style, neutral base)
- **CRACO** (build override on top of Create React App)
- **lucide-react** icons, **sonner** toasts, **recharts** charts

## Scripts

```bash
yarn install         # install deps
yarn start           # dev server on :3000 (hot reload)
yarn build           # production bundle into ./build
yarn test            # CRA test runner (Jest)
yarn lint            # eslint
yarn format          # prettier --write .
```

## Environment

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `REACT_APP_BACKEND_URL` | Base URL of FastAPI backend (e.g. `http://localhost:8000`) |
| `ENABLE_HEALTH_CHECK` | `true` to enable webpack health endpoints (see [`plugins/health-check`](./plugins/health-check)) |

## Source layout

```
src/
├── App.js              # Router + providers
├── index.js            # ReactDOM root
├── index.css           # Tailwind directives + global styles
├── App.css
├── pages/              # 6 routed pages
│   ├── Landing.jsx
│   ├── Deposit.jsx
│   ├── Withdraw.jsx
│   ├── Relayers.jsx
│   ├── Compliance.jsx
│   └── Architecture.jsx
├── components/
│   ├── Layout.jsx      # Sticky glassmorphic nav + footer
│   └── ui/             # shadcn/ui primitives (~45 components)
├── context/
│   └── WalletContext.jsx   # Mock wallet state (localStorage-persisted)
├── hooks/
│   └── use-toast.js
└── lib/
    └── utils.js        # cn() class merger
```

## Path aliases

`@/*` maps to `src/*` (configured in `craco.config.js` and `jsconfig.json`):

```js
import Landing from "@/pages/Landing";
```

## Build plugins

- **`plugins/health-check/`** — optional Express endpoints (`/health`, `/health/ready`, `/health/live`, `/health/errors`, `/health/stats`) wired into the webpack dev server. Toggle with `ENABLE_HEALTH_CHECK=true`.

## Conventions

- Use **`.jsx`** extension for files that contain JSX.
- Every interactive element exposes a **`data-testid`** attribute (see `docs/design-guidelines.json` accessibility section).
- Headings use **Unbounded**, body uses **Outfit**, technical strings (addresses, hashes, ZK commitments) use **JetBrains Mono**.

See the root [`README.md`](../README.md) for project-wide context and the production roadmap.
