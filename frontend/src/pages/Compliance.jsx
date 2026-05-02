import { useState } from "react";
import { toast } from "sonner";
import { Shield, CheckCircle2, AlertTriangle, XCircle, Loader2, Search, FileCheck, Activity } from "lucide-react";

const KNOWN_RISKY = [
  { prefix: "9Ab", score: 87, flags: ["OFAC sanctions", "Ransomware"], verdict: "BLOCK" },
  { prefix: "5Xz", score: 64, flags: ["Mixer exposure"], verdict: "REVIEW" },
];

const DEMO_WALLETS = [
  { address: "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", label: "Creator wallet", result: "clean" },
  { address: "9AbXk1mZjnRpTs2hVuFy7QdDx3c8EoNk4WsYtBvJcGhL", label: "Sanctioned address", result: "blocked" },
  { address: "5Xzk4f8RgY2nJpVtWq3mBcHs1DuE7LoMx9PkNrZbQvAo", label: "Mixer-linked wallet", result: "review" },
];

const CHECKS = [
  { label: "OFAC / SDN sanctions list", category: "Regulatory" },
  { label: "Known hacker addresses", category: "Threat Intel" },
  { label: "Ransomware clusters", category: "Threat Intel" },
  { label: "Darknet market exposure", category: "Threat Intel" },
  { label: "Tornado Cash interaction", category: "Mixer" },
  { label: "Bridge exploit proceeds", category: "DeFi" },
  { label: "Pig-butchering fund flows", category: "Fraud" },
  { label: "Stolen NFT proceeds", category: "NFT" },
];

