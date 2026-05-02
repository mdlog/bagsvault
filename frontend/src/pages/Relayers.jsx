import { useState } from "react";
import { Activity, Zap, Clock, CheckCircle2, TrendingUp, Filter, Search } from "lucide-react";

const RELAYERS = [
  { id: "rly-01", name: "NovaRelay", operator: "nova.sol", fee: 0.15, ping: 42, uptime: 99.98, jobs: 12840, volume: "412K", region: "US-East" },
  { id: "rly-02", name: "GhostNode", operator: "ghost.sol", fee: 0.20, ping: 58, uptime: 99.91, jobs: 8721, volume: "287K", region: "EU-West" },
  { id: "rly-03", name: "PhantomProxy", operator: "phantom.sol", fee: 0.12, ping: 71, uptime: 99.74, jobs: 6104, volume: "198K", region: "Asia-Pacific" },
  { id: "rly-04", name: "ZeroGateway", operator: "zerog.sol", fee: 0.18, ping: 38, uptime: 99.99, jobs: 15204, volume: "521K", region: "US-West" },
  { id: "rly-05", name: "SilentBroadcast", operator: "silent.sol", fee: 0.22, ping: 82, uptime: 99.67, jobs: 4412, volume: "142K", region: "EU-Central" },
  { id: "rly-06", name: "VaultPipe", operator: "vault.sol", fee: 0.14, ping: 49, uptime: 99.95, jobs: 11020, volume: "358K", region: "US-East" },
  { id: "rly-07", name: "MerkleMesh", operator: "merkle.sol", fee: 0.17, ping: 64, uptime: 99.88, jobs: 9450, volume: "302K", region: "Asia-Pacific" },
];

const RECENT = [
  { hash: "5a2f…9c1b", token: "SOL", amount: "10", relayer: "NovaRelay", time: "2m ago", status: "confirmed" },
  { hash: "3b8e…f012", token: "BAGS", amount: "10,000", relayer: "ZeroGateway", time: "4m ago", status: "confirmed" },
  { hash: "9d41…a7c3", token: "USDC", amount: "1,000", relayer: "PhantomProxy", time: "7m ago", status: "confirmed" },
  { hash: "7e2d…b498", token: "SOL", amount: "1", relayer: "VaultPipe", time: "11m ago", status: "confirmed" },
  { hash: "2c9a…1f56", token: "WIF", amount: "500", relayer: "NovaRelay", time: "14m ago", status: "confirmed" },
  { hash: "8f71…e032", token: "BAGS", amount: "100,000", relayer: "GhostNode", time: "18m ago", status: "confirmed" },
];

