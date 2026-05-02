import { useState } from "react";
import { toast } from "sonner";
import {
  Shield,
  CheckCircle2,
  Loader2,
  Lock,
  Cpu,
  ArrowRight,
  Zap,
  Key,
  AlertTriangle,
} from "lucide-react";

const RELAYERS = [
  { id: "rly-01", name: "NovaRelay", fee: 0.15, ping: 42, uptime: 99.98 },
  { id: "rly-02", name: "GhostNode", fee: 0.20, ping: 58, uptime: 99.91 },
  { id: "rly-03", name: "PhantomProxy", fee: 0.12, ping: 71, uptime: 99.74 },
];

export default function Withdraw() {
  const [note, setNote] = useState("");
  const [recipient, setRecipient] = useState("");
  const [relayer, setRelayer] = useState("rly-01");
  const [stage, setStage] = useState("idle"); // idle|parsing|proving|submitting|done
  const [progress, setProgress] = useState(0);
  const [parsed, setParsed] = useState(null);
  const [txHash, setTxHash] = useState("");

  const handleParse = () => {
    if (!note.startsWith("bagsvault-v1-")) {
      toast.error("Invalid note format.");
      return;
    }
    const parts = note.split("-");
    setParsed({
      chain: parts[2] || "solana",
      token: (parts[3] || "sol").toUpperCase(),
      amount: parts[4] || "1",
      secret: note.slice(-12),
    });
    toast.success("Note decrypted", { description: "Ready to generate proof." });
  };

  const withdraw = async () => {
    if (!parsed) {
      toast.error("Paste a valid note first.");
      return;
    }
    if (!recipient || recipient.length < 20) {
      toast.error("Enter a valid recipient address.");
      return;
    }
    setStage("proving");
    setProgress(0);
    // Fake progress
    const start = Date.now();
    const duration = 3500;
    const tick = setInterval(() => {
      const p = Math.min(100, ((Date.now() - start) / duration) * 100);
      setProgress(p);
      if (p >= 100) clearInterval(tick);
    }, 60);

    await new Promise((r) => setTimeout(r, duration));

    setStage("submitting");
    await new Promise((r) => setTimeout(r, 1600));

    const hash = "5" + Array.from({ length: 87 })
      .map(() => "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMN".charAt(Math.floor(Math.random() * 50)))
      .join("");
    setTxHash(hash);
    setStage("done");
    toast.success("Withdrawal successful", {
      description: `Sent ${parsed.amount} ${parsed.token} to fresh wallet.`,
    });
  };

  const reset = () => {
    setStage("idle");
    setProgress(0);
    setParsed(null);
    setNote("");
    setRecipient("");
    setTxHash("");
  };

  const selectedRelayer = RELAYERS.find((r) => r.id === relayer);

  return (
    <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-12 pb-24">
      <div className="absolute inset-x-0 top-0 h-[400px] radial-glow pointer-events-none" />

      <div className="relative flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#9945FF] mb-3">
            / protocol · withdraw
          </p>
          <h1 className="font-display font-bold text-4xl lg:text-5xl tracking-tight">
            Anonymous withdrawal
          </h1>
          <p className="text-zinc-400 mt-3 max-w-xl text-sm leading-relaxed">
            Paste your private note. A ZK-SNARK proof is generated in your browser —
            no on-chain link between deposit and payout.
          </p>
        </div>
        <div className="flex items-center gap-2 border border-white/10 px-4 h-11 font-mono text-xs text-zinc-500">
          <Cpu className="w-3.5 h-3.5 text-[#9945FF]" /> Noir · Groth16
        </div>
      </div>

      <div className="relative grid lg:grid-cols-5 gap-6 mt-10">
        {/* Form */}
        <div className="lg:col-span-3 space-y-4">
          <div className="border border-white/5 bg-[#0A0A0A] p-6 lg:p-8 space-y-6">
            <div>
              <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-2 block">
                Private Note
              </label>
              <div className="relative">
                <textarea
                  data-testid="note-textarea"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="bagsvault-v1-solana-sol-1-..."
                  rows={4}
                  className="w-full bg-black border border-white/10 focus:border-[#9945FF] focus:outline-none p-4 font-mono text-xs text-white placeholder:text-zinc-700 resize-none"
                />
                <Key className="absolute top-3 right-3 w-4 h-4 text-zinc-700" />
              </div>
              <button
                data-testid="parse-note-btn"
                onClick={handleParse}
                disabled={!note}
                className="mt-2 text-xs text-[#14F195] hover:text-white disabled:opacity-40 font-mono uppercase tracking-[0.2em]"
              >
                → decrypt & verify
              </button>
              {parsed && (
                <div className="mt-4 grid grid-cols-3 gap-3 animate-fade-up">
                  {[
                    ["chain", parsed.chain],
                    ["amount", `${parsed.amount} ${parsed.token}`],
                    ["secret", `…${parsed.secret}`],
                  ].map(([k, v]) => (
                    <div key={k} className="border border-white/5 p-3 bg-black">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">{k}</p>
                      <p className="font-mono text-xs mt-1 text-white truncate">{v}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-2 block">
                Recipient (fresh wallet)
              </label>
              <input
                data-testid="recipient-input"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="Solana address — any clean wallet"
                className="w-full h-14 bg-black border border-white/10 focus:border-[#9945FF] focus:outline-none px-4 font-mono text-xs text-white placeholder:text-zinc-700"
              />
              <p className="text-[11px] text-zinc-600 mt-2 font-mono">
                Use a newly generated wallet for maximum privacy.
              </p>
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-2 block">
                Select Relayer
              </label>
              <div className="space-y-2">
                {RELAYERS.map((r) => (
                  <button
                    key={r.id}
                    data-testid={`relayer-${r.id}`}
                    onClick={() => setRelayer(r.id)}
                    className={`w-full p-4 border text-left transition-all ${
                      relayer === r.id
                        ? "border-[#14F195] bg-[#14F195]/5"
                        : "border-white/10 hover:border-white/30"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className={`w-2 h-2 rounded-full ${relayer === r.id ? "bg-[#14F195] pulse-glow" : "bg-zinc-700"}`} />
                        <span className="font-medium">{r.name}</span>
                        <span className="font-mono text-[10px] text-zinc-500">{r.id}</span>
                      </div>
                      <div className="flex items-center gap-5 text-xs font-mono">
                        <span className="text-zinc-400">fee <span className="text-white">{r.fee}%</span></span>
                        <span className="text-zinc-400">ping <span className="text-white">{r.ping}ms</span></span>
                        <span className="text-zinc-400">up <span className="text-[#14F195]">{r.uptime}%</span></span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-white/5 pt-6 space-y-3 text-sm">
              <div className="flex justify-between"><span className="text-zinc-500">Withdrawing</span><span className="text-white">{parsed ? `${parsed.amount} ${parsed.token}` : "—"}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">Relayer fee</span><span className="text-white">{selectedRelayer?.fee}%</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">Network cost</span><span className="text-white">gasless</span></div>
              <div className="flex justify-between pt-3 border-t border-white/5">
                <span className="text-zinc-500">You receive</span>
                <span className="text-white font-display font-bold text-xl">
                  {parsed ? (parseFloat(parsed.amount) * (1 - (selectedRelayer?.fee || 0) / 100)).toFixed(4) : "—"}{" "}
                  <span className="text-zinc-500 text-sm">{parsed?.token}</span>
                </span>
              </div>
            </div>

            {stage === "done" ? (
              <div className="space-y-3">
                <div className="border border-[#14F195]/40 bg-[#14F195]/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.2em] text-[#14F195]">Signature</p>
                  <p className="font-mono text-[11px] text-white mt-1 break-all">{txHash}</p>
                </div>
                <button
                  data-testid="new-withdrawal-btn"
                  onClick={reset}
                  className="w-full h-14 border border-white/15 hover:bg-white/5 font-semibold"
                >
                  Start New Withdrawal
                </button>
              </div>
            ) : (
              <button
                data-testid="withdraw-submit-btn"
                onClick={withdraw}
                disabled={stage !== "idle" || !parsed}
                className="w-full h-14 bg-[#14F195] text-black font-semibold hover:bg-[#14F195]/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {stage === "proving" ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Generating proof…</>
                ) : stage === "submitting" ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Submitting…</>
                ) : (
                  <>Generate Proof & Withdraw <ArrowRight className="w-4 h-4" /></>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Proof Pipeline */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-white/5 bg-[#0A0A0A] p-6">
            <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-5">
              ZK Proof Pipeline
            </p>

            <div className="border border-white/5 p-5 bg-black mb-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs text-white">Groth16 proof generation</p>
                <span className="font-mono text-[10px] text-[#9945FF]">{Math.floor(progress)}%</span>
              </div>
              <div className="w-full h-1.5 bg-white/5 relative overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#9945FF] to-[#14F195] transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="grid grid-cols-3 gap-2 mt-4 text-[10px] font-mono">
                {[
                  ["witness", progress > 15],
                  ["prover", progress > 55],
                  ["verify", progress > 95],
                ].map(([label, active], i) => (
                  <div
                    key={i}
                    className={`text-center py-2 border ${
                      active ? "border-[#14F195]/40 text-[#14F195]" : "border-white/5 text-zinc-700"
                    }`}
                  >
                    {label}
                  </div>
                ))}
              </div>
            </div>

            {[
              { icon: Shield, label: "Note decrypted", active: !!parsed },
              { icon: Cpu, label: "Witness computed", active: stage === "proving" ? progress > 20 : stage !== "idle" },
              { icon: Lock, label: "Proof generated", active: stage === "submitting" || stage === "done" },
              { icon: Zap, label: "Relayer submitted", active: stage === "done" },
            ].map((s, i, arr) => (
              <div key={i} className="flex items-center gap-3 py-3 border-b border-white/5 last:border-0">
                <s.icon className={`w-4 h-4 ${s.active ? "text-[#14F195]" : "text-zinc-700"}`} />
                <span className={`text-sm ${s.active ? "text-white" : "text-zinc-600"}`}>{s.label}</span>
                {s.active && <CheckCircle2 className="w-4 h-4 text-[#14F195] ml-auto" />}
              </div>
            ))}
          </div>

          <div className="border border-white/5 bg-[#0A0A0A] p-6">
            <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-4">
              Anonymity Set
            </p>
            <p className="font-display font-bold text-4xl">47,129</p>
            <p className="text-xs text-zinc-500 mt-1">active commitments</p>
            <div className="mt-5 grid grid-cols-10 gap-1">
              {Array.from({ length: 40 }).map((_, i) => (
                <div
                  key={i}
                  className={`aspect-square ${
                    i === 7
                      ? "bg-[#9945FF] border border-[#9945FF]"
                      : "bg-white/[0.04] border border-white/5"
                  }`}
                />
              ))}
            </div>
            <p className="text-[10px] text-zinc-500 mt-3 font-mono flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3 text-amber-500" />
              your commitment is indistinguishable from the rest
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
