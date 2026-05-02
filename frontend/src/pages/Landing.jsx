import { Link } from "react-router-dom";
import {
  Shield,
  Lock,
  Zap,
  Network,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Cpu,
  FileKey,
  Layers,
} from "lucide-react";

const Stat = ({ label, value, suffix, accent }) => (
  <div className="border border-white/5 bg-black p-6 group hover:border-white/20 transition-colors">
    <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">{label}</p>
    <p className={`font-display font-bold text-3xl lg:text-4xl mt-3 ${accent || "text-white"}`}>
      {value}
      {suffix && <span className="text-zinc-500 text-xl ml-1">{suffix}</span>}
    </p>
  </div>
);

const FeatureCard = ({ icon: Icon, title, desc, accent, span = "md:col-span-4" }) => (
  <div
    className={`${span} border border-white/5 bg-[#0A0A0A] p-8 relative overflow-hidden group hover:border-white/20 transition-all`}
  >
    <div className={`w-10 h-10 flex items-center justify-center mb-6 border ${accent}`}>
      <Icon className="w-5 h-5" />
    </div>
    <h3 className="font-display text-xl lg:text-2xl mb-3">{title}</h3>
    <p className="text-zinc-500 text-sm leading-relaxed">{desc}</p>
    <div className="absolute -bottom-8 -right-8 w-40 h-40 bg-gradient-radial from-white/[0.03] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
  </div>
);

const FlowStep = ({ n, title, desc, mono, accent }) => (
  <div className="flex gap-6 relative">
    <div className="flex flex-col items-center">
      <div className={`w-11 h-11 border flex items-center justify-center font-mono font-bold ${accent}`}>
        {n}
      </div>
      <div className="w-px flex-1 bg-white/5 mt-3" />
    </div>
    <div className="pb-14 flex-1">
      <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-1">Step {n}</p>
      <h4 className="font-display text-lg lg:text-xl text-white">{title}</h4>
      <p className="text-zinc-500 text-sm mt-2 leading-relaxed max-w-lg">{desc}</p>
      {mono && (
        <code className="block mt-3 font-mono text-[11px] text-zinc-600 bg-black border border-white/5 px-3 py-2">
          {mono}
        </code>
      )}
    </div>
  </div>
);

