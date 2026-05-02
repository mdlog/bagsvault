import { useState } from "react";
import {
  Cpu, Database, Network, Shield, Lock, FileKey,
  Zap, GitBranch, Eye,
} from "lucide-react";

const PILLARS = [
  {
    id: "smart-contract",
    title: "Smart contract layer",
    subtitle: "Solana · Anchor",
    icon: Database,
    components: [
      { name: "BagsVault Program", desc: "Receives deposits, verifies proofs, executes withdrawals" },
      { name: "Merkle tree state", desc: "Stores 10 most recent commitment roots" },
      { name: "Nullifier set", desc: "Prevents double-spending of commitments" },
      { name: "Groth16 verifier", desc: "CPI to Sunspot Verifier Program" },
    ],
  },
  {
    id: "bags-api",
    title: "Bags API layer",
    subtitle: "Native integration",
    icon: Network,
    components: [
      { name: "/trade/swap", desc: "Auto-swap tokens before deposit" },
      { name: "/token-launch/claim-txs/v3", desc: "Claim creator fees directly into vault" },
      { name: "Fee Share V2 (FEE2tBhCK…)", desc: "Distribute creator revenue correctly" },
    ],
  },
  {
    id: "privacy-backend",
    title: "Privacy & compliance",
    subtitle: "Backend · Off-chain",
    icon: Shield,
    components: [
      { name: "ZK proof generator", desc: "Noir circuits → Groth16 proofs" },
      { name: "Range Risk API", desc: "Pre-deposit sanctions & illicit flow check" },
      { name: "Commitment storage", desc: "Client-side secret + nullifier" },
    ],
  },
  {
    id: "relayer",
    title: "Relayer network",
    subtitle: "Decentralized · Gasless",
    icon: Zap,
    components: [
      { name: "Proof submission", desc: "Relayers broadcast user withdrawals" },
      { name: "Gas coverage", desc: "Users withdraw without owning SOL" },
      { name: "Fee competition", desc: "0.12% – 0.25% market rates" },
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
    <div>
      {/* Hero */}
      <section className="border-b border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-12 pb-12">
          <p className="text-xs font-medium text-[#14F195] mb-2">System · Architecture</p>
          <h1 className="text-3xl lg:text-4xl font-semibold tracking-tight max-w-3xl leading-[1.1]">
            Four pillars holding up <span className="text-[#14F195]">private creator money.</span>
          </h1>
          <p className="text-zinc-400 mt-4 max-w-2xl text-sm lg:text-base leading-relaxed">
            BagsVault's architecture is designed around one principle: every transaction
            must be verifiable, compliant, and untraceable. Here's how the four layers
            come together, and the exact ZK circuit that makes it possible.
          </p>
        </div>
      </section>

      {/* Pillars */}
      <section className="max-w-[1280px] mx-auto px-6 lg:px-8 py-14">
        <div className="grid md:grid-cols-2 gap-3">
          {PILLARS.map((p, i) => (
            <div
              key={p.id}
              data-testid={`pillar-${p.id}`}
              className="border border-white/5 bg-[#0a0b0d] p-6 rounded-md hover:border-white/15 transition-colors"
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <p className="text-xs text-zinc-500 mb-1">Layer 0{i + 1}</p>
                  <h3 className="text-base lg:text-lg font-semibold">{p.title}</h3>
                  <p className="text-xs text-zinc-500 mt-0.5">{p.subtitle}</p>
                </div>
                <div className="w-10 h-10 rounded-md bg-[#14F195]/10 border border-[#14F195]/30 text-[#14F195] flex items-center justify-center">
                  <p.icon className="w-4 h-4" />
                </div>
              </div>
              <div className="space-y-2">
                {p.components.map((c) => (
                  <div
                    key={c.name}
                    className="border border-white/5 bg-[#07080a] rounded-md px-3.5 py-2.5 flex items-start gap-3"
                  >
                    <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 bg-[#14F195]" />
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

      {/* Flow */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-14">
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-8">
            <div>
              <p className="text-xs font-medium text-[#14F195] mb-2">Transaction flow</p>
              <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight">
                Two phases, zero links.
              </h2>
            </div>
            <div className="inline-flex border border-white/10 rounded-md overflow-hidden">
              <button
                data-testid="phase-deposit"
                onClick={() => setPhase("deposit")}
                className={`px-4 h-10 text-sm font-medium transition-colors ${
                  phase === "deposit" ? "bg-white text-black" : "text-zinc-400 hover:text-white"
                }`}
              >
                Phase 1 · Deposit
              </button>
              <button
                data-testid="phase-withdraw"
                onClick={() => setPhase("withdraw")}
                className={`px-4 h-10 text-sm font-medium transition-colors ${
                  phase === "withdraw" ? "bg-white text-black" : "text-zinc-400 hover:text-white"
                }`}
              >
                Phase 2 · Withdraw
              </button>
            </div>
          </div>

          <div className="border border-white/5 bg-[#0a0b0d] p-6 lg:p-8 rounded-md">
            {phase === "deposit" ? <DepositFlow /> : <WithdrawFlow />}
          </div>
        </div>
      </section>

      {/* Circuit */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-14">
          <div className="mb-8">
            <p className="text-xs font-medium text-[#14F195] mb-2">Cryptography</p>
            <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight">
              Noir circuit specification.
            </h2>
            <p className="text-zinc-500 mt-3 text-sm max-w-2xl leading-relaxed">
              Written in Noir, compiled to Groth16 for compact on-chain verification.
              Proof size: <span className="text-white font-mono">~200 bytes</span>.
              Avg generation time: <span className="text-white font-mono">1.8s</span>.
            </p>
          </div>

          <div className="grid lg:grid-cols-2 gap-3">
            <div className="border border-white/5 bg-[#0a0b0d] rounded-md p-5">
              <div className="flex items-center gap-2 mb-4">
                <Eye className="w-4 h-4 text-[#14F195]" />
                <p className="text-xs font-medium text-zinc-300">Public inputs</p>
              </div>
              <div className="space-y-2">
                {CIRCUIT.public.map((c) => (
                  <div key={c.key} className="flex items-start justify-between p-3 bg-[#07080a] border border-white/5 rounded-md gap-4">
                    <code className="font-mono text-xs text-[#14F195]">{c.key}</code>
                    <span className="text-xs text-zinc-400 text-right">{c.desc}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border border-white/5 bg-[#0a0b0d] rounded-md p-5">
              <div className="flex items-center gap-2 mb-4">
                <Lock className="w-4 h-4 text-zinc-400" />
                <p className="text-xs font-medium text-zinc-300">Private inputs</p>
              </div>
              <div className="space-y-2">
                {CIRCUIT.private.map((c) => (
                  <div key={c.key} className="flex items-start justify-between p-3 bg-[#07080a] border border-white/5 rounded-md gap-4">
                    <code className="font-mono text-xs text-zinc-300">{c.key}</code>
                    <span className="text-xs text-zinc-400 text-right">{c.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-3 border border-white/5 bg-[#07080a] rounded-md p-5 font-mono text-xs leading-relaxed overflow-x-auto">
            <p className="text-zinc-600 mb-3 text-[11px]">// withdrawal constraint</p>
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
        </div>
      </section>

      {/* Tech Stack */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-14">
          <p className="text-xs font-medium text-zinc-300 mb-4">Tech stack</p>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
            {[
              "Solana", "Anchor", "Noir", "Groth16",
              "Sunspot Verifier", "Bags API", "Range Risk", "Phantom",
              "Solflare", "Rust", "TypeScript", "React",
            ].map((s) => (
              <div
                key={s}
                className="bg-[#0a0b0d] border border-white/5 rounded-md p-4 text-center text-xs text-zinc-400 hover:text-white hover:border-white/15 transition-colors"
              >
                {s}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------- FLOW COMPONENTS ---------- */

const FlowNode = ({ icon: Icon, label, sub }) => (
  <div className="flex flex-col items-center text-center min-w-[140px]">
    <div className="w-12 h-12 border border-[#14F195]/40 bg-[#14F195]/[0.05] rounded-md flex items-center justify-center">
      <Icon className="w-5 h-5 text-[#14F195]" />
    </div>
    <p className="font-medium text-sm mt-2.5 text-white">{label}</p>
    <p className="text-[11px] text-zinc-500 mt-0.5 max-w-[160px]">{sub}</p>
  </div>
);

const FlowArrow = () => (
  <div className="flex-1 min-w-8 flex items-center justify-center px-2">
    <div className="w-full h-px bg-white/15 relative">
      <div className="absolute right-0 top-1/2 -translate-y-1/2 w-1.5 h-1.5 border-t border-r border-white/40 rotate-45" />
    </div>
  </div>
);

function DepositFlow() {
  return (
    <div>
      <div className="grid md:flex md:items-center gap-5 md:gap-2 md:overflow-x-auto pb-2">
        <FlowNode icon={Eye} label="User wallet" sub="source of funds" />
        <FlowArrow />
        <FlowNode icon={Shield} label="Range Risk API" sub="pre-deposit screening" />
        <FlowArrow />
        <FlowNode icon={FileKey} label="Generate commitment" sub="hash(nullifier, secret, amt)" />
        <FlowArrow />
        <FlowNode icon={Database} label="BagsVault Program" sub="receive deposit" />
        <FlowArrow />
        <FlowNode icon={GitBranch} label="Merkle tree" sub="commitment inserted" />
      </div>
      <div className="mt-8 grid md:grid-cols-4 gap-2 pt-6 border-t border-white/5">
        {[
          ["Step 01", "Source wallet screened for AML risk"],
          ["Step 02", "Client generates secret + nullifier locally"],
          ["Step 03", "Commitment submitted with token amount"],
          ["Step 04", "On-chain Merkle root updates"],
        ].map(([k, v]) => (
          <div key={k} className="border border-white/5 rounded-md p-3.5 bg-[#07080a]">
            <p className="text-[11px] font-medium text-[#14F195] mb-1.5">{k}</p>
            <p className="text-xs text-zinc-300 leading-relaxed">{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function WithdrawFlow() {
  return (
    <div>
      <div className="grid md:flex md:items-center gap-5 md:gap-2 md:overflow-x-auto pb-2">
        <FlowNode icon={FileKey} label="Private note" sub="secret + nullifier" />
        <FlowArrow />
        <FlowNode icon={Cpu} label="Noir prover" sub="Groth16 proof" />
        <FlowArrow />
        <FlowNode icon={Zap} label="Relayer" sub="gasless submission" />
        <FlowArrow />
        <FlowNode icon={Database} label="On-chain verifier" sub="Sunspot CPI" />
        <FlowArrow />
        <FlowNode icon={Eye} label="Fresh wallet" sub="anonymous payout" />
      </div>
      <div className="mt-8 grid md:grid-cols-5 gap-2 pt-6 border-t border-white/5">
        {[
          ["Step 01", "User provides secret note + recipient"],
          ["Step 02", "Proof generated client-side"],
          ["Step 03", "Relayer broadcasts proof on-chain"],
          ["Step 04", "Verifier checks proof & nullifier"],
          ["Step 05", "Funds sent to fresh wallet — unlinkable"],
        ].map(([k, v]) => (
          <div key={k} className="border border-white/5 rounded-md p-3.5 bg-[#07080a]">
            <p className="text-[11px] font-medium text-[#14F195] mb-1.5">{k}</p>
            <p className="text-xs text-zinc-300 leading-relaxed">{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
