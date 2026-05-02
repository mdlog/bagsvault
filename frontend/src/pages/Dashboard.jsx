// Dashboard — primary landing page for connected users.
//
// Privacy contract: this page MUST NOT show per-wallet activity. The whole
// point of a privacy pool is to break the on-chain link between deposit
// and withdrawal — a "your transactions" feed would re-create that link.
// What we DO show:
//   * Pool-wide anonymity-set health (commitment count, current root)
//   * System indicators (indexer, RPC, relayer count)
//   * Anonymized recent activity (no addresses, no amounts you can map back)
//   * Quick action cards routing to Deposit / Withdraw / Compliance
//
// Wallet info is shown only because the user is the one looking at it.

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useWallet } from "@/context/WalletContext";
import { toast } from "sonner";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ShieldCheck,
  Activity,
  Layers,
  Server,
  Copy,
  ExternalLink,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Lock,
  Loader2,
  AlertTriangle,
  Wallet,
} from "lucide-react";
import {
  getAnonymityState,
  getRecentDeposits,
  getRecentWithdrawals,
  getRelayers,
  getComplianceStats,
} from "@/lib/zk_client";

// ----------------------------------------------------------------------
// Sub-components
// ----------------------------------------------------------------------

function StatCard({ icon: Icon, label, value, hint, accent = "white" }) {
  const accentColor =
    accent === "green"
      ? "text-[#14F195]"
      : accent === "amber"
        ? "text-amber-400"
        : "text-white";
  return (
    <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wider text-zinc-500">
          {label}
        </p>
        <Icon className={`w-4 h-4 ${accentColor}`} />
      </div>
      <p className={`text-2xl font-semibold mt-3 ${accentColor}`}>{value}</p>
      {hint && <p className="text-[11px] text-zinc-500 mt-1">{hint}</p>}
    </div>
  );
}

function QuickActionCard({ to, icon: Icon, title, desc, accent }) {
  return (
    <Link
      to={to}
      className="group border border-white/5 bg-[#0a0b0d] p-5 rounded-md hover:border-white/20 transition-colors"
    >
      <div
        className="w-9 h-9 flex items-center justify-center rounded-md mb-4"
        style={{
          background: `${accent}14`,
          border: `1px solid ${accent}40`,
        }}
      >
        <Icon className="w-4 h-4" style={{ color: accent }} />
      </div>
      <p className="text-sm font-semibold text-white">{title}</p>
      <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{desc}</p>
      <p
        className="text-[11px] mt-3 inline-flex items-center gap-1 group-hover:translate-x-0.5 transition-transform"
        style={{ color: accent }}
      >
        Open →
      </p>
    </Link>
  );
}

