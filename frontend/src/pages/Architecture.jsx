import { useState } from "react";
import {
  Cpu, Database, Network, Shield, Lock, FileKey,
  ArrowRight, Layers, Zap, GitBranch, Eye,
} from "lucide-react";

const PILLARS = [
  {
    id: "smart-contract",
    title: "Smart Contract Layer",
    subtitle: "Solana · Anchor",
    color: "#9945FF",
    icon: Database,
    components: [
      { name: "BagsVault Program", desc: "Receives deposits, verifies proofs, executes withdrawals" },
      { name: "Merkle Tree State", desc: "Stores 10 most recent commitment roots" },
      { name: "Nullifier Set", desc: "Prevents double-spending of commitments" },
      { name: "Groth16 Verifier", desc: "CPI to Sunspot Verifier Program" },
    ],
  },
  {
    id: "bags-api",
    title: "Bags API Layer",
    subtitle: "Native Integration",
    color: "#14F195",
    icon: Network,
    components: [
      { name: "/trade/swap", desc: "Auto-swap tokens before deposit" },
      { name: "/token-launch/claim-txs/v3", desc: "Claim creator fees directly into vault" },
      { name: "Fee Share V2 (FEE2tBhCK…)", desc: "Distribute creator revenue correctly" },
    ],
  },
  {
    id: "privacy-backend",
    title: "Privacy & Compliance",
    subtitle: "Backend · Off-chain",
    color: "#9945FF",
    icon: Shield,
    components: [
      { name: "ZK Proof Generator", desc: "Noir circuits → Groth16 proofs" },
      { name: "Range Risk API", desc: "Pre-deposit sanctions & illicit flow check" },
      { name: "Commitment Storage", desc: "Client-side secret + nullifier" },
    ],
  },
  {
    id: "relayer",
    title: "Relayer Network",
    subtitle: "Decentralized · Gasless",
    color: "#14F195",
    icon: Zap,
    components: [
      { name: "Proof Submission", desc: "Relayers broadcast user withdrawals" },
      { name: "Gas Coverage", desc: "Users withdraw without owning SOL" },
      { name: "Fee Competition", desc: "0.12% – 0.25% market rates" },
    ],
  },
];

const CIRCUIT = {
  public: [
    { key: "root", desc: "current Merkle tree root" },
    { key: "nullifier_hash", desc: "prevents double-spend" },
    { key: "recipient", desc: "withdrawal destination" },
    { key: "amount", desc: "withdrawal amount" },
  ],
  private: [
    { key: "nullifier", desc: "commitment preimage part 1" },
    { key: "secret", desc: "commitment preimage part 2" },
    { key: "merkle_proof", desc: "path from commitment to root" },
    { key: "is_even", desc: "merkle tree position indicator" },
  ],
};

