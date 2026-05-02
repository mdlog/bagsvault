# BagsVault

> Privacy-preserving vault protocol for Bags.fm creators on Solana — a ZK mixer UI with Range Risk compliance, relayer network, and Groth16 proof simulation.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tailwind](https://img.shields.io/badge/Tailwind-3.4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Solana](https://img.shields.io/badge/Solana-9945FF?logo=solana&logoColor=white)](https://solana.com)

> **Status:** UI/UX prototype — all on-chain interactions are mocked client-side. See [Roadmap](#roadmap) for production wiring.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Pages & Routes](#pages--routes)
- [Design System](#design-system)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

BagsVault is a privacy layer for creators on [Bags.fm](https://bags.fm) who launch tokens on Solana. It combines a non-custodial ZK mixer with on-chain compliance scoring (Range Risk API) and a decentralized relayer network — letting creators deposit and withdraw without linking their public identity to their treasury wallet.

This repository contains the **frontend dApp UI** (React + Tailwind) and a **FastAPI backend scaffold** (MongoDB-backed). It is designed as a high-fidelity prototype that mirrors the production architecture.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Tailwind CSS 3.4, shadcn/ui, react-router-dom v7, sonner |
| Build tool | CRACO (Create React App Configuration Override) |
| Backend | FastAPI 0.110, Motor (async MongoDB driver), Pydantic v2 |
| Database | MongoDB |
| Tooling | Yarn, ESLint, Prettier, Black, isort, mypy, flake8 |

## Quick Start

### Prerequisites

- **Node.js** ≥ 18 and **Yarn** ≥ 1.22
- **Python** ≥ 3.11
- **MongoDB** ≥ 6.0 (local or via Docker)

### Setup

```bash
# Clone
git clone <repo-url> bagsvault
cd bagsvault

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit values

# Frontend
cd ../frontend
yarn install
cp .env.example .env       # then edit values
```

### Run

```bash
# Terminal 1 — backend (http://localhost:8000)
cd backend && uvicorn app.main:app --reload

# Terminal 2 — frontend (http://localhost:3000)
cd frontend && yarn start
```

Or, with Docker:

```bash
docker compose up
```

Or, with Make:

```bash
make dev      # start backend + frontend together
make test     # run all tests
make lint     # run linters
```

## Project Structure

```
bagsvault/
├── backend/                    # FastAPI service
│   ├── app/
│   │   ├── main.py             # FastAPI app + middleware
│   │   ├── config.py           # Pydantic settings
│   │   ├── database.py         # Mongo client
│   │   ├── models/             # Pydantic models
│   │   └── routers/            # API routers
│   ├── requirements.txt
│   ├── pyproject.toml          # tooling config (black, isort, mypy)
│   └── .env.example
├── frontend/                   # React dApp
│   ├── src/
│   │   ├── pages/              # 6 routed pages (Landing, Deposit, …)
│   │   ├── components/         # Layout + shadcn/ui primitives
│   │   ├── context/            # WalletContext (mocked)
│   │   ├── hooks/
│   │   └── lib/
│   ├── public/
│   ├── plugins/                # Custom CRACO plugins (health-check)
│   └── package.json
├── docs/                       # Design guidelines, PRD
├── tests/                      # Cross-stack integration tests
├── docker-compose.yml
├── Makefile
└── README.md
```

## Pages & Routes

| Route | Description |
|---|---|
| `/` | Landing — hero, stats, bento features, public-vs-private comparison |
| `/deposit` | 4-step pipeline: Range Risk → commitment → Merkle broadcast → anonymity set |
| `/withdraw` | Note parsing, recipient input, relayer selection, Groth16 proof animation |
| `/relayers` | Searchable + sortable table of 7 relayer operators with live stats |
| `/compliance` | Range Risk scanner with 3 demo wallets and 8-check detection matrix |
| `/architecture` | 4-pillar diagram with Deposit/Withdraw phase toggle and Noir circuit spec |

## Design System

- **Colors:** Solana purple `#9945FF` + green `#14F195` on deep black `#050505`
- **Typography:** [Unbounded](https://fonts.google.com/specimen/Unbounded) (display), [Outfit](https://fonts.google.com/specimen/Outfit) (body), [JetBrains Mono](https://fonts.google.com/specimen/JetBrains+Mono) (technical)
- **Surfaces:** Glassmorphic sticky nav, mesh gradients, pulse-glow animations
- **Accessibility:** Every interactive element exposes a `data-testid` attribute

Full spec: [`docs/design-guidelines.json`](./docs/design-guidelines.json).

## Development

### Code style

```bash
# Backend
cd backend
black .          # format
isort .          # sort imports
flake8 .         # lint
mypy .           # type check

# Frontend
cd frontend
yarn lint        # eslint
yarn format      # prettier
```

### Tests

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && yarn test
```

### Environment variables

| Variable | Service | Description |
|---|---|---|
| `MONGO_URL` | backend | MongoDB connection string |
| `DB_NAME` | backend | Database name |
| `CORS_ORIGINS` | backend | Comma-separated allowed origins |
| `REACT_APP_BACKEND_URL` | frontend | Base URL of backend API |

See `backend/.env.example` and `frontend/.env.example` for full lists.

## Roadmap

### P0 — Production wiring
- [ ] Real Solana wallet adapter (`@solana/wallet-adapter`: Phantom, Solflare, Backpack)
- [ ] Anchor IDL integration for BagsVault on-chain program (CPI)
- [ ] In-browser Noir + Groth16 proof generation via WebAssembly

### P1 — External integrations
- [ ] Bags API (`/trade/swap`, `/token-launch/claim-txs/v3`)
- [ ] Range Risk API (live wallet scoring)
- [ ] WebSocket relayer feed
- [ ] i18n (Bahasa Indonesia)

### P2 — Polish
- [ ] 404 / NotFound route
- [ ] ARIA polish (menu role, `aria-pressed` on tabs)
- [ ] OpenGraph + share cards
- [ ] Theme toggle (light variant)

Detailed product context: [`docs/PRD.md`](./docs/PRD.md).

## License

[MIT](./LICENSE) © BagsVault contributors.