export default function Relayers() {
  const [sort, setSort] = useState("uptime");
  const [query, setQuery] = useState("");

  const sorted = [...RELAYERS]
    .filter((r) => r.name.toLowerCase().includes(query.toLowerCase()) || r.operator.includes(query))
    .sort((a, b) => {
      if (sort === "uptime") return b.uptime - a.uptime;
      if (sort === "fee") return a.fee - b.fee;
      if (sort === "ping") return a.ping - b.ping;
      return b.jobs - a.jobs;
    });

  return (
    <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-12 pb-24">
      <div className="absolute inset-x-0 top-0 h-[400px] radial-glow pointer-events-none" />

      <div className="relative">
        <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
          / infrastructure · relayers
        </p>
        <h1 className="font-display font-bold text-4xl lg:text-5xl tracking-tight">
          Relayer Network
        </h1>
        <p className="text-zinc-400 mt-3 max-w-2xl text-sm leading-relaxed">
          Independent operators submit your withdrawals, covering gas and preserving your privacy.
          All relayers are non-custodial and rated live by protocol metrics.
        </p>
      </div>

      {/* Top Stats */}
      <div className="relative grid grid-cols-2 lg:grid-cols-4 gap-px bg-white/5 border border-white/5 mt-10">
        {[
          { icon: Activity, label: "Active Relayers", value: "23", accent: "text-[#14F195]" },
          { icon: Zap, label: "24h Jobs Processed", value: "18,412", accent: "text-white" },
          { icon: TrendingUp, label: "24h Volume", value: "2.8M", suffix: "USD", accent: "solana-text" },
          { icon: Clock, label: "Avg Latency", value: "54", suffix: "ms", accent: "text-white" },
        ].map((s) => (
          <div key={s.label} className="bg-black p-6">
            <div className="flex items-center justify-between mb-4">
              <s.icon className="w-4 h-4 text-zinc-500" />
              <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">live</span>
            </div>
            <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">{s.label}</p>
            <p className={`font-display font-bold text-3xl mt-2 ${s.accent}`}>
              {s.value}
              {s.suffix && <span className="text-zinc-500 text-base ml-1">{s.suffix}</span>}
            </p>
          </div>
        ))}
      </div>

      {/* Controls */}
      <div className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mt-10">
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-600" />
          <input
            data-testid="relayer-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search relayer or operator…"
            className="w-full h-11 bg-black border border-white/10 focus:border-white/30 focus:outline-none pl-10 pr-4 text-sm text-white placeholder:text-zinc-600"
          />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500 flex items-center gap-1.5"><Filter className="w-3.5 h-3.5" /> sort</span>
          {[
            { key: "uptime", label: "Uptime" },
            { key: "fee", label: "Lowest fee" },
            { key: "ping", label: "Latency" },
            { key: "jobs", label: "Most jobs" },
          ].map((o) => (
            <button
              key={o.key}
              data-testid={`sort-${o.key}`}
              onClick={() => setSort(o.key)}
              className={`px-3 h-8 border text-xs transition-colors ${
                sort === o.key
                  ? "border-[#14F195] text-[#14F195]"
                  : "border-white/10 text-zinc-500 hover:border-white/30"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="relative border border-white/5 mt-4 overflow-x-auto">
        <table className="w-full min-w-[900px]">
          <thead>
            <tr className="border-b border-white/5 text-[10px] uppercase tracking-[0.2em] text-zinc-500">
              <th className="text-left px-5 py-4 font-normal">Relayer</th>
              <th className="text-left px-5 py-4 font-normal">Region</th>
              <th className="text-right px-5 py-4 font-normal">Fee</th>
              <th className="text-right px-5 py-4 font-normal">Ping</th>
              <th className="text-right px-5 py-4 font-normal">Uptime</th>
              <th className="text-right px-5 py-4 font-normal">24h Jobs</th>
              <th className="text-right px-5 py-4 font-normal">Volume</th>
              <th className="text-right px-5 py-4 font-normal">Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr
                key={r.id}
                data-testid={`relayer-row-${r.id}`}
                className="border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors"
              >
                <td className="px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 bg-gradient-to-br from-[#9945FF] to-[#14F195] text-black font-bold flex items-center justify-center">
                      {r.name[0]}
                    </div>
                    <div>
                      <p className="font-medium text-sm">{r.name}</p>
                      <p className="font-mono text-[10px] text-zinc-500">{r.operator}</p>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-4 text-sm text-zinc-400">{r.region}</td>
                <td className="px-5 py-4 text-right font-mono text-sm">{r.fee}%</td>
                <td className="px-5 py-4 text-right font-mono text-sm">
                  <span className={r.ping < 50 ? "text-[#14F195]" : r.ping < 80 ? "text-amber-400" : "text-zinc-400"}>
                    {r.ping}ms
                  </span>
                </td>
                <td className="px-5 py-4 text-right font-mono text-sm">
                  <span className="text-[#14F195]">{r.uptime}%</span>
                </td>
                <td className="px-5 py-4 text-right font-mono text-sm text-white">{r.jobs.toLocaleString()}</td>
                <td className="px-5 py-4 text-right font-mono text-sm">${r.volume}</td>
                <td className="px-5 py-4 text-right">
                  <span className="inline-flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.2em] text-[#14F195]">
                    <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full pulse-glow" /> online
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recent withdrawals */}
      <div className="relative mt-16">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-display font-bold text-2xl lg:text-3xl tracking-tight">
            Recent Withdrawals
          </h2>
          <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195]">
            LIVE · anonymized
          </span>
        </div>
        <div className="border border-white/5">
          {RECENT.map((r, i) => (
            <div
              key={i}
              className="flex items-center justify-between px-5 py-4 border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex items-center gap-4">
                <CheckCircle2 className="w-4 h-4 text-[#14F195]" />
                <code className="font-mono text-xs text-white">{r.hash}</code>
              </div>
              <div className="flex items-center gap-8 text-xs">
                <span className="font-mono text-white">{r.amount} {r.token}</span>
                <span className="text-zinc-500 hidden md:inline">via {r.relayer}</span>
                <span className="text-zinc-600 font-mono w-16 text-right">{r.time}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
