import { useState } from "react";
import { useWallet } from "@/context/WalletContext";
import { toast } from "sonner";
import {
  Shield,
  CheckCircle2,
  Copy,
  Download,
  Loader2,
  AlertTriangle,
  Lock,
  ChevronDown,
  ArrowRight,
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

const TOKENS = [
  { symbol: "SOL", name: "Solana", icon: "◎", balance: 12.4, mint: "So111...1112" },
  { symbol: "BAGS", name: "Bags", icon: "B", balance: 12340, mint: "Bags111...2cKv" },
  { symbol: "USDC", name: "USD Coin", icon: "$", balance: 820.55, mint: "EPjF...u6M" },
  { symbol: "WIF", name: "dogwifhat", icon: "W", balance: 2100, mint: "EKpQ...Kv" },
];

const FIXED_AMOUNTS = {
  SOL: [0.1, 1, 10, 100],
  BAGS: [100, 1000, 10000, 100000],
  USDC: [10, 100, 1000, 10000],
  WIF: [50, 500, 5000, 50000],
};

const rand = (chars = "abcdef0123456789", len = 64) =>
  Array.from({ length: len })
    .map(() => chars[Math.floor(Math.random() * chars.length)])
    .join("");

export default function Deposit() {
  const { wallet } = useWallet();
  const [token, setToken] = useState("SOL");
  const [amount, setAmount] = useState(1);
  const [mode, setMode] = useState("standard"); // standard | creator-fee

  const [step, setStep] = useState("idle"); // idle|compliance|commitment|broadcast|done
  const [riskScore, setRiskScore] = useState(null);
  const [riskFlags, setRiskFlags] = useState([]);
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);

  const tokenInfo = TOKENS.find((t) => t.symbol === token);

  const runDeposit = async () => {
    if (!wallet) {
      toast.error("Please connect a wallet first.");
      return;
    }
    // 1. Compliance
    setStep("compliance");
    setRiskScore(null);
    setRiskFlags([]);
    await new Promise((r) => setTimeout(r, 1400));
    const score = Math.floor(Math.random() * 15) + 2; // always low risk for demo
    const flags = [
      { label: "OFAC sanctions", status: "clean" },
      { label: "Known hacker addresses", status: "clean" },
      { label: "Mixer exposure", status: "clean" },
      { label: "Illicit flows", status: "clean" },
    ];
    setRiskScore(score);
    setRiskFlags(flags);
    await new Promise((r) => setTimeout(r, 800));

    // 2. Commitment
    setStep("commitment");
    await new Promise((r) => setTimeout(r, 1800));

    // 3. Broadcast
    setStep("broadcast");
    await new Promise((r) => setTimeout(r, 1800));

    // 4. Done — generate note
    const newNote = `bagsvault-v1-solana-${token.toLowerCase()}-${amount}-${rand()}`;
    setNote(newNote);
    setStep("done");
    setNoteOpen(true);
    toast.success("Deposit confirmed", {
      description: `${amount} ${token} added to the privacy pool.`,
    });
  };

  const stepIndex = ["idle", "compliance", "commitment", "broadcast", "done"].indexOf(step);

  return (
    <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-12 pb-24">
      <div className="absolute inset-x-0 top-0 h-[400px] radial-glow pointer-events-none" />

      {/* Header */}
      <div className="relative flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
            / protocol · deposit
          </p>
          <h1 className="font-display font-bold text-4xl lg:text-5xl tracking-tight">
            Deposit into the pool
          </h1>
          <p className="text-zinc-400 mt-3 max-w-xl text-sm leading-relaxed">
            Add liquidity to the BagsVault anonymity set. Your commitment will join
            47,129 others — indistinguishable on-chain.
          </p>
        </div>
        <div className="flex items-center gap-2 border border-white/10 px-4 h-11 font-mono text-xs text-zinc-500">
          <Lock className="w-3.5 h-3.5 text-[#14F195]" /> end-to-end client-side encryption
        </div>
      </div>

      <div className="relative grid lg:grid-cols-5 gap-6 mt-10">
        {/* LEFT: Form */}
        <div className="lg:col-span-3 space-y-4">
          {/* Mode tabs */}
          <div className="grid grid-cols-2 border border-white/5">
            <button
              data-testid="deposit-mode-standard"
              onClick={() => setMode("standard")}
              className={`p-5 text-left border-r border-white/5 transition-colors ${
                mode === "standard" ? "bg-white/[0.04]" : "hover:bg-white/[0.02]"
              }`}
            >
              <p className={`text-xs font-mono uppercase tracking-[0.2em] ${mode === "standard" ? "text-[#14F195]" : "text-zinc-500"}`}>
                Standard
              </p>
              <p className="font-display text-base mt-1">Deposit tokens</p>
              <p className="text-xs text-zinc-500 mt-1">Add SOL / SPL to the pool</p>
            </button>
            <button
              data-testid="deposit-mode-creator"
              onClick={() => setMode("creator-fee")}
              className={`p-5 text-left transition-colors ${
                mode === "creator-fee" ? "bg-white/[0.04]" : "hover:bg-white/[0.02]"
              }`}
            >
              <p className={`text-xs font-mono uppercase tracking-[0.2em] ${mode === "creator-fee" ? "text-[#14F195]" : "text-zinc-500"}`}>
                Creator fees
              </p>
              <p className="font-display text-base mt-1">Claim direct to vault</p>
              <p className="text-xs text-zinc-500 mt-1">Bags API · /claim-txs/v3</p>
            </button>
          </div>

          {/* Card */}
          <div className="border border-white/5 bg-[#0A0A0A] p-6 lg:p-8 space-y-6">
            {mode === "creator-fee" && (
              <div className="border border-[#9945FF]/30 bg-[#9945FF]/[0.05] p-4 flex gap-3 items-start">
                <Shield className="w-4 h-4 text-[#9945FF] flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs font-medium text-[#9945FF]">Creator fee mode</p>
                  <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                    Unclaimed Bags fees will be routed directly into your vault commitment.
                    Pending: <span className="font-mono text-white">2.47 SOL · 18,420 BAGS</span>
                  </p>
                </div>
              </div>
            )}

            {/* Token select */}
            <div>
              <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-2 block">
                Token
              </label>
              <Select value={token} onValueChange={(v) => { setToken(v); setAmount(FIXED_AMOUNTS[v][0]); }}>
                <SelectTrigger
                  data-testid="token-select-trigger"
                  className="w-full h-14 bg-black border-white/10 rounded-none text-white hover:border-white/20"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#0A0A0A] border-white/10 text-white rounded-none">
                  {TOKENS.map((t) => (
                    <SelectItem
                      key={t.symbol}
                      value={t.symbol}
                      data-testid={`token-option-${t.symbol.toLowerCase()}`}
                      className="focus:bg-white/5 rounded-none py-3"
                    >
                      <span className="flex items-center gap-3">
                        <span className="w-7 h-7 bg-gradient-to-br from-[#9945FF] to-[#14F195] text-black font-bold flex items-center justify-center text-sm">
                          {t.icon}
                        </span>
                        <span>
                          <span className="font-medium">{t.symbol}</span>
                          <span className="text-zinc-500 text-xs ml-2">{t.name}</span>
                        </span>
                        <span className="ml-auto font-mono text-xs text-zinc-500">
                          {t.balance.toLocaleString()}
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Amount */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">
                  Fixed denomination
                </label>
                <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">
                  balance · <span className="text-zinc-400 font-mono">{tokenInfo.balance.toLocaleString()} {token}</span>
                </span>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {FIXED_AMOUNTS[token].map((a) => (
                  <button
                    key={a}
                    data-testid={`amount-${a}`}
                    onClick={() => setAmount(a)}
                    className={`h-16 border transition-all ${
                      amount === a
                        ? "border-[#14F195] bg-[#14F195]/5 text-white"
                        : "border-white/10 hover:border-white/30 text-zinc-400"
                    }`}
                  >
                    <span className="font-display font-bold text-lg block">{a.toLocaleString()}</span>
                    <span className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">{token}</span>
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-zinc-500 mt-3 font-mono flex items-start gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                fixed denominations maximize anonymity set uniformity
              </p>
            </div>

            {/* Summary */}
            <div className="border-t border-white/5 pt-6 space-y-3 text-sm">
              {[
                ["Depositing", `${amount.toLocaleString()} ${token}`],
                ["Protocol fee", `0 ${token}`],
                ["Anonymity set after deposit", "47,130"],
                ["Merkle root", "0x7a3f…c9e1", "font-mono"],
              ].map(([k, v, cls]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-zinc-500">{k}</span>
                  <span className={`text-white ${cls || ""}`}>{v}</span>
                </div>
              ))}
            </div>

            <button
              data-testid="deposit-submit-btn"
              onClick={runDeposit}
              disabled={step !== "idle" && step !== "done"}
              className="w-full h-14 bg-white text-black font-semibold hover:bg-zinc-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {step !== "idle" && step !== "done" ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Processing…</>
              ) : (
                <>Deposit {amount.toLocaleString()} {token} <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </div>
        </div>

        {/* RIGHT: Status timeline */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-white/5 bg-[#0A0A0A] p-6">
            <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-5">
              Transaction Pipeline
            </p>
            {[
              {
                id: 1,
                title: "Risk Pre-Check",
                mono: "Range Risk API",
                active: stepIndex >= 1,
                done: stepIndex >= 2,
              },
              {
                id: 2,
                title: "Generate Commitment",
                mono: "hash(nullifier, secret, amt)",
                active: stepIndex >= 2,
                done: stepIndex >= 3,
              },
              {
                id: 3,
                title: "Broadcast to Merkle Tree",
                mono: "BagsVault Program",
                active: stepIndex >= 3,
                done: stepIndex >= 4,
              },
              {
                id: 4,
                title: "Anonymity Set Updated",
                mono: "+1 commitment · new root",
                active: stepIndex >= 4,
                done: stepIndex >= 4,
              },
            ].map((s, i, arr) => (
              <div key={s.id} className="flex gap-4 relative">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-8 h-8 border flex items-center justify-center font-mono text-[11px] transition-colors ${
                      s.done
                        ? "border-[#14F195] bg-[#14F195]/10 text-[#14F195]"
                        : s.active
                        ? "border-white text-white"
                        : "border-white/10 text-zinc-600"
                    }`}
                  >
                    {s.done ? <CheckCircle2 className="w-4 h-4" /> : s.id}
                  </div>
                  {i < arr.length - 1 && (
                    <div className={`w-px flex-1 ${s.done ? "bg-[#14F195]/40" : "bg-white/10"}`} />
                  )}
                </div>
                <div className="pb-6 flex-1">
                  <p className={`text-sm ${s.active ? "text-white" : "text-zinc-500"}`}>{s.title}</p>
                  <p className="text-[10px] font-mono text-zinc-600 mt-0.5">{s.mono}</p>
                  {s.active && !s.done && step !== "idle" && (
                    <p className="text-[10px] text-[#14F195] mt-1 font-mono flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> processing…
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Risk */}
          {step !== "idle" && (
            <div className="border border-white/5 bg-[#0A0A0A] p-6 animate-fade-up">
              <div className="flex items-center justify-between mb-4">
                <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">
                  Compliance · Range Risk
                </p>
                {riskScore !== null && (
                  <span className="text-[10px] font-mono text-[#14F195]">CLEAN</span>
                )}
              </div>
              <div className="flex items-end gap-4 mb-5">
                <p className="font-display font-bold text-5xl">
                  {riskScore !== null ? riskScore : "—"}
                </p>
                <p className="text-xs text-zinc-500 mb-2">/ 100 risk score</p>
              </div>
              <div className="w-full h-1.5 bg-white/5 relative">
                <div
                  className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#14F195] via-amber-400 to-red-500 transition-all"
                  style={{ width: riskScore ? `${riskScore}%` : "0%" }}
                />
              </div>
              <div className="mt-5 space-y-2">
                {riskFlags.length > 0
                  ? riskFlags.map((f) => (
                      <div key={f.label} className="flex items-center justify-between text-xs">
                        <span className="text-zinc-400">{f.label}</span>
                        <span className="flex items-center gap-1.5 text-[#14F195] font-mono uppercase text-[10px]">
                          <CheckCircle2 className="w-3 h-3" /> {f.status}
                        </span>
                      </div>
                    ))
                  : Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-3 bg-white/5 animate-pulse" />
                    ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Note modal */}
      <Dialog open={noteOpen} onOpenChange={setNoteOpen}>
        <DialogContent className="bg-[#0A0A0A] border-white/10 text-white max-w-lg rounded-none">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-[#14F195]" />
              Deposit Successful
            </DialogTitle>
            <DialogDescription className="text-zinc-500">
              Save your private note. This is the <span className="text-white">only</span> way
              to withdraw your funds. Losing it means losing access forever.
            </DialogDescription>
          </DialogHeader>
          <div className="border border-[#14F195]/30 bg-[#14F195]/[0.03] p-4 relative">
            <p className="text-[10px] uppercase tracking-[0.2em] text-[#14F195] mb-2">Private note</p>
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
              className="flex-1 h-11 bg-white text-black font-semibold hover:bg-zinc-200 flex items-center justify-center gap-2"
            >
              <Copy className="w-4 h-4" /> Copy Note
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
              className="h-11 px-5 border border-white/15 hover:bg-white/5 flex items-center gap-2"
            >
              <Download className="w-4 h-4" /> Save
            </button>
          </div>
          <p className="text-[11px] text-amber-400 font-mono flex gap-2 items-start">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            BagsVault never stores your note. Back it up offline.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}