function ActivityRow({ icon: Icon, label, amount, token, time, sig, accent }) {
  const explorerUrl = sig
    ? `https://explorer.solana.com/tx/${sig}?cluster=devnet`
    : null;
  return (
    <div className="flex items-center gap-3 py-3 border-b border-white/5 last:border-0">
      <div
        className="w-8 h-8 flex items-center justify-center rounded-md flex-shrink-0"
        style={{ background: `${accent}10`, border: `1px solid ${accent}30` }}
      >
        <Icon className="w-3.5 h-3.5" style={{ color: accent }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white">
          {label}{" "}
          <span className="font-mono text-xs text-zinc-300">
            {amount} {token}
          </span>
        </p>
        <p className="text-[11px] text-zinc-500 mt-0.5">{time}</p>
      </div>
      {explorerUrl && (
        <a
          href={explorerUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[11px] text-zinc-500 hover:text-white inline-flex items-center gap-1 flex-shrink-0"
          title="Open on Solana Explorer"
        >
          <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}

function EmptyFeed({ label }) {
  return (
    <div className="text-center py-8 text-xs text-zinc-600">
      <Lock className="w-5 h-5 mx-auto mb-2 text-zinc-700" />
      No {label} yet. The pool is fresh — be the first.
    </div>
  );
}

// ----------------------------------------------------------------------
// Main page
// ----------------------------------------------------------------------

export default function Dashboard() {
  const { wallet, balance, connect, connecting } = useWallet();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pool, setPool] = useState(null); // { count, current_root, source }
  const [deposits, setDeposits] = useState([]);
  const [withdrawals, setWithdrawals] = useState([]);
  const [relayers, setRelayers] = useState([]);
  const [compliance, setCompliance] = useState(null);

  const fetchAll = async (silent = false) => {
    if (!silent) setRefreshing(true);
    try {
      const [poolR, depR, wdR, relR, compR] = await Promise.allSettled([
        getAnonymityState(),
        getRecentDeposits(8),
        getRecentWithdrawals(8),
        getRelayers(),
        getComplianceStats(),
      ]);
      if (poolR.status === "fulfilled") setPool(poolR.value);
      if (depR.status === "fulfilled") {
        setDeposits(depR.value?.items || depR.value || []);
      }
      if (wdR.status === "fulfilled") {
        setWithdrawals(wdR.value?.items || wdR.value || []);
      }
      if (relR.status === "fulfilled") {
        setRelayers(relR.value?.items || relR.value || []);
      }
      if (compR.status === "fulfilled") setCompliance(compR.value);
    } catch (err) {
      if (!silent) toast.error("Failed to refresh dashboard.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const id = setInterval(() => fetchAll(true), 30_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalActivity = (deposits?.length || 0) + (withdrawals?.length || 0);

  const indexerOk = pool?.source === "indexer" || pool?.count > 0;
  const indexerLabel = !pool
    ? "—"
    : indexerOk
      ? "Live"
      : pool?.source === "fallback-empty"
        ? "Empty"
        : "Idle";

  const shortRoot = useMemo(() => {
    const r = pool?.current_root || pool?.root;
    if (!r || typeof r !== "string") return "—";
    if (r.length <= 16) return r;
    return `${r.slice(0, 8)}…${r.slice(-6)}`;
  }, [pool]);

  // ---- Not connected → CTA layout ------------------------------------
  if (!wallet) {
    return (
      <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-20">
        <div className="text-center py-20 max-w-2xl mx-auto">
          <div className="w-14 h-14 mx-auto bg-[#14F195]/10 border border-[#14F195]/30 rounded-md flex items-center justify-center mb-6">
            <Wallet className="w-6 h-6 text-[#14F195]" />
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Connect your wallet
          </h1>
          <p className="text-zinc-400 mt-3 leading-relaxed">
            Sign in with Phantom, Solflare, or any wallet-standard browser
            extension to access your BagsVault dashboard.
          </p>
          <button
            onClick={() => connect()}
            disabled={connecting}
            className="mt-8 h-11 px-6 bg-white text-black rounded-md font-medium text-sm hover:bg-zinc-200 disabled:opacity-60 inline-flex items-center gap-2"
          >
            {connecting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Connecting…
              </>
            ) : (
              <>
                <Wallet className="w-4 h-4" /> Connect wallet
              </>
            )}
          </button>
          <p className="text-[11px] text-zinc-600 mt-6">
            BagsVault never holds your signing key. Transactions sign locally
            in your wallet.
          </p>
        </div>
      </div>
    );
  }

  // ---- Connected → full dashboard ------------------------------------
  return (
    <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-20">
      {/* Welcome bar */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <p className="text-xs font-medium text-[#14F195] mb-2">
            Dashboard · Pool overview
          </p>
          <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight">
            Welcome back
          </h1>
          <p className="text-zinc-400 mt-2 max-w-xl text-sm leading-relaxed">
            Live state of the BagsVault privacy pool. We never display your
            personal transaction history — that would defeat the anonymity
            guarantee.
          </p>
        </div>
        <button
          onClick={() => fetchAll()}
          disabled={refreshing}
          className="inline-flex items-center gap-2 border border-white/10 hover:border-white/25 px-3 h-9 rounded-md text-xs text-zinc-400 disabled:opacity-50"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`}
          />
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Wallet card */}
      <div className="mt-6 border border-[#14F195]/25 bg-gradient-to-br from-[#14F195]/[0.06] to-transparent p-5 rounded-md flex items-center justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-4 min-w-0">
          <div className="w-11 h-11 bg-[#14F195]/10 border border-[#14F195]/40 rounded-md flex items-center justify-center flex-shrink-0">
            <ShieldCheck className="w-5 h-5 text-[#14F195]" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] text-zinc-500 uppercase tracking-wider">
              Connected via {wallet.provider}
            </p>
            <p className="font-mono text-sm text-white mt-1 truncate">
              {wallet.address}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="text-right">
            <p className="text-[11px] text-zinc-500 uppercase tracking-wider">
              Balance
            </p>
            <p className="font-mono text-base text-white mt-1">
              {balance?.toFixed(4) ?? "0.0000"} SOL
            </p>
          </div>
          <button
            onClick={() => {
              navigator.clipboard.writeText(wallet.address);
              toast.success("Address copied");
            }}
            className="h-9 w-9 flex items-center justify-center border border-white/10 hover:border-white/25 rounded-md"
            title="Copy address"
          >
            <Copy className="w-3.5 h-3.5 text-zinc-400" />
          </button>
          <a
            href={`https://explorer.solana.com/address/${wallet.address}?cluster=devnet`}
            target="_blank"
            rel="noopener noreferrer"
            className="h-9 w-9 flex items-center justify-center border border-white/10 hover:border-white/25 rounded-md"
            title="View on Solana Explorer"
          >
            <ExternalLink className="w-3.5 h-3.5 text-zinc-400" />
          </a>
        </div>
      </div>

      {/* Stats grid */}
      <div className="mt-5 grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Layers}
          label="Anonymity set"
          value={loading ? "…" : (pool?.count ?? 0).toLocaleString()}
          hint={
            pool?.count
              ? `${pool.count} commitments · root ${shortRoot}`
              : "Empty pool — first deposit seeds the set."
          }
          accent="green"
        />
        <StatCard
          icon={TrendingUp}
          label="Recent activity"
          value={loading ? "…" : totalActivity}
          hint={
            totalActivity
              ? `${deposits.length} deposits · ${withdrawals.length} withdrawals`
              : "No activity in the last window."
          }
        />
        <StatCard
          icon={Server}
          label="Indexer"
          value={loading ? "…" : indexerLabel}
          hint={pool?.source ? `source: ${pool.source}` : "—"}
          accent={indexerOk ? "green" : "amber"}
        />
        <StatCard
          icon={Activity}
          label="Active relayers"
          value={loading ? "…" : relayers.length}
          hint={
            relayers[0]
              ? `${relayers[0].name || relayers[0].relayer_id} · top`
              : "No relayers registered."
          }
        />
      </div>

      {/* Quick actions */}
      <div className="mt-6">
        <p className="text-[11px] uppercase tracking-wider text-zinc-500 mb-3">
          Quick actions
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <QuickActionCard
            to="/deposit"
            icon={ArrowDownToLine}
            title="Deposit into the pool"
            desc="Generate a commitment, sign the deposit tx in your wallet, and join the anonymity set."
            accent="#14F195"
          />
          <QuickActionCard
            to="/withdraw"
            icon={ArrowUpFromLine}
            title="Withdraw anonymously"
            desc="Submit a ZK proof + your private note. The relayer pays gas; funds land at a fresh address."
            accent="#9945FF"
          />
          <QuickActionCard
            to="/compliance"
            icon={ShieldCheck}
            title="Run a risk scan"
            desc="Check a wallet against the Range Risk API before depositing — pre-deposit gating keeps the pool clean."
            accent="#FFA500"
          />
        </div>
      </div>

      {/* Activity feeds */}
      <div className="mt-6 grid lg:grid-cols-2 gap-4">
        <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-white flex items-center gap-2">
              <ArrowDownToLine className="w-3.5 h-3.5 text-[#14F195]" />
              Recent deposits
            </p>
            <span className="text-[11px] text-zinc-600 font-mono">
              anonymized
            </span>
          </div>
          {loading ? (
            <div className="text-center py-8 text-xs text-zinc-600">
              <Loader2 className="w-4 h-4 mx-auto mb-2 animate-spin" />
              Loading…
            </div>
          ) : deposits.length === 0 ? (
            <EmptyFeed label="deposits" />
          ) : (
            <div>
              {deposits.slice(0, 6).map((d, i) => (
                <ActivityRow
                  key={d.tx_signature || d.commitment || i}
                  icon={ArrowDownToLine}
                  label="Commitment"
                  amount={d.amount ? formatAmount(d.amount, d.token) : "—"}
                  token={d.token || "SOL"}
                  time={d.relative_time || "just now"}
                  sig={d.tx_signature}
                  accent="#14F195"
                />
              ))}
            </div>
          )}
        </div>
        <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-white flex items-center gap-2">
              <ArrowUpFromLine className="w-3.5 h-3.5 text-[#9945FF]" />
              Recent withdrawals
            </p>
            <span className="text-[11px] text-zinc-600 font-mono">
              relayer-paid
            </span>
          </div>
          {loading ? (
            <div className="text-center py-8 text-xs text-zinc-600">
              <Loader2 className="w-4 h-4 mx-auto mb-2 animate-spin" />
              Loading…
            </div>
          ) : withdrawals.length === 0 ? (
            <EmptyFeed label="withdrawals" />
          ) : (
            <div>
              {withdrawals.slice(0, 6).map((w, i) => (
                <ActivityRow
                  key={w.tx_signature || i}
                  icon={ArrowUpFromLine}
                  label={w.relayer_name ? `via ${w.relayer_name}` : "Withdraw"}
                  amount={w.amount ? formatAmount(w.amount, w.token) : "—"}
                  token={w.token || "SOL"}
                  time={w.relative_time || "just now"}
                  sig={w.tx_signature}
                  accent="#9945FF"
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Relayer leaderboard + compliance preview */}
      <div className="mt-4 grid lg:grid-cols-2 gap-4">
        <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
          <p className="text-sm font-medium text-white flex items-center gap-2 mb-3">
            <Server className="w-3.5 h-3.5 text-zinc-400" />
            Active relayer network
          </p>
          {loading ? (
            <div className="text-xs text-zinc-600">Loading…</div>
          ) : relayers.length === 0 ? (
            <p className="text-xs text-zinc-600">No relayers registered yet.</p>
          ) : (
            <div className="space-y-2">
              {relayers.slice(0, 3).map((r, i) => (
                <div
                  key={r.relayer_id || i}
                  className="flex items-center justify-between py-2 border-b border-white/5 last:border-0"
                >
                  <div className="min-w-0">
                    <p className="text-sm text-white truncate">
                      {r.name || r.relayer_id}
                    </p>
                    <p className="text-[11px] text-zinc-500">
                      {r.region || "—"} · {r.fee_bps ?? r.fee ?? "—"}{" "}
                      {typeof r.fee_bps === "number" ? "bps" : "fee"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
                    <span className="text-[11px] text-zinc-400 font-mono">
                      {r.uptime_pct
                        ? `${r.uptime_pct.toFixed(2)}%`
                        : "online"}
                    </span>
                  </div>
                </div>
              ))}
              <Link
                to="/relayers"
                className="text-xs text-[#14F195] hover:text-white inline-flex items-center gap-1 mt-2"
              >
                View all relayers →
              </Link>
            </div>
          )}
        </div>

        <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
          <p className="text-sm font-medium text-white flex items-center gap-2 mb-3">
            <Sparkles className="w-3.5 h-3.5 text-zinc-400" />
            Compliance summary
          </p>
          {loading ? (
            <div className="text-xs text-zinc-600">Loading…</div>
          ) : !compliance ? (
            <p className="text-xs text-zinc-600">No scan history yet.</p>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <div className="border border-white/5 rounded-md p-3 bg-[#07080a]">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Approved
                </p>
                <p className="text-lg font-semibold text-[#14F195] mt-1">
                  {compliance.approvals ?? 0}
                </p>
              </div>
              <div className="border border-white/5 rounded-md p-3 bg-[#07080a]">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Review
                </p>
                <p className="text-lg font-semibold text-amber-400 mt-1">
                  {compliance.reviews ?? 0}
                </p>
              </div>
              <div className="border border-white/5 rounded-md p-3 bg-[#07080a]">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                  Blocked
                </p>
                <p className="text-lg font-semibold text-red-400 mt-1">
                  {compliance.blocks ?? 0}
                </p>
              </div>
            </div>
          )}
          <Link
            to="/compliance"
            className="text-xs text-[#14F195] hover:text-white inline-flex items-center gap-1 mt-3"
          >
            Run a scan →
          </Link>
        </div>
      </div>

      {/* Privacy reminder */}
      <div className="mt-6 border border-white/5 bg-[#0a0b0d] p-4 rounded-md flex gap-3 items-start">
        <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-zinc-400 leading-relaxed">
          <span className="text-zinc-200 font-medium">Privacy reminder:</span>{" "}
          BagsVault never stores your private notes. After every deposit,
          download or back up the note offline — it's the only way to
          withdraw.
        </div>
      </div>
    </div>
  );
}

// Format a base-unit amount back into a human number. Mirrors
// `Deposit.jsx::toBaseUnits` (inverse).
function formatAmount(baseUnits, token) {
  const n = Number(baseUnits) || 0;
  if (token === "USDC") return (n / 1_000_000).toLocaleString();
  return (n / 1_000_000_000).toLocaleString();
}