export default function Architecture() {
  const [phase, setPhase] = useState("deposit");

  return (
    <div className="relative">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-white/5">
        <div className="absolute inset-0 radial-glow pointer-events-none" />
        <div className="absolute inset-0 grid-bg opacity-60 pointer-events-none" />

        <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-12 pb-16">
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
            / system · architecture
          </p>
          <h1 className="font-display font-bold text-4xl lg:text-6xl tracking-tighter max-w-4xl leading-[0.95]">
            Four pillars holding up <span className="solana-text">private creator money.</span>
          </h1>
          <p className="text-zinc-400 mt-6 max-w-2xl text-sm lg:text-base leading-relaxed">
            BagsVault's architecture is designed around one principle: every transaction
            must be verifiable, compliant, and untraceable. Here's how the four layers
            come together, and the exact ZK circuit that makes it possible.
          </p>
        </div>
      </section>

      {/* Pillars Diagram */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-16">
        <div className="grid md:grid-cols-2 gap-4">
          {PILLARS.map((p, i) => (
            <div
              key={p.id}
              data-testid={`pillar-${p.id}`}
              className="relative border border-white/5 bg-[#0A0A0A] p-7 group hover:border-white/20 transition-all overflow-hidden"
            >
              <div
                className="absolute top-0 left-0 w-1 h-full transition-all group-hover:w-full group-hover:opacity-10"
                style={{ background: p.color }}
              />
              <div className="relative flex items-start justify-between mb-6">
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-zinc-500 mb-2">
                    Layer 0{i + 1}
                  </p>
                  <h3 className="font-display text-xl lg:text-2xl">{p.title}</h3>
                  <p className="text-xs text-zinc-500 mt-1 font-mono">{p.subtitle}</p>
                </div>
                <div
                  className="w-11 h-11 border flex items-center justify-center"
                  style={{ borderColor: `${p.color}66`, color: p.color }}
                >
                  <p.icon className="w-5 h-5" />
                </div>
              </div>
              <div className="relative space-y-2">
                {p.components.map((c) => (
                  <div
                    key={c.name}
                    className="border border-white/5 bg-black px-4 py-3 flex items-start gap-3"
                  >
                    <div
                      className="w-1.5 h-1.5 rounded-full mt-2 flex-shrink-0"
                      style={{ background: p.color }}
                    />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white">{c.name}</p>
                      <p className="text-[11px] text-zinc-500 mt-0.5 leading-relaxed">{c.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Flow Visualization */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-16 border-t border-white/5">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-10">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
              — Transaction Flow
            </p>
            <h2 className="font-display font-bold text-3xl lg:text-4xl tracking-tight">
              Two phases, zero links.
            </h2>
          </div>
          <div className="inline-flex border border-white/10">
            <button
              data-testid="phase-deposit"
              onClick={() => setPhase("deposit")}
              className={`px-6 h-11 text-sm font-medium transition-colors ${
                phase === "deposit" ? "bg-white text-black" : "text-zinc-400 hover:text-white"
              }`}
            >
              Phase 1 · Deposit
            </button>
            <button
              data-testid="phase-withdraw"
              onClick={() => setPhase("withdraw")}
              className={`px-6 h-11 text-sm font-medium transition-colors ${
                phase === "withdraw" ? "bg-white text-black" : "text-zinc-400 hover:text-white"
              }`}
            >
              Phase 2 · Withdraw
            </button>
          </div>
        </div>

        {/* Flow Diagram */}
        <div className="border border-white/5 bg-[#0A0A0A] p-6 lg:p-10 relative overflow-hidden">
          <div className="absolute inset-0 mesh-gradient opacity-10 pointer-events-none" />

          {phase === "deposit" ? (
            <DepositFlow />
          ) : (
            <WithdrawFlow />
          )}
        </div>
      </section>

      {/* ZK Circuit Specs */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-16 border-t border-white/5">
        <div className="mb-10">
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#9945FF] mb-3">
            — Cryptography
          </p>
          <h2 className="font-display font-bold text-3xl lg:text-4xl tracking-tight">
            Noir circuit specification.
          </h2>
          <p className="text-zinc-500 mt-3 text-sm max-w-2xl leading-relaxed">
            Written in Noir, compiled to Groth16 for compact on-chain verification.
            Proof size: <span className="text-white font-mono">~200 bytes</span>.
            Avg generation time: <span className="text-white font-mono">1.8s</span>.
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          <div className="border border-[#14F195]/30 bg-[#14F195]/[0.02] p-6">
            <div className="flex items-center gap-2 mb-5">
              <Eye className="w-4 h-4 text-[#14F195]" />
              <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195]">
                Public Inputs
              </p>
            </div>
            <div className="space-y-2">
              {CIRCUIT.public.map((c) => (
                <div key={c.key} className="flex items-start justify-between p-3 bg-black border border-white/5 gap-4">
                  <code className="font-mono text-xs text-[#14F195]">{c.key}</code>
                  <span className="text-xs text-zinc-400 text-right">{c.desc}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border border-[#9945FF]/30 bg-[#9945FF]/[0.02] p-6">
            <div className="flex items-center gap-2 mb-5">
              <Lock className="w-4 h-4 text-[#9945FF]" />
              <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#9945FF]">
                Private Inputs
              </p>
            </div>
            <div className="space-y-2">
              {CIRCUIT.private.map((c) => (
                <div key={c.key} className="flex items-start justify-between p-3 bg-black border border-white/5 gap-4">
                  <code className="font-mono text-xs text-[#9945FF]">{c.key}</code>
                  <span className="text-xs text-zinc-400 text-right">{c.desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-6 border border-white/5 bg-black p-6 font-mono text-xs leading-relaxed overflow-x-auto">
          <p className="text-zinc-600 mb-3 text-[10px] uppercase tracking-[0.2em]">// withdrawal constraint</p>
          <pre className="text-zinc-300 whitespace-pre">
{`fn main(
    // public
    root: pub Field,
    nullifier_hash: pub Field,
    recipient: pub Field,
    amount: pub Field,
    // private
    nullifier: Field,
    secret: Field,
    merkle_proof: [Field; 20],
    is_even: [bool; 20],
) {
    let commitment = hash([nullifier, secret, amount]);
    let computed_root = merkle_root(commitment, merkle_proof, is_even);
    assert(computed_root == root);
    assert(hash([nullifier]) == nullifier_hash);
}`}
          </pre>
        </div>
      </section>

      {/* Tech Stack footer */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-16 border-t border-white/5">
        <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-zinc-500 mb-6">
          — Tech Stack
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-px bg-white/5 border border-white/5">
          {[
            "Solana", "Anchor", "Noir", "Groth16",
            "Sunspot Verifier", "Bags API", "Range Risk", "Phantom",
            "Solflare", "Rust", "TypeScript", "React",
          ].map((s) => (
            <div
              key={s}
              className="bg-black p-5 text-center text-xs font-mono text-zinc-400 hover:text-white hover:bg-white/[0.02] transition-colors"
            >
              {s}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------- FLOW COMPONENTS ---------- */

const FlowNode = ({ icon: Icon, label, sub, color, delay = 0 }) => (
  <div
    className="flex flex-col items-center text-center animate-fade-up min-w-[140px]"
    style={{ animationDelay: `${delay}ms` }}
  >
    <div
      className="w-14 h-14 border-2 flex items-center justify-center bg-black relative"
      style={{ borderColor: color }}
    >
      <Icon className="w-6 h-6" style={{ color }} />
      <span
        className="absolute -inset-1 border opacity-30"
        style={{ borderColor: color }}
      />
    </div>
    <p className="font-medium text-sm mt-3 text-white">{label}</p>
    <p className="text-[10px] font-mono text-zinc-500 mt-1 max-w-[160px]">{sub}</p>
  </div>
);

const FlowArrow = () => (
  <div className="flex-1 min-w-8 flex items-center justify-center relative px-2">
    <div className="w-full h-px bg-gradient-to-r from-[#9945FF]/40 via-[#14F195]/60 to-[#14F195]/40 relative">
      <div className="absolute right-0 top-1/2 -translate-y-1/2 w-2 h-2 border-t border-r border-[#14F195] rotate-45" />
    </div>
  </div>
);

function DepositFlow() {
  return (
    <div className="relative">
      <div className="grid md:flex md:items-center gap-6 md:gap-2 md:overflow-x-auto pb-4">
        <FlowNode icon={Eye} label="User Wallet" sub="source of funds" color="#FFFFFF" delay={0} />
        <FlowArrow />
        <FlowNode icon={Shield} label="Range Risk API" sub="pre-deposit screening" color="#14F195" delay={100} />
        <FlowArrow />
        <FlowNode icon={FileKey} label="Generate Commitment" sub="hash(nullifier, secret, amt)" color="#9945FF" delay={200} />
        <FlowArrow />
        <FlowNode icon={Database} label="BagsVault Program" sub="receive deposit" color="#14F195" delay={300} />
        <FlowArrow />
        <FlowNode icon={GitBranch} label="Merkle Tree" sub="commitment inserted" color="#9945FF" delay={400} />
      </div>
      <div className="mt-10 grid md:grid-cols-4 gap-3 pt-8 border-t border-white/5">
        {[
          ["Step 01", "Source wallet screened for AML risk"],
          ["Step 02", "Client generates secret + nullifier locally"],
          ["Step 03", "Commitment submitted with token amount"],
          ["Step 04", "On-chain Merkle root updates"],
        ].map(([k, v]) => (
          <div key={k} className="border border-white/5 p-4 bg-black">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#14F195] mb-2">{k}</p>
            <p className="text-xs text-zinc-300 leading-relaxed">{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function WithdrawFlow() {
  return (
    <div className="relative">
      <div className="grid md:flex md:items-center gap-6 md:gap-2 md:overflow-x-auto pb-4">
        <FlowNode icon={FileKey} label="Private Note" sub="secret + nullifier" color="#9945FF" delay={0} />
        <FlowArrow />
        <FlowNode icon={Cpu} label="Noir Prover" sub="Groth16 proof" color="#9945FF" delay={100} />
        <FlowArrow />
        <FlowNode icon={Zap} label="Relayer" sub="gasless submission" color="#14F195" delay={200} />
        <FlowArrow />
        <FlowNode icon={Database} label="On-chain Verifier" sub="Sunspot CPI" color="#14F195" delay={300} />
        <FlowArrow />
        <FlowNode icon={Eye} label="Fresh Wallet" sub="anonymous payout" color="#FFFFFF" delay={400} />
      </div>
      <div className="mt-10 grid md:grid-cols-5 gap-3 pt-8 border-t border-white/5">
        {[
          ["Step 01", "User provides secret note + recipient"],
          ["Step 02", "Proof generated client-side"],
          ["Step 03", "Relayer broadcasts proof on-chain"],
          ["Step 04", "Verifier checks proof & nullifier"],
          ["Step 05", "Funds sent to fresh wallet — unlinkable"],
        ].map(([k, v]) => (
          <div key={k} className="border border-white/5 p-4 bg-black">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#9945FF] mb-2">{k}</p>
            <p className="text-xs text-zinc-300 leading-relaxed">{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
