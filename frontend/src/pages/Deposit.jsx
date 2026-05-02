// Deposit page — real backend-wired flow with browser wallet signing.
//
// Connected wallet (Phantom / Solflare / wallet-standard auto-discovery):
//   1. Generate nullifier + secret + commitment via /api/proofs/commitment
//   2. Build the unsigned deposit tx via /api/deposits/build
//   3. Wallet signs + broadcasts via signAndSendTx (refreshes blockhash)
//   4. Register the resulting signature via /api/deposits
//   5. Show the private note — single source of truth for withdrawal
//
// No connected wallet → show "Connect wallet" CTA. The manual paste-tx
// flow has been retired; signing happens entirely in the browser.

import { useMemo, useState } from "react";
import { useWallet } from "@/context/WalletContext";
import { toast } from "sonner";
import {
  CheckCircle2,
  Copy,
  Download,
  Loader2,
  AlertTriangle,
  Lock,
  ArrowRight,
  Wallet,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  buildDepositTx,
  buildNote,
  deriveCommitment,
  randomFieldHex,
  registerDeposit,
} from "@/lib/zk_client";

const TOKENS = [
  { symbol: "SOL", name: "Solana", icon: "◎" },
  { symbol: "BAGS", name: "Bags", icon: "B" },
  { symbol: "USDC", name: "USD Coin", icon: "$" },
  { symbol: "WIF", name: "dogwifhat", icon: "W" },
];

const FIXED_AMOUNTS = {
  SOL: [0.1, 1, 10, 100],
  BAGS: [100, 1000, 10000, 100000],
  USDC: [10, 100, 1000, 10000],
  WIF: [50, 500, 5000, 50000],
};

const LAMPORTS_PER_SOL = 1_000_000_000;

function toBaseUnits(token, amount) {
  // SPL decimals are token-specific; until the registry endpoint lands
  // we hardcode common cases. Worst case the backend will reject a
  // mismatched amount, which is the right failure mode.
  if (token === "SOL") return Math.round(amount * LAMPORTS_PER_SOL);
  if (token === "USDC") return Math.round(amount * 1_000_000); // 6 decimals
  // BAGS / WIF / unknown: assume 9 decimals to match SOL.
  return Math.round(amount * LAMPORTS_PER_SOL);
}

