# BagsVault — Product Requirements Document

## Original Problem Statement
"buatkan saya frontend ui ux yang profesional sesuai degan desain arsitektur yang saya lampirkan" — Professional UI/UX frontend for the BagsVault architecture (ZK privacy protocol for Bags.fm creators on Solana).

## User Choices
- Scope: Frontend UI only (mocked client-side state, no real Web3 wiring)
- Pages: Landing + Deposit + Withdraw + Relayer status + Compliance + Architecture
- Theme: Solana-inspired (purple #9945FF / green #14F195 on deep black)
- Target audience: Bags.fm creators
- Language: English

## Architecture (what was built)
React 19 + Tailwind + shadcn/ui + react-router-dom + sonner. All state mocked via `WalletContext` (localStorage-persisted). Backend `server.py` untouched.

### Pages / Routes
- `/` — Landing: hero, 4-col stats, bento features, public-vs-private comparison, 5-step flow, CTA
- `/deposit` — 4-step pipeline (Range Risk → commitment → Merkle broadcast → anonymity set), note dialog with copy/download
- `/withdraw` — Note parsing, recipient input, relayer selection, Groth16 proof progress UI, signature result
- `/relayers` — Live stats, searchable + sortable relayer table (7 operators), recent anonymized withdrawals feed
- `/compliance` — Range Risk scanner with 3 demo wallets (clean / blocked / review) + 8-check detection matrix
- `/architecture` — 4-pillar diagram, Deposit/Withdraw phase toggle, Noir circuit spec + code block, tech stack grid

### Design System
- Fonts: `Unbounded` (display), `Outfit` (body), `JetBrains Mono` (technical)
- Glassmorphic sticky nav, grid backgrounds, radial glow, solana gradient text, mesh gradients, pulse-glow animations
- Every interactive element has `data-testid` attributes

## What's Implemented (2025-12)
- Layout with mock wallet connect (Phantom/Solflare/Backpack) + persistence
- All 6 pages fully interactive with simulated backend timing
- Full client-side flows: deposit pipeline, ZK proof animation, compliance scanning, architecture phase toggle
- 22/22 frontend test assertions passing (iteration_1)

## Prioritized Backlog
### P0
- Real Solana wallet adapter (Phantom / Solflare via @solana/wallet-adapter)
- Real BagsVault program CPI (Anchor IDL integration)
- Real Noir + Groth16 proof generation in browser (WebAssembly)

### P1
- Integrate Bags API endpoints (/trade/swap, /token-launch/claim-txs/v3)
- Real Range Risk API integration (API key needed)
- Live relayer network feed via WebSocket
- Multi-language (add Indonesian after English)

### P2
- 404/NotFound route
- ARIA role polish (menu, aria-pressed on tabs)
- Dark/light theme toggle (currently dark-only)
- Share cards / OpenGraph metadata

## Next Tasks
1. Validate design with user, collect screenshots feedback
2. Prioritize Solana wallet adapter integration when user is ready to go beyond mockup
3. Acquire Range Risk API credentials for compliance flow
