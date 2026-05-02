// Deposit page — real backend-wired flow.
//
// The Phase 5 wallet adapter is not in this branch yet, so this page
// uses a "depositor pubkey" text input as the proxy. The user signs the
// generated unsigned tx out-of-band (via `solana program send-tx`,
// Phantom's deeplink, etc.) and pastes the resulting signature back
// here so we can record the commitment via POST /api/deposits.

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
  KeyRound,
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
  const { wallet } = useWallet();
  const [token, setToken] = useState("SOL");
  const [amount, setAmount] = useState(1);
  const [mode, setMode] = useState("standard");

  const [step, setStep] = useState("idle"); // idle | commitment | building | awaiting-sig | registering | done
  const [depositorPubkey, setDepositorPubkey] = useState("");
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [unsignedTx, setUnsignedTx] = useState(null); // { tx_base64, blockhash, ... }
  const [pastedSignature, setPastedSignature] = useState("");

  // Pre-fill depositor input from the (mock) wallet context the moment
  // the user connects, so the upgrade path to a real wallet adapter is
  // a one-line change in WalletContext.
  const effectiveDepositor = depositorPubkey || wallet?.address || "";

  const canSubmit = step === "idle" && effectiveDepositor.length >= 32;

  const reset = () => {
    setStep("idle");
    setNote("");
    setUnsignedTx(null);
    setPastedSignature("");
  };

  const runDeposit = async () => {
    if (!effectiveDepositor || effectiveDepositor.length < 32) {
      toast.error("Enter a valid Solana depositor pubkey first.");
      return;
    }

    try {
      // 1. Generate nullifier + secret + commitment.
      setStep("commitment");
      const nullifier = randomFieldHex();
      const secret = randomFieldHex();
      const baseUnits = toBaseUnits(token, amount);
      const commitmentResp = await deriveCommitment(nullifier, secret, baseUnits);
      const commitment = commitmentResp?.commitment || commitmentResp; // tolerant
      if (!commitment || typeof commitment !== "string") {
        throw new Error("Backend returned an empty commitment.");
      }

      // 2. Build the unsigned tx.
      setStep("building");
      const built = await buildDepositTx({
        commitment,
        amount: baseUnits,
        token,
        depositorPubkey: effectiveDepositor,
      });
      setUnsignedTx(built);

      // 3. Hand the user the note + the unsigned tx and wait for the
      //    signed signature to come back.
      const newNote = buildNote({ token, amount, nullifier, secret });
      setNote(newNote);
      setNoteOpen(true);
      setStep("awaiting-sig");
      toast.success("Commitment generated", {
        description: "Save the note + sign the unsigned tx.",
      });
    } catch (err) {
      toast.error(err?.message || "Deposit failed.");
      setStep("idle");
    }
  };

  const submitSignature = async () => {
    if (!pastedSignature || pastedSignature.length < 32) {
      toast.error("Paste the broadcasted tx signature first.");
      return;
    }
    if (!unsignedTx || !note) {
      toast.error("Build a deposit transaction first.");
      return;
    }
    try {
      setStep("registering");
      const baseUnits = toBaseUnits(token, amount);
      // We can't recover the commitment from the note (it only carries
      // nullifier + secret). The build response echoes it back, so we
      // pull it from `unsignedTx` here.
      const commitment = unsignedTx.commitment;
      if (!commitment) throw new Error("Internal error: missing commitment.");
      await registerDeposit({
        commitment,
        amount: baseUnits,
        token,
        txSignature: pastedSignature.trim(),
        creatorWallet: null,
      });
      setStep("done");
      toast.success("Deposit registered", {
        description: `${amount} ${token} added to the privacy pool.`,
      });
    } catch (err) {
      toast.error(err?.message || "Registering deposit failed.");
      setStep("awaiting-sig");
    }
  };

  const stepIndex = useMemo(
    () => ["idle", "commitment", "building", "awaiting-sig", "registering", "done"].indexOf(step),
    [step]
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

      {/* Wallet warning — shown until Phase 5 wallet adapter ships. */}
      <div className="mt-6 border border-amber-500/30 bg-amber-500/[0.04] rounded-md p-3.5 flex gap-3 items-start">
        <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-amber-200 leading-relaxed">
          <span className="font-medium">No wallet adapter yet.</span> Paste your
          depositor pubkey below — the page will return an unsigned base64
          transaction that you sign + broadcast manually (e.g. via{" "}
          <code className="font-mono text-[11px] text-amber-100">solana program send-tx</code>),
          then return here to register the resulting signature.
        </div>
      </div>

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
            {/* Depositor pubkey */}
            <div>
              <label className="text-xs text-zinc-400 mb-2 block">Depositor pubkey</label>
              <input
                data-testid="depositor-input"
                value={depositorPubkey}
                onChange={(e) => setDepositorPubkey(e.target.value)}
                placeholder={wallet?.address || "Solana base58 pubkey of the signer wallet"}
                className="w-full h-12 bg-[#07080a] border border-white/10 focus:border-[#14F195]/50 focus:outline-none rounded-md px-3.5 font-mono text-xs text-white placeholder:text-zinc-700"
              />
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
                disabled={!canSubmit}
                className="w-full h-11 bg-white text-black rounded-md font-medium text-sm hover:bg-zinc-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {step === "idle" ? (
                  <>Generate commitment + tx <ArrowRight className="w-4 h-4" /></>
                ) : (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Working…</>
                )}
              </button>
            )}
          </div>

          {/* Awaiting signature panel */}
          {(step === "awaiting-sig" || step === "registering") && unsignedTx && (
            <div className="border border-[#14F195]/30 bg-[#14F195]/[0.04] p-5 rounded-md space-y-4">
              <div className="flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-[#14F195]" />
                <p className="text-sm font-medium text-white">Sign &amp; broadcast manually</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-[#14F195] mb-1.5">
                  Unsigned transaction (base64)
                </p>
                <code
                  data-testid="unsigned-tx-base64"
                  className="block font-mono text-[10px] text-white break-all leading-relaxed border border-white/10 bg-[#07080a] rounded-md p-3 max-h-32 overflow-auto"
                >
                  {unsignedTx.tx_base64}
                </code>
                <button
                  data-testid="copy-tx-btn"
                  onClick={() => {
                    navigator.clipboard.writeText(unsignedTx.tx_base64);
                    toast.success("Unsigned tx copied");
                  }}
                  className="mt-2 text-xs text-[#14F195] hover:text-white inline-flex items-center gap-1"
                >
                  <Copy className="w-3 h-3" /> Copy
                </button>
                <p className="text-[11px] text-zinc-400 mt-2 leading-relaxed">
                  Sign with your wallet (Phantom: import as transaction, or run{" "}
                  <code className="font-mono text-[10px] text-zinc-200">
                    solana program send-tx
                  </code>
                  ), then paste the resulting tx signature below.
                </p>
              </div>
              <div>
                <label className="text-xs text-zinc-400 mb-2 block">Tx signature</label>
                <input
                  data-testid="tx-signature-input"
                  value={pastedSignature}
                  onChange={(e) => setPastedSignature(e.target.value)}
                  placeholder="5...base58 signature..."
                  className="w-full h-11 bg-[#07080a] border border-white/10 focus:border-[#14F195]/50 focus:outline-none rounded-md px-3.5 font-mono text-xs text-white placeholder:text-zinc-700"
                />
                <button
                  data-testid="submit-signature-btn"
                  onClick={submitSignature}
                  disabled={step === "registering"}
                  className="mt-3 w-full h-11 bg-[#14F195] text-black rounded-md font-medium text-sm hover:bg-[#14F195]/90 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {step === "registering" ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Registering…</>
                  ) : (
                    <>Register commitment <ArrowRight className="w-4 h-4" /></>
                  )}
                </button>
              </div>
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
              { id: 3, title: "User signs + broadcasts", mono: "wallet · solana RPC", active: stepIndex >= 3, done: stepIndex >= 4 },
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
            <p className="text-zinc-300 font-medium mb-2 text-sm">Why a manual sign step?</p>
            <p>
              Phase 5 wires up the Solana wallet adapter so the entire flow
              happens in-browser. Until then we keep the protocol honest by
              never asking the backend to hold your signing key.
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