export default function Landing() {
  return (
    <div>
      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 radial-glow pointer-events-none" />
        <div className="absolute inset-0 grid-bg opacity-60 pointer-events-none" />

        <div className="relative max-w-[1400px] mx-auto px-6 lg:px-10 pt-20 lg:pt-32 pb-24">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 border border-white/10 bg-black/40 backdrop-blur-md">
            <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full pulse-glow" />
            <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-zinc-400">
              Bags Hackathon · Privacy Track
            </span>
          </div>

          <h1 className="font-display font-bold text-5xl sm:text-6xl lg:text-7xl xl:text-8xl mt-6 max-w-5xl leading-[0.95] tracking-tighter">
            Private earnings for{" "}
            <span className="solana-text">Bags creators.</span>
          </h1>

          <p className="text-zinc-400 text-lg lg:text-xl mt-8 max-w-2xl leading-relaxed">
            BagsVault is a zero-knowledge privacy protocol on Solana. Claim creator
            fees, accept donations, and move tokens without exposing your wallet —
            secured by Noir ZK-SNARKs and compliance-aware from deposit to payout.
          </p>

          <div className="flex flex-wrap items-center gap-3 mt-10">
            <Link
              to="/deposit"
              data-testid="hero-launch-app-btn"
              className="inline-flex items-center gap-2 bg-white text-black h-12 px-7 font-semibold hover:bg-zinc-200 transition-colors group"
            >
              Launch App
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>
            <Link
              to="/architecture"
              data-testid="hero-architecture-btn"
              className="inline-flex items-center gap-2 h-12 px-7 border border-white/15 text-white hover:bg-white/5 transition-colors font-medium"
            >
              <Layers className="w-4 h-4" /> View Architecture
            </Link>
            <div className="hidden sm:flex items-center gap-2 h-12 px-4 border border-[#14F195]/20 text-[#14F195] font-mono text-xs">
              <CheckCircle2 className="w-4 h-4" /> Audited Circuits
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-white/5 border border-white/5 mt-20">
            <Stat label="Anonymity Set" value="47,129" accent="text-white" />
            <Stat label="Total Protected" value="1.2M" suffix="SOL" accent="solana-text" />
            <Stat label="Active Relayers" value="23" accent="text-[#14F195]" />
            <Stat label="Creators Onboarded" value="8,412" accent="text-white" />
          </div>
        </div>
      </section>

      {/* BENTO FEATURES */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-24">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 mb-12">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
              — Protocol Pillars
            </p>
            <h2 className="font-display font-bold text-4xl lg:text-5xl max-w-xl tracking-tight">
              Four layers. One private creator economy.
            </h2>
          </div>
          <p className="text-zinc-500 max-w-md text-sm leading-relaxed">
            Every BagsVault transaction is validated by an on-chain Groth16 verifier,
            pre-screened by Range Risk, and paid out gaslessly by our relayer network.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-8 lg:grid-cols-12 gap-4">
          <FeatureCard
            icon={Lock}
            title="Zero-Knowledge Commitments"
            desc="Every deposit is hashed into a commitment stored in an on-chain Merkle Tree. Your identity is mathematically decoupled from your withdrawal."
            accent="border-[#9945FF]/40 text-[#9945FF]"
            span="md:col-span-4 lg:col-span-6"
          />
          <FeatureCard
            icon={Shield}
            title="Compliance-Aware"
            desc="Integrated Range Risk API screens every deposit for sanctions, hacks, and illicit flows before funds enter the privacy pool."
            accent="border-[#14F195]/40 text-[#14F195]"
            span="md:col-span-4 lg:col-span-6"
          />
          <FeatureCard
            icon={Network}
            title="Bags API Native"
            desc="Claim creator fees through /token-launch/claim-txs/v3 and auto-swap via /trade/swap — directly into the vault."
            accent="border-white/20 text-white"
            span="md:col-span-4 lg:col-span-4"
          />
          <FeatureCard
            icon={Zap}
            title="Gasless Relayers"
            desc="Withdraw to a fresh wallet without paying gas. Relayers cover fees and earn a small protocol share."
            accent="border-[#14F195]/40 text-[#14F195]"
            span="md:col-span-4 lg:col-span-4"
          />
          <FeatureCard
            icon={Cpu}
            title="Noir + Groth16"
            desc="Compact ZK proofs generated client-side, verified on-chain through Sunspot Verifier CPI. Sub-second proof times."
            accent="border-[#9945FF]/40 text-[#9945FF]"
            span="md:col-span-4 lg:col-span-4"
          />
        </div>
      </section>

      {/* PRIVACY SWITCH SECTION */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-24 border-t border-white/5">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
              — The Problem
            </p>
            <h2 className="font-display font-bold text-4xl lg:text-5xl tracking-tight leading-tight">
              Your public wallet is a public spreadsheet.
            </h2>
            <p className="text-zinc-400 text-base lg:text-lg mt-6 leading-relaxed max-w-lg">
              On Solana, every creator fee, donation, and token swap is forever
              visible. Competitors, stalkers, and scrapers can map your entire
              income. BagsVault breaks that chain using cryptography, not promises.
            </p>
            <ul className="mt-8 space-y-4 text-sm">
              {[
                "Receive tips and fees to a stealth identity",
                "Move tokens between wallets without a traceable link",
                "Maintain public proof of compliance without KYC",
                "Compatible with Phantom, Solflare & Bags wallet",
              ].map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-[#14F195] flex-shrink-0 mt-0.5" />
                  <span className="text-zinc-300">{t}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="relative border border-white/10 bg-gradient-to-br from-black to-[#0a0a0a] p-8">
            <div className="flex items-center justify-between mb-8">
              <div>
                <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">
                  Wallet Transparency
                </p>
                <p className="font-display text-2xl mt-1">Compare</p>
              </div>
              <div className="flex items-center gap-2 text-xs font-mono text-zinc-500">
                <Eye className="w-3.5 h-3.5" />
                public ledger
              </div>
            </div>

            {/* Public wallet */}
            <div className="border border-white/5 p-5 space-y-3 mb-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-500">Public wallet</span>
                <span className="font-mono text-[11px] text-red-400">EXPOSED</span>
              </div>
              {[
                ["+ 1,240 BAGS", "from @fan42"],
                ["+ 0.85 SOL", "creator fee"],
                ["- 500 BAGS", "to @rival.sol"],
                ["+ 12.3 SOL", "tip"],
              ].map(([a, b], i) => (
                <div key={i} className="flex items-center justify-between font-mono text-xs">
                  <span className={a.startsWith("+") ? "text-[#14F195]" : "text-red-400"}>
                    {a}
                  </span>
                  <span className="text-zinc-600">{b}</span>
                </div>
              ))}
            </div>

            {/* BagsVault wallet */}
            <div className="border border-[#14F195]/30 bg-[#14F195]/[0.03] p-5 space-y-3 relative">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#14F195] flex items-center gap-1.5">
                  <EyeOff className="w-3.5 h-3.5" /> BagsVault wallet
                </span>
                <span className="font-mono text-[11px] text-[#14F195]">PRIVATE</span>
              </div>
              {[
                ["0x•••••••••", "commitment 0x7a…c9"],
                ["0x•••••••••", "commitment 0x3b…a1"],
                ["0x•••••••••", "commitment 0xd2…87"],
                ["0x•••••••••", "commitment 0xe4…ff"],
              ].map(([a, b], i) => (
                <div key={i} className="flex items-center justify-between font-mono text-xs">
                  <span className="text-white">{a}</span>
                  <span className="text-zinc-600">{b}</span>
                </div>
              ))}
              <div className="pt-3 border-t border-white/5 flex items-center justify-between text-[10px] font-mono">
                <span className="text-zinc-500">anonymity set</span>
                <span className="text-[#14F195]">1 of 47,129</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-24 border-t border-white/5">
        <div className="grid lg:grid-cols-3 gap-12">
          <div className="lg:col-span-1">
            <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
              — How It Works
            </p>
            <h2 className="font-display font-bold text-4xl lg:text-5xl tracking-tight leading-tight">
              From deposit to anonymous payout.
            </h2>
            <p className="text-zinc-500 text-sm mt-6 leading-relaxed">
              Two phases decouple sender from recipient on-chain. Your secret note
              is the only link — and only you hold it.
            </p>
            <Link
              to="/architecture"
              className="inline-flex items-center gap-2 mt-8 text-[#14F195] font-mono text-xs uppercase tracking-[0.2em] hover:translate-x-1 transition-transform"
            >
              Full architecture <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="lg:col-span-2">
            <FlowStep
              n="01"
              title="Pre-Deposit Risk Check"
              desc="Your source wallet is screened via Range Risk API for sanctions, hacks, and illicit flows. Clean wallets proceed; flagged ones are blocked before funds enter the pool."
              accent="border-[#9945FF]/40 text-[#9945FF]"
            />
            <FlowStep
              n="02"
              title="Generate Commitment"
              desc="Client-side, you generate a secret + nullifier. We compute a commitment hash and send it on-chain as your deposit receipt."
              mono="commitment = hash(nullifier, secret, amount)"
              accent="border-[#14F195]/40 text-[#14F195]"
            />
            <FlowStep
              n="03"
              title="Merkle Tree Update"
              desc="Your commitment is inserted into the BagsVault Merkle Tree. The on-chain root updates — adding you to the anonymity set."
              accent="border-white/20 text-white"
            />
            <FlowStep
              n="04"
              title="ZK-Proof Withdrawal"
              desc="To withdraw, paste your note. A Groth16 proof is generated in-browser proving you own a valid commitment, without revealing which one."
              mono="proof = Noir.prove(secret, nullifier, merkle_path)"
              accent="border-[#9945FF]/40 text-[#9945FF]"
            />
            <div className="flex gap-6">
              <div className="w-11 h-11 border border-[#14F195]/40 text-[#14F195] flex items-center justify-center font-mono font-bold">
                05
              </div>
              <div className="flex-1">
                <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 mb-1">Step 05</p>
                <h4 className="font-display text-lg lg:text-xl text-white">Gasless Payout</h4>
                <p className="text-zinc-500 text-sm mt-2 leading-relaxed max-w-lg">
                  A relayer submits your transaction. Funds land in a fresh wallet —
                  with zero on-chain link to the original deposit.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="relative max-w-[1400px] mx-auto px-6 lg:px-10 py-24">
        <div className="relative border border-white/10 bg-gradient-to-br from-[#0A0A0A] via-black to-[#0A0A0A] p-10 lg:p-16 overflow-hidden">
          <div className="absolute inset-0 mesh-gradient opacity-30 pointer-events-none" />
          <div className="relative z-10 grid lg:grid-cols-2 gap-10 items-center">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#14F195] mb-3">
                — Ready to disappear?
              </p>
              <h2 className="font-display font-bold text-4xl lg:text-5xl tracking-tight leading-tight">
                Start claiming fees <br /> privately today.
              </h2>
              <p className="text-zinc-400 mt-6 max-w-md text-base lg:text-lg leading-relaxed">
                No KYC. No leaks. Just cryptography doing what it does best.
              </p>
              <div className="flex flex-wrap gap-3 mt-8">
                <Link
                  to="/deposit"
                  data-testid="cta-deposit-btn"
                  className="inline-flex items-center gap-2 bg-white text-black h-12 px-7 font-semibold hover:bg-zinc-200 transition-colors"
                >
                  Deposit Now <ArrowRight className="w-4 h-4" />
                </Link>
                <Link
                  to="/compliance"
                  className="inline-flex items-center gap-2 h-12 px-7 border border-white/15 hover:bg-white/5 font-medium"
                >
                  Run Compliance Check
                </Link>
              </div>
            </div>

            <div className="relative">
              <div className="border border-white/10 bg-black p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">
                    Live Anonymity Set
                  </span>
                  <FileKey className="w-4 h-4 text-[#14F195]" />
                </div>
                <div className="grid grid-cols-7 gap-1.5">
                  {Array.from({ length: 49 }).map((_, i) => (
                    <div
                      key={i}
                      className={`aspect-square border ${
                        i % 7 === 0
                          ? "bg-[#14F195]/20 border-[#14F195]/50"
                          : i % 5 === 0
                          ? "bg-[#9945FF]/15 border-[#9945FF]/40"
                          : "border-white/10 bg-white/[0.02]"
                      }`}
                    />
                  ))}
                </div>
                <div className="flex items-center justify-between text-xs font-mono pt-3 border-t border-white/5">
                  <span className="text-zinc-500">current root</span>
                  <span className="text-white">0x7a3f…c9e1</span>
                </div>
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-zinc-500">commitments</span>
                  <span className="text-[#14F195]">47,129</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
