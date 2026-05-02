import { useState } from "react";
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
  { symbol: "SOL", name: "Solana", icon: "◎", balance: 12.4 },
  { symbol: "BAGS", name: "Bags", icon: "B", balance: 12340 },
  { symbol: "USDC", name: "USD Coin", icon: "$", balance: 820.55 },
  { symbol: "WIF", name: "dogwifhat", icon: "W", balance: 2100 },
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
  const [mode, setMode] = useState("standard");

  const [step, setStep] = useState("idle");
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
    setStep("compliance");
    setRiskScore(null);
    setRiskFlags([]);
    await new Promise((r) => setTimeout(r, 1400));
    const score = Math.floor(Math.random() * 15) + 2;
    setRiskScore(score);
    setRiskFlags([
      { label: "OFAC sanctions", status: "clean" },
      { label: "Known hacker addresses", status: "clean" },
      { label: "Mixer exposure", status: "clean" },
      { label: "Illicit flows", status: "clean" },
    ]);
    await new Promise((r) => setTimeout(r, 800));

    setStep("commitment");
    await new Promise((r) => setTimeout(r, 1800));

    setStep("broadcast");
    await new Promise((r) => setTimeout(r, 1800));

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
    <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-20">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-xs font-medium text-[#14F195] mb-2">Protocol · Deposit</p>
          <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">
            Deposit into the pool
          </h1>
          <p className="text-zinc-400 mt-2 max-w-xl text-sm leading-relaxed">
            Add liquidity to the BagsVault anonymity set. Your commitment will join
            47,129 others — indistinguishable on-chain.
          </p>
        </div>
        <div className="flex items-center gap-2 border border-white/10 px-3 h-9 rounded-md text-xs text-zinc-400">
          <Lock className="w-3.5 h-3.5 text-[#14F195]" /> client-side encryption
        </div>
      </div>

      <div className="grid lg:grid-cols-5 gap-5 mt-8">
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
            {mode === "creator-fee" && (
              <div className="border border-[#14F195]/30 bg-[#14F195]/[0.05] rounded-md p-3.5 flex gap-3 items-start">
                <div>
                  <p className="text-xs font-medium text-[#14F195]">Creator fee mode</p>
                  <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                    Unclaimed Bags fees will be routed directly into your vault commitment.
                    Pending: <span className="font-mono text-white">2.47 SOL · 18,420 BAGS</span>
                  </p>
                </div>
              </div>
            )}

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
                <label className="text-xs text-zinc-400">Fixed denomination</label>
                <span className="text-xs text-zinc-500">
                  Balance · <span className="text-zinc-300 font-mono">{tokenInfo.balance.toLocaleString()} {token}</span>
                </span>
              </div>
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

            {/* Summary */}
            <div className="border-t border-white/5 pt-5 space-y-2.5 text-sm">
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
              className="w-full h-11 bg-white text-black rounded-md font-medium text-sm hover:bg-zinc-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {step !== "idle" && step !== "done" ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Processing…</>
              ) : (
                <>Deposit {amount.toLocaleString()} {token} <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </div>
        </div>

        {/* RIGHT: Status */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
            <p className="text-xs font-medium text-zinc-300 mb-4">Transaction pipeline</p>
            {[
              { id: 1, title: "Risk pre-check", mono: "Range Risk API", active: stepIndex >= 1, done: stepIndex >= 2 },
              { id: 2, title: "Generate commitment", mono: "hash(nullifier, secret, amt)", active: stepIndex >= 2, done: stepIndex >= 3 },
              { id: 3, title: "Broadcast to Merkle tree", mono: "BagsVault Program", active: stepIndex >= 3, done: stepIndex >= 4 },
              { id: 4, title: "Anonymity set updated", mono: "+1 commitment · new root", active: stepIndex >= 4, done: stepIndex >= 4 },
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
                  {s.active && !s.done && step !== "idle" && (
                    <p className="text-[11px] text-[#14F195] mt-1 flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> processing…
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Risk */}
          {step !== "idle" && (
            <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md animate-fade-up">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium text-zinc-300">Compliance · Range Risk</p>
                {riskScore !== null && (
                  <span className="text-[10px] font-mono text-[#14F195]">CLEAN</span>
                )}
              </div>
              <div className="flex items-end gap-3 mb-4">
                <p className="text-4xl font-semibold tracking-tight">
                  {riskScore !== null ? riskScore : "—"}
                </p>
                <p className="text-xs text-zinc-500 mb-1.5">/ 100 risk score</p>
              </div>
              <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#14F195] transition-all"
                  style={{ width: riskScore ? `${riskScore}%` : "0%" }}
                />
              </div>
              <div className="mt-4 space-y-2">
                {riskFlags.length > 0
                  ? riskFlags.map((f) => (
                      <div key={f.label} className="flex items-center justify-between text-xs">
                        <span className="text-zinc-400">{f.label}</span>
                        <span className="flex items-center gap-1.5 text-[#14F195] text-[11px]">
                          <CheckCircle2 className="w-3 h-3" /> {f.status}
                        </span>
                      </div>
                    ))
                  : Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-3 bg-white/5 rounded animate-pulse" />
                    ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Note modal */}
      <Dialog open={noteOpen} onOpenChange={setNoteOpen}>
        <DialogContent className="bg-[#0c0d10] border-white/10 text-white max-w-lg rounded-lg">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-[#14F195]" />
              Deposit successful
            </DialogTitle>
            <DialogDescription className="text-zinc-500 text-sm">
              Save your private note. This is the <span className="text-white">only</span> way
              to withdraw your funds. Losing it means losing access forever.
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
