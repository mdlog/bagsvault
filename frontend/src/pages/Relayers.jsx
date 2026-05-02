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
  { hash: "5a2f…9c1b", token: "SOL", amount: "10", relayer: "NovaRelay", time: "2m ago" },
  { hash: "3b8e…f012", token: "BAGS", amount: "10,000", relayer: "ZeroGateway", time: "4m ago" },
  { hash: "9d41…a7c3", token: "USDC", amount: "1,000", relayer: "PhantomProxy", time: "7m ago" },
  { hash: "7e2d…b498", token: "SOL", amount: "1", relayer: "VaultPipe", time: "11m ago" },
  { hash: "2c9a…1f56", token: "WIF", amount: "500", relayer: "NovaRelay", time: "14m ago" },
  { hash: "8f71…e032", token: "BAGS", amount: "100,000", relayer: "GhostNode", time: "18m ago" },
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
    <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-20">
      <div>
        <p className="text-xs font-medium text-[#14F195] mb-2">Infrastructure · Relayers</p>
        <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">
          Relayer network
        </h1>
        <p className="text-zinc-400 mt-2 max-w-2xl text-sm leading-relaxed">
          Independent operators submit your withdrawals, covering gas and preserving your privacy.
          All relayers are non-custodial and rated live by protocol metrics.
        </p>
      </div>

      {/* Top Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-8">
        {[
          { icon: Activity, label: "Active relayers", value: "23" },
          { icon: Zap, label: "24h jobs processed", value: "18,412" },
          { icon: TrendingUp, label: "24h volume", value: "2.8M", suffix: "USD" },
          { icon: Clock, label: "Avg latency", value: "54", suffix: "ms" },
        ].map((s) => (
          <div key={s.label} className="bg-[#0a0b0d] border border-white/5 rounded-md p-5">
            <div className="flex items-center justify-between mb-3">
              <s.icon className="w-4 h-4 text-zinc-500" />
              <span className="text-[10px] text-zinc-600">live</span>
            </div>
            <p className="text-xs text-zinc-500">{s.label}</p>
            <p className="text-xl font-semibold mt-1 tracking-tight">
              {s.value}
              {s.suffix && <span className="text-zinc-500 text-sm font-normal ml-1">{s.suffix}</span>}
            </p>
          </div>
        ))}
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mt-8">
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-600" />
          <input
            data-testid="relayer-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search relayer or operator…"
            className="w-full h-10 bg-[#0a0b0d] border border-white/10 focus:border-white/25 focus:outline-none rounded-md pl-9 pr-4 text-sm text-white placeholder:text-zinc-600"
          />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500 flex items-center gap-1.5"><Filter className="w-3.5 h-3.5" /> Sort</span>
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
              className={`px-2.5 h-8 rounded-md border text-xs transition-colors ${
                sort === o.key
                  ? "border-[#14F195]/40 bg-[#14F195]/[0.05] text-[#14F195]"
                  : "border-white/10 text-zinc-400 hover:border-white/25 hover:text-white"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="border border-white/5 rounded-md mt-3 overflow-x-auto bg-[#0a0b0d]">
        <table className="w-full min-w-[900px]">
          <thead>
            <tr className="border-b border-white/5 text-xs text-zinc-500">
              <th className="text-left px-5 py-3 font-medium">Relayer</th>
              <th className="text-left px-5 py-3 font-medium">Region</th>
              <th className="text-right px-5 py-3 font-medium">Fee</th>
              <th className="text-right px-5 py-3 font-medium">Ping</th>
              <th className="text-right px-5 py-3 font-medium">Uptime</th>
              <th className="text-right px-5 py-3 font-medium">24h jobs</th>
              <th className="text-right px-5 py-3 font-medium">Volume</th>
              <th className="text-right px-5 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={r.id}
                data-testid={`relayer-row-${r.id}`}
                className="border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors"
              >
                <td className="px-5 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-[#14F195]/15 border border-[#14F195]/40 text-[#14F195] font-semibold flex items-center justify-center rounded-md text-sm">
                      {r.name[0]}
                    </div>
                    <div>
                      <p className="font-medium text-sm">{r.name}</p>
                      <p className="font-mono text-[10px] text-zinc-500">{r.operator}</p>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3.5 text-sm text-zinc-400">{r.region}</td>
                <td className="px-5 py-3.5 text-right font-mono text-sm">{r.fee}%</td>
                <td className="px-5 py-3.5 text-right font-mono text-sm">
                  <span className={r.ping < 50 ? "text-[#14F195]" : r.ping < 80 ? "text-amber-400" : "text-zinc-400"}>
                    {r.ping}ms
                  </span>
                </td>
                <td className="px-5 py-3.5 text-right font-mono text-sm text-[#14F195]">{r.uptime}%</td>
                <td className="px-5 py-3.5 text-right font-mono text-sm text-white">{r.jobs.toLocaleString()}</td>
                <td className="px-5 py-3.5 text-right font-mono text-sm">${r.volume}</td>
                <td className="px-5 py-3.5 text-right">
                  <span className="inline-flex items-center gap-1.5 text-[11px] text-[#14F195]">
                    <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" /> Online
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recent withdrawals */}
      <div className="mt-12">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg lg:text-xl font-semibold tracking-tight">
            Recent withdrawals
          </h2>
          <span className="text-[11px] text-[#14F195] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
            Live · anonymized
          </span>
        </div>
        <div className="border border-white/5 rounded-md bg-[#0a0b0d]">
          {RECENT.map((r, i) => (
            <div
              key={i}
              className="flex items-center justify-between px-5 py-3 border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-4 h-4 text-[#14F195]" />
                <code className="font-mono text-xs text-white">{r.hash}</code>
              </div>
              <div className="flex items-center gap-6 text-xs">
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