export default function Deposit() {
  const { wallet, connect, signAndSendTx } = useWallet();
  const [token, setToken] = useState("SOL");
  const [amount, setAmount] = useState(1);
  const [mode, setMode] = useState("standard");

  // Pipeline state. With the wallet adapter wired, "awaiting-sig" is no
  // longer a user-blocking step — it's a transient state while the
  // wallet popup is open.
  const [step, setStep] = useState("idle"); // idle | commitment | building | signing | registering | done
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [txSignature, setTxSignature] = useState("");

  const isConnected = Boolean(wallet?.address);
  const canSubmit = step === "idle" && isConnected;

  const reset = () => {
    setStep("idle");
    setNote("");
    setTxSignature("");
  };

  const runDeposit = async () => {
    if (!isConnected) {
      connect();
      toast.message("Connect a wallet to continue.");
      return;
    }

    let commitment = null;
    let nullifier = null;
    let secret = null;
    let baseUnits = null;

    try {
      // 1. Generate nullifier + secret + commitment.
      setStep("commitment");
      nullifier = randomFieldHex();
      secret = randomFieldHex();
      baseUnits = toBaseUnits(token, amount);
      const commitmentResp = await deriveCommitment(nullifier, secret, baseUnits);
      commitment =
        commitmentResp?.commitment_hex ||
        commitmentResp?.commitment ||
        commitmentResp;
      if (!commitment || typeof commitment !== "string") {
        throw new Error("Backend returned an empty commitment.");
      }

      // 2. Build the unsigned tx.
      setStep("building");
      const built = await buildDepositTx({
        commitment,
        amount: baseUnits,
        token,
        depositorPubkey: wallet.address,
      });
      const unsignedTx = built?.tx_base64 || built?.unsigned_tx;
      if (!unsignedTx) {
        throw new Error("Backend did not return an unsigned transaction.");
      }

      // 3. Show the note BEFORE signing. If the user closes the wallet
      //    popup, they still need to know the secret in case the tx
      //    actually landed (rare but possible with rebroadcasts).
      const newNote = buildNote({ token, amount, nullifier, secret });
      setNote(newNote);
      setNoteOpen(true);

      // 4. Sign + broadcast via the wallet adapter.
      setStep("signing");
      const signature = await signAndSendTx(unsignedTx);
      setTxSignature(signature);

      // 5. Register the commitment with the backend.
      setStep("registering");
      await registerDeposit({
        commitment,
        amount: baseUnits,
        token,
        txSignature: signature,
        creatorWallet: null,
      });
      setStep("done");
      toast.success("Deposit confirmed", {
        description: `${amount} ${token} added to the privacy pool.`,
      });
    } catch (err) {
      // User-rejected wallet popup is the most common path here.
      const message = err?.message || "Deposit failed.";
      const userRejected =
        /rejected|cancel|denied/i.test(message) ||
        err?.code === 4001 ||
        err?.name === "WalletSendTransactionError";
      if (userRejected) {
        toast.error("Wallet signature was rejected.");
      } else {
        toast.error(message);
      }
      // If we already broadcast but the register call failed, surface
      // the signature so the user can manually retry the registration.
      setStep(txSignature ? "registering" : "idle");
    }
  };

  const retryRegister = async () => {
    if (!txSignature || !note) return;
    try {
      setStep("registering");
      const baseUnits = toBaseUnits(token, amount);
      // The commitment is encoded in the note as the second-to-last
      // field; recover it from the same nullifier+secret+amount inputs.
      const parts = note.split("-");
      const recoveredNullifier = parts[parts.length - 2];
      const recoveredSecret = parts[parts.length - 1];
      const commitmentResp = await deriveCommitment(
        recoveredNullifier,
        recoveredSecret,
        baseUnits,
      );
      const commitment =
        commitmentResp?.commitment_hex ||
        commitmentResp?.commitment ||
        commitmentResp;
      await registerDeposit({
        commitment,
        amount: baseUnits,
        token,
        txSignature,
        creatorWallet: null,
      });
      setStep("done");
      toast.success("Deposit registered.");
    } catch (err) {
      toast.error(err?.message || "Registering deposit failed.");
    }
  };

  const stepIndex = useMemo(
    () =>
      ["idle", "commitment", "building", "signing", "registering", "done"].indexOf(
        step,
      ),
    [step],
  );

  return (
    <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-20">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-xs font-medium text-[#14F195] mb-2">Protocol · Deposit</p>
          <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">
            Deposit into the pool
          </h1>
          <p className="text-zinc-400 mt-2 max-w-xl text-sm leading-relaxed">
            Add liquidity to the BagsVault anonymity set. Your commitment will join the others — indistinguishable on-chain.
          </p>
        </div>
        <div className="flex items-center gap-2 border border-white/10 px-3 h-9 rounded-md text-xs text-zinc-400">
          <Lock className="w-3.5 h-3.5 text-[#14F195]" /> client-side commitment
        </div>
      </div>

      {/* Wallet status banner. */}
      {isConnected ? (
        <div className="mt-6 border border-[#14F195]/25 bg-[#14F195]/[0.04] rounded-md p-3.5 flex gap-3 items-center">
          <Wallet className="w-4 h-4 text-[#14F195] flex-shrink-0" />
          <div className="text-xs text-zinc-300 leading-relaxed flex-1">
            Signed in as{" "}
            <code className="font-mono text-[11px] text-white">
              {wallet.address.slice(0, 6)}…{wallet.address.slice(-6)}
            </code>{" "}
            via {wallet.provider}. Deposits sign + broadcast in your wallet —
            BagsVault never holds your key.
          </div>
        </div>
      ) : (
        <div className="mt-6 border border-amber-500/30 bg-amber-500/[0.04] rounded-md p-3.5 flex gap-3 items-start">
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200 leading-relaxed">
            <span className="font-medium">Wallet not connected.</span> Click{" "}
            <button
              onClick={() => connect()}
              className="underline text-amber-100 hover:text-white"
            >
              Connect wallet
            </button>{" "}
            in the top-right (or hit the deposit button below) to sign
            transactions in-browser via Phantom / Solflare / wallet-standard.
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-5 gap-5 mt-6">
        {/* LEFT: Form */}
        <div className="lg:col-span-3 space-y-4">
          {/* Mode tabs */}
          <div className="grid grid-cols-2 border border-white/5 rounded-md overflow-hidden bg-[#0a0b0d]">
            <button
              data-testid="deposit-mode-standard"
              onClick={() => setMode("standard")}
              className={`p-4 text-left border-r border-white/5 transition-colors ${
                mode === "standard" ? "bg-white/[0.05]" : "hover:bg-white/[0.02]"
              }`}
            >
              <p className={`text-xs font-medium ${mode === "standard" ? "text-[#14F195]" : "text-zinc-500"}`}>
                Standard
              </p>
              <p className="text-sm font-semibold mt-1">Deposit tokens</p>
              <p className="text-xs text-zinc-500 mt-0.5">Add SOL / SPL to the pool</p>
            </button>
            <button
              data-testid="deposit-mode-creator"
              onClick={() => setMode("creator-fee")}
              className={`p-4 text-left transition-colors ${
                mode === "creator-fee" ? "bg-white/[0.05]" : "hover:bg-white/[0.02]"
              }`}
            >
              <p className={`text-xs font-medium ${mode === "creator-fee" ? "text-[#14F195]" : "text-zinc-500"}`}>
                Creator fees
              </p>
              <p className="text-sm font-semibold mt-1">Claim direct to vault</p>
              <p className="text-xs text-zinc-500 mt-0.5">Bags API · /claim-txs/v3</p>
            </button>
          </div>

          {/* Card */}
          <div className="border border-white/5 bg-[#0a0b0d] p-6 lg:p-7 space-y-6 rounded-md">
            {/* Connected depositor — read-only display when wallet is on. */}
            <div>
              <label className="text-xs text-zinc-400 mb-2 block">Depositor</label>
              <div
                data-testid="depositor-display"
                className={`w-full h-12 bg-[#07080a] border rounded-md px-3.5 flex items-center justify-between ${
                  isConnected ? "border-white/10" : "border-amber-500/30"
                }`}
              >
                {isConnected ? (
                  <>
                    <span className="font-mono text-xs text-white">
                      {wallet.address.slice(0, 8)}…{wallet.address.slice(-8)}
                    </span>
                    <span className="text-[11px] text-zinc-500">
                      {wallet.provider}
                    </span>
                  </>
                ) : (
                  <span className="text-xs text-amber-200">
                    Connect a wallet to continue.
                  </span>
                )}
              </div>
            </div>

            {/* Token */}
            <div>
              <label className="text-xs text-zinc-400 mb-2 block">Token</label>
              <Select value={token} onValueChange={(v) => { setToken(v); setAmount(FIXED_AMOUNTS[v][0]); }}>
                <SelectTrigger
                  data-testid="token-select-trigger"
                  className="w-full h-12 bg-[#07080a] border-white/10 rounded-md text-white hover:border-white/20"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#0c0d10] border-white/10 text-white rounded-md">
                  {TOKENS.map((t) => (
                    <SelectItem
                      key={t.symbol}
                      value={t.symbol}
                      data-testid={`token-option-${t.symbol.toLowerCase()}`}
                      className="focus:bg-white/5 rounded-sm py-2.5"
                    >
                      <span className="flex items-center gap-3">
                        <span className="w-7 h-7 bg-[#14F195]/15 border border-[#14F195]/40 text-[#14F195] font-semibold flex items-center justify-center text-sm rounded-md">
                          {t.icon}
                        </span>
                        <span>
                          <span className="font-medium text-sm">{t.symbol}</span>
                          <span className="text-zinc-500 text-xs ml-2">{t.name}</span>
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Amount */}
            <div>
              <label className="text-xs text-zinc-400 mb-2 block">Fixed denomination</label>
              <div className="grid grid-cols-4 gap-2">
                {FIXED_AMOUNTS[token].map((a) => (
                  <button
                    key={a}
                    data-testid={`amount-${a}`}
                    onClick={() => setAmount(a)}
                    className={`h-14 rounded-md border transition-colors ${
                      amount === a
                        ? "border-[#14F195] bg-[#14F195]/[0.06] text-white"
                        : "border-white/10 hover:border-white/25 text-zinc-300"
                    }`}
                  >
                    <span className="text-base font-semibold block tracking-tight">{a.toLocaleString()}</span>
                    <span className="text-[10px] text-zinc-500">{token}</span>
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-zinc-500 mt-2 flex items-start gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                Fixed denominations maximize anonymity-set uniformity.
              </p>
            </div>

            {/* Submit */}
            {step === "done" ? (
              <button
                data-testid="deposit-restart-btn"
                onClick={reset}
                className="w-full h-11 border border-white/15 rounded-md hover:bg-white/[0.04] font-medium text-sm"
              >
                Make another deposit
              </button>
            ) : (
              <button
                data-testid="deposit-submit-btn"
                onClick={runDeposit}
                disabled={step !== "idle"}
                className="w-full h-11 bg-white text-black rounded-md font-medium text-sm hover:bg-zinc-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {step === "idle" ? (
                  isConnected ? (
                    <>Deposit {amount} {token} <ArrowRight className="w-4 h-4" /></>
                  ) : (
                    <><Wallet className="w-4 h-4" /> Connect wallet to deposit</>
                  )
                ) : step === "signing" ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Awaiting signature…</>
                ) : step === "registering" ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Registering…</>
                ) : (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Working…</>
                )}
              </button>
            )}
          </div>

          {/* Tx confirmation / retry panel — visible once we have a sig. */}
          {txSignature && (
            <div className="border border-[#14F195]/30 bg-[#14F195]/[0.04] p-5 rounded-md space-y-3">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#14F195]" />
                <p className="text-sm font-medium text-white">
                  {step === "done"
                    ? "Deposit confirmed on chain"
                    : "Transaction broadcasted"}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-[#14F195] mb-1.5">
                  Tx signature
                </p>
                <code
                  data-testid="tx-signature"
                  className="block font-mono text-[10px] text-white break-all leading-relaxed border border-white/10 bg-[#07080a] rounded-md p-3"
                >
                  {txSignature}
                </code>
                <div className="flex gap-3 mt-2">
                  <button
                    data-testid="copy-tx-btn"
                    onClick={() => {
                      navigator.clipboard.writeText(txSignature);
                      toast.success("Signature copied");
                    }}
                    className="text-xs text-[#14F195] hover:text-white inline-flex items-center gap-1"
                  >
                    <Copy className="w-3 h-3" /> Copy
                  </button>
                  <a
                    href={`https://explorer.solana.com/tx/${txSignature}?cluster=devnet`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[#14F195] hover:text-white inline-flex items-center gap-1"
                  >
                    Open on Solana Explorer ↗
                  </a>
                </div>
              </div>
              {step === "registering" && (
                <p className="text-[11px] text-zinc-400 flex items-center gap-1.5">
                  <Loader2 className="w-3 h-3 animate-spin" /> Registering with
                  the indexer…
                </p>
              )}
              {step !== "done" && step !== "registering" && (
                <button
                  data-testid="retry-register-btn"
                  onClick={retryRegister}
                  className="w-full h-11 bg-[#14F195] text-black rounded-md font-medium text-sm hover:bg-[#14F195]/90 flex items-center justify-center gap-2"
                >
                  Retry register commitment <ArrowRight className="w-4 h-4" />
                </button>
              )}
            </div>
          )}
        </div>

        {/* RIGHT: Pipeline */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
            <p className="text-xs font-medium text-zinc-300 mb-4">Transaction pipeline</p>
            {[
              { id: 1, title: "Generate commitment", mono: "POST /api/proofs/commitment", active: stepIndex >= 1, done: stepIndex >= 2 },
              { id: 2, title: "Build unsigned tx", mono: "POST /api/deposits/build", active: stepIndex >= 2, done: stepIndex >= 3 },
              { id: 3, title: "Wallet signs + broadcasts", mono: `${wallet?.provider || "wallet"} · solana RPC`, active: stepIndex >= 3, done: stepIndex >= 4 },
              { id: 4, title: "Register commitment", mono: "POST /api/deposits", active: stepIndex >= 4, done: stepIndex >= 5 },
            ].map((s, i, arr) => (
              <div key={s.id} className="flex gap-3.5 relative">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-7 h-7 rounded-md border flex items-center justify-center font-mono text-[11px] transition-colors ${
                      s.done
                        ? "border-[#14F195] bg-[#14F195]/10 text-[#14F195]"
                        : s.active
                        ? "border-white/40 text-white"
                        : "border-white/10 text-zinc-600"
                    }`}
                  >
                    {s.done ? <CheckCircle2 className="w-3.5 h-3.5" /> : s.id}
                  </div>
                  {i < arr.length - 1 && (
                    <div className={`w-px flex-1 ${s.done ? "bg-[#14F195]/40" : "bg-white/10"}`} />
                  )}
                </div>
                <div className="pb-5 flex-1">
                  <p className={`text-sm ${s.active ? "text-white" : "text-zinc-500"}`}>{s.title}</p>
                  <p className="text-[11px] font-mono text-zinc-600 mt-0.5">{s.mono}</p>
                  {s.active && !s.done && (
                    <p className="text-[11px] text-[#14F195] mt-1 flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> processing…
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md text-xs text-zinc-400 leading-relaxed">
            <p className="text-zinc-300 font-medium mb-2 text-sm">In-browser signing</p>
            <p>
              Your wallet (Phantom / Solflare / wallet-standard) signs the
              deposit transaction locally; the backend only sees the public
              commitment + the broadcasted signature. The signing key never
              leaves your device.
            </p>
          </div>
        </div>
      </div>

      {/* Note modal */}
      <Dialog open={noteOpen} onOpenChange={setNoteOpen}>
        <DialogContent className="bg-[#0c0d10] border-white/10 text-white max-w-lg rounded-lg">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-[#14F195]" />
              Save your private note
            </DialogTitle>
            <DialogDescription className="text-zinc-500 text-sm">
              This note is the <span className="text-white">only</span> way to
              withdraw later. Save it before you broadcast the tx — losing it
              means losing access forever.
            </DialogDescription>
          </DialogHeader>
          <div className="border border-[#14F195]/30 bg-[#14F195]/[0.04] rounded-md p-3.5">
            <p className="text-[10px] uppercase tracking-wider text-[#14F195] mb-1.5">Private note</p>
            <code
              data-testid="private-note"
              className="font-mono text-[11px] text-white break-all leading-relaxed"
            >
              {note}
            </code>
          </div>
          <div className="flex gap-2">
            <button
              data-testid="copy-note-btn"
              onClick={() => {
                navigator.clipboard.writeText(note);
                toast.success("Note copied to clipboard");
              }}
              className="flex-1 h-10 bg-white text-black rounded-md font-medium text-sm hover:bg-zinc-200 flex items-center justify-center gap-2"
            >
              <Copy className="w-4 h-4" /> Copy note
            </button>
            <button
              data-testid="download-note-btn"
              onClick={() => {
                const blob = new Blob([note], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "bagsvault-note.txt";
                a.click();
                toast.success("Note downloaded");
              }}
              className="h-10 px-4 border border-white/15 rounded-md hover:bg-white/[0.04] flex items-center gap-2 text-sm"
            >
              <Download className="w-4 h-4" /> Save
            </button>
          </div>
          <p className="text-xs text-amber-400 flex gap-2 items-start">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            BagsVault never stores your note. Back it up offline.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}

