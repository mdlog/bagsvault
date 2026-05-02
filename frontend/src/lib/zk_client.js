// High-level helpers wired to the BagsVault backend.
//
// All ZK heavy-lifting (witness generation, proof creation, Merkle path
// reconstruction) lives on the server — the browser only POSTs values
// in / receives proofs back. This keeps Noir / nargo / bb out of the
// frontend bundle. The backend equivalents are documented in
// `backend/app/services/zk_proof_service.py` (Phase 4).
//
// Exports:
//   deriveCommitment(nullifier, secret, amount)            → hex string
//   generateWithdrawProof(args)                            → { proof, public_inputs }
//   relayWithdrawal(payload)                               → { signature, status }
//   buildDepositTx(args)                                   → { tx_base64, ... }
//   registerDeposit(args)                                  → Commitment record
//   getAnonymityState()                                    → { count, current_root, ... }
//   getMerklePath(leafIndex)                               → { siblings, is_left, depth }
//   randomFieldHex()                                       → 64-char hex string
//   buildNote({ token, amount, nullifier, secret })        → "bagsvault-v1-..."
//   parseNote(noteString)                                  → { token, amount, nullifier, secret } | null

import { apiGet, apiPost } from "@/lib/api";

const NOTE_PREFIX = "bagsvault-v1-";

// 32 random bytes encoded as lowercase hex. Uses the WebCrypto RNG —
// every modern browser exposes it, including Phantom's in-app browser.
export function randomFieldHex() {
  const buf = new Uint8Array(32);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(buf);
  } else {
    // Fallback for tests / SSR. Not cryptographically secure — but the
    // server reroutes anything from this path through the real builder.
    for (let i = 0; i < buf.length; i += 1) {
      buf[i] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ----------------------------------------------------------------------
// Note serialisation
// ----------------------------------------------------------------------
export function buildNote({ token, amount, nullifier, secret }) {
  const cleanToken = String(token || "SOL").toLowerCase();
  return `${NOTE_PREFIX}${cleanToken}-${amount}-${nullifier}-${secret}`;
}

// Parse a saved note. Returns `null` for anything that doesn't match the
// `bagsvault-v1-<token>-<amount>-<nullifier>-<secret>` shape so callers
// can `if (!parsed) toast.error(...)`.
export function parseNote(raw) {
  if (typeof raw !== "string") return null;
  const stripped = raw.trim();
  if (!stripped.startsWith(NOTE_PREFIX)) return null;
  const body = stripped.slice(NOTE_PREFIX.length);
  const parts = body.split("-");
  if (parts.length < 4) return null;
  // Last two parts are nullifier + secret (each 64-char hex). Earlier
  // parts join back to a single token name (handles "usd-coin" etc).
  const secret = parts.pop();
  const nullifier = parts.pop();
  const amount = parts.pop();
  const token = parts.join("-").toUpperCase();
  if (!/^[0-9a-fA-F]+$/.test(nullifier) || !/^[0-9a-fA-F]+$/.test(secret)) {
    return null;
  }
  return { token, amount, nullifier, secret };
}

// ----------------------------------------------------------------------
// Backend wrappers
// ----------------------------------------------------------------------
export async function deriveCommitment(nullifier, secret, amount) {
  // Server endpoint mirrors the Noir circuit's commitment hash. Returns
  // `{ commitment: <hex>, ... }`. Throws via the api.js error wrapper
  // when the backend is unreachable or returns a 4xx/5xx.
  return apiPost("/api/proofs/commitment", {
    nullifier,
    secret,
    amount,
  });
}

export async function generateWithdrawProof(args) {
  const {
    nullifier,
    secret,
    amount,
    leafIndex,
    merklePath,
    isLeft,
    recipient,
    relayer,
  } = args;
  return apiPost("/api/proofs/withdraw", {
    nullifier,
    secret,
    amount,
    leaf_index: leafIndex,
    merkle_path: merklePath,
    is_left: isLeft,
    recipient,
    relayer,
  });
}

export async function relayWithdrawal(payload) {
  return apiPost("/api/withdrawals/relay", payload);
}

export async function buildDepositTx({ commitment, amount, token, depositorPubkey }) {
  return apiPost("/api/deposits/build", {
    commitment,
    amount,
    token,
    depositor_pubkey: depositorPubkey,
  });
}

export async function registerDeposit({
  commitment,
  amount,
  token,
  txSignature,
  creatorWallet,
}) {
  return apiPost("/api/deposits", {
    commitment,
    amount,
    token,
    tx_signature: txSignature,
    creator_wallet: creatorWallet,
  });
}

export async function getAnonymityState() {
  // Backend exposes both `/anonymity-set` (legacy) and `/anonymity/state`
  // — we use the latter so the namespace matches the frontend's mental
  // model.
  return apiGet("/api/anonymity/state");
}

export async function getMerklePath(leafIndex) {
  return apiGet(`/api/anonymity/merkle-path?leaf_index=${encodeURIComponent(leafIndex)}`);
}

// ----------------------------------------------------------------------
// Dashboard fetchers (read-only pool stats — never user-specific, never
// leak per-wallet history because the privacy contract forbids it).
// ----------------------------------------------------------------------
export async function getRecentDeposits(limit = 10) {
  return apiGet(`/api/deposits/recent?limit=${limit}`);
}

export async function getRecentWithdrawals(limit = 10) {
  return apiGet(`/api/withdrawals/recent?limit=${limit}`);
}

export async function getRelayers() {
  return apiGet("/api/relayers");
}

export async function getComplianceStats() {
  return apiGet("/api/compliance/stats");
}

export async function getHealth() {
  return apiGet("/api/health");
}

export async function getMerkleRoots() {
  return apiGet("/api/merkle/root");
}