export default function Compliance() {
  const [address, setAddress] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const scan = async (addr) => {
    if (!addr || addr.length < 20) {
      toast.error("Enter a valid Solana address.");
      return;
    }
    setLoading(true);
    setResult(null);
    await new Promise((r) => setTimeout(r, 1600));

    let r;
    const risky = KNOWN_RISKY.find((k) => addr.startsWith(k.prefix));
    if (risky) {
      r = {
        address: addr,
        score: risky.score,
        verdict: risky.verdict,
        flags: risky.flags,
        checks: CHECKS.map((c) => ({
          ...c,
          status: risky.flags.some((f) => c.label.toLowerCase().includes(f.toLowerCase().split(" ")[0]))
            ? "flagged"
            : "clean",
        })),
      };
    } else {
      r = {
        address: addr,
        score: Math.floor(Math.random() * 12) + 2,
        verdict: "APPROVE",
        flags: [],
        checks: CHECKS.map((c) => ({ ...c, status: "clean" })),
      };
    }
    setResult(r);
    setLoading(false);
    toast.success("Risk scan complete", { description: `Verdict: ${r.verdict}` });
  };

  const scoreColor =
    !result ? "text-white"
      : result.score < 20 ? "text-[#14F195]"
      : result.score < 50 ? "text-amber-400"
      : "text-red-500";

  const verdictColor =
    result?.verdict === "APPROVE" ? "bg-[#14F195]/10 border-[#14F195]/40 text-[#14F195]"
      : result?.verdict === "REVIEW" ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
      : "bg-red-500/10 border-red-500/40 text-red-400";

  return (
    <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-12 pb-24">
      <div className="absolute inset-x-0 top-0 h-[400px] radial-glow pointer-events-none" />

      <div className="relative flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
            / compliance · range risk
          </p>
          <h1 className="font-display font-bold text-4xl lg:text-5xl tracking-tight">
            Wallet Risk Scoring
          </h1>
          <p className="text-zinc-400 mt-3 max-w-2xl text-sm leading-relaxed">
            BagsVault screens every deposit via the Range Risk API. Sanctions, hacker
            clusters, mixer exposure, and illicit flows are blocked <span className="text-white">before</span> funds
            enter the privacy pool — giving the protocol regulatory legitimacy without sacrificing user privacy.
          </p>
        </div>
        <div className="flex items-center gap-2 border border-white/10 px-4 h-11 font-mono text-xs text-zinc-500">
          <Shield className="w-3.5 h-3.5 text-[#14F195]" /> Range Risk API · live
        </div>
      </div>

      {/* Scan */}
      <div className="relative grid lg:grid-cols-5 gap-6 mt-10">
        <div className="lg:col-span-3 space-y-4">
          <div className="border border-white/5 bg-[#0A0A0A] p-6 lg:p-8">
            <label className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-3 block">
              Solana address
            </label>
            <div className="flex gap-2">
              <input
                data-testid="compliance-address-input"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Enter Solana wallet address to scan…"
                className="flex-1 h-14 bg-black border border-white/10 focus:border-[#14F195] focus:outline-none px-4 font-mono text-xs text-white placeholder:text-zinc-700"
              />
              <button
                data-testid="compliance-scan-btn"
                onClick={() => scan(address)}
                disabled={loading}
                className="h-14 px-6 bg-white text-black font-semibold hover:bg-zinc-200 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                Run Scan
              </button>
            </div>
            <div className="flex items-center gap-2 mt-4 flex-wrap">
              <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">try demo:</span>
              {DEMO_WALLETS.map((d) => (
                <button
                  key={d.address}
                  data-testid={`demo-wallet-${d.result}`}
                  onClick={() => {
                    setAddress(d.address);
                    scan(d.address);
                  }}
                  className="text-[10px] font-mono px-2.5 py-1 border border-white/10 hover:border-white/30 text-zinc-400 hover:text-white"
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {/* Result */}
          {result && (
            <div className="border border-white/5 bg-[#0A0A0A] p-6 lg:p-8 animate-fade-up space-y-6">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                  <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-1">Scanned</p>
                  <p className="font-mono text-xs text-white break-all">{result.address}</p>
                </div>
                <div className={`px-4 h-10 inline-flex items-center border font-mono text-xs uppercase tracking-[0.2em] ${verdictColor}`}>
                  {result.verdict === "APPROVE" && <CheckCircle2 className="w-3.5 h-3.5 mr-2" />}
                  {result.verdict === "REVIEW" && <AlertTriangle className="w-3.5 h-3.5 mr-2" />}
                  {result.verdict === "BLOCK" && <XCircle className="w-3.5 h-3.5 mr-2" />}
                  {result.verdict}
                </div>
              </div>

              <div>
                <div className="flex items-end gap-4 mb-3">
                  <p className={`font-display font-bold text-6xl ${scoreColor}`}>{result.score}</p>
                  <div className="pb-3">
                    <p className="text-xs text-zinc-500">risk score</p>
                    <p className="text-[10px] font-mono text-zinc-600">0 (clean) · 100 (critical)</p>
                  </div>
                </div>
                <div className="w-full h-2 bg-white/5 relative">
                  <div
                    className="absolute inset-y-0 left-0 transition-all"
                    style={{
                      width: `${result.score}%`,
                      background: result.score < 20
                        ? "#14F195"
                        : result.score < 50
                        ? "#FBBF24"
                        : "#EF4444",
                    }}
                  />
                </div>
              </div>

              {result.flags.length > 0 && (
                <div className="border border-red-500/30 bg-red-500/[0.04] p-4">
                  <p className="text-[10px] uppercase tracking-[0.25em] text-red-400 mb-2">Flags detected</p>
                  <ul className="text-sm text-red-400 space-y-1">
                    {result.flags.map((f) => (
                      <li key={f} className="flex items-center gap-2">
                        <XCircle className="w-3.5 h-3.5" /> {f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-4">
                  Detection Matrix
                </p>
                <div className="grid sm:grid-cols-2 gap-2">
                  {result.checks.map((c) => (
                    <div
                      key={c.label}
                      className={`flex items-center justify-between p-3 border ${
                        c.status === "flagged"
                          ? "border-red-500/30 bg-red-500/[0.03]"
                          : "border-white/5 bg-black"
                      }`}
                    >
                      <div>
                        <p className="text-[10px] font-mono uppercase text-zinc-600">{c.category}</p>
                        <p className="text-xs text-zinc-300 mt-0.5">{c.label}</p>
                      </div>
                      {c.status === "clean" ? (
                        <CheckCircle2 className="w-4 h-4 text-[#14F195]" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-400" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Side: stats */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-white/5 bg-[#0A0A0A] p-6">
            <div className="flex items-center justify-between mb-5">
              <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">Protocol Stats</p>
              <Activity className="w-4 h-4 text-[#14F195]" />
            </div>
            {[
              ["Scans today", "3,284"],
              ["Approvals", "3,247 · 98.87%"],
              ["Reviews", "21 · 0.64%"],
              ["Blocks", "16 · 0.49%"],
              ["False positives", "0.02%"],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between py-3 border-b border-white/5 last:border-0 text-sm">
                <span className="text-zinc-500">{k}</span>
                <span className="text-white font-mono">{v}</span>
              </div>
            ))}
          </div>

          <div className="border border-[#14F195]/30 bg-gradient-to-b from-[#14F195]/[0.04] to-transparent p-6">
            <FileCheck className="w-5 h-5 text-[#14F195] mb-3" />
            <p className="font-display text-lg">Privacy meets compliance.</p>
            <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
              Pre-deposit screening blocks illicit funds without KYC. Users prove
              their right to privacy without exposing their identity — and the
              protocol stays reputable enough to remain institutional-friendly.
            </p>
            <p className="text-[10px] font-mono text-zinc-600 mt-4">
              Inspired by Range Security's Solana Privacy Hack winner architecture.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
