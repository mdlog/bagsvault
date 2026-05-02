import { Link } from "react-router-dom";
import { useWallet } from "@/context/WalletContext";
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
  LayoutDashboard,
} from "lucide-react";

const Stat = ({ label, value, suffix }) => (
  <div className="border border-white/5 bg-[#0a0b0d] p-5 rounded-md">
    <p className="text-xs text-zinc-500">{label}</p>
    <p className="text-2xl font-semibold text-white mt-1.5 tracking-tight">
      {value}
      {suffix && <span className="text-zinc-500 text-base font-normal ml-1">{suffix}</span>}
    </p>
  </div>
);

const FeatureCard = ({ icon: Icon, title, desc }) => (
  <div className="border border-white/5 bg-[#0a0b0d] p-6 rounded-md hover:border-white/15 transition-colors">
    <div className="w-9 h-9 flex items-center justify-center rounded-md bg-[#14F195]/10 border border-[#14F195]/30 text-[#14F195] mb-4">
      <Icon className="w-4 h-4" />
    </div>
    <h3 className="text-base font-semibold text-white">{title}</h3>
    <p className="text-zinc-500 text-sm mt-2 leading-relaxed">{desc}</p>
  </div>
);

const FlowStep = ({ n, title, desc, mono }) => (
  <div className="flex gap-5 relative">
    <div className="flex flex-col items-center">
      <div className="w-9 h-9 border border-white/10 bg-[#0a0b0d] rounded-md flex items-center justify-center font-mono text-xs text-zinc-300">
        {n}
      </div>
      <div className="w-px flex-1 bg-white/5 mt-2" />
    </div>
    <div className="pb-10 flex-1">
      <h4 className="text-base font-semibold text-white">{title}</h4>
      <p className="text-zinc-500 text-sm mt-1.5 leading-relaxed max-w-lg">{desc}</p>
      {mono && (
        <code className="block mt-3 font-mono text-[11px] text-zinc-500 bg-[#0a0b0d] border border-white/5 rounded px-3 py-2">
          {mono}
        </code>
      )}
    </div>
  </div>
);

export default function Landing() {
  const { wallet, connect } = useWallet();
  // When the user is already connected, route the primary CTA to their
  // dashboard so the landing page degrades gracefully into a brief
  // marketing surface — no need to re-pitch the protocol.
  const primaryCtaTo = wallet ? "/dashboard" : "/deposit";
  const primaryCtaLabel = wallet ? "Open dashboard" : "Launch app";
  const primaryCtaIcon = wallet ? LayoutDashboard : ArrowRight;
  const PrimaryIcon = primaryCtaIcon;

  return (
    <div>
      {/* HERO */}
      <section className="relative">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 pt-20 lg:pt-28 pb-20">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 border border-white/10 bg-[#0c0d10] rounded-full">
            <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
            <span className="text-[11px] font-mono text-zinc-400">
              Bags Hackathon · Privacy track
            </span>
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold mt-6 max-w-4xl leading-[1.05] tracking-tight">
            Private earnings for{" "}
            <span className="text-[#14F195]">Bags creators.</span>
          </h1>

          <p className="text-zinc-400 text-base lg:text-lg mt-6 max-w-2xl leading-relaxed">
            BagsVault is a zero-knowledge privacy protocol on Solana. Claim creator
            fees, accept donations, and move tokens without exposing your wallet —
            secured by Noir ZK-SNARKs and compliance-aware from deposit to payout.
          </p>

          <div className="flex flex-wrap items-center gap-3 mt-8">
            <Link
              to={primaryCtaTo}
              data-testid="hero-launch-app-btn"
              className="inline-flex items-center gap-2 bg-white text-black h-10 px-5 rounded-md text-sm font-medium hover:bg-zinc-200 transition-colors"
            >
              {primaryCtaLabel}
              <PrimaryIcon className="w-4 h-4" />
            </Link>
            {!wallet && (
              <button
                onClick={() => connect()}
                data-testid="hero-connect-btn"
                className="inline-flex items-center gap-2 h-10 px-5 rounded-md border border-[#14F195]/40 text-[#14F195] hover:bg-[#14F195]/[0.05] transition-colors text-sm font-medium"
              >
                Connect wallet
              </button>
            )}
            <Link
              to="/architecture"
              data-testid="hero-architecture-btn"
              className="inline-flex items-center gap-2 h-10 px-5 rounded-md border border-white/15 text-white hover:bg-white/[0.04] transition-colors text-sm font-medium"
            >
              View architecture
            </Link>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-16">
            <Stat label="Anonymity set" value="47,129" />
            <Stat label="Total protected" value="1.2M" suffix="SOL" />
            <Stat label="Active relayers" value="23" />
            <Stat label="Creators onboarded" value="8,412" />
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-20">
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 mb-10">
            <div>
              <p className="text-xs font-medium text-[#14F195] mb-2">Protocol pillars</p>
              <h2 className="text-2xl lg:text-3xl font-semibold max-w-xl tracking-tight">
                Four layers. One private creator economy.
              </h2>
            </div>
            <p className="text-zinc-500 max-w-md text-sm leading-relaxed">
              Every BagsVault transaction is validated by an on-chain Groth16 verifier,
              pre-screened by Range Risk, and paid out gaslessly by our relayer network.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <FeatureCard
              icon={Lock}
              title="Zero-knowledge commitments"
              desc="Every deposit is hashed into a commitment stored in an on-chain Merkle tree. Your identity is mathematically decoupled from your withdrawal."
            />
            <FeatureCard
              icon={Shield}
              title="Compliance-aware"
              desc="Integrated Range Risk API screens every deposit for sanctions, hacks, and illicit flows before funds enter the privacy pool."
            />
            <FeatureCard
              icon={Network}
              title="Bags API native"
              desc="Claim creator fees through /token-launch/claim-txs/v3 and auto-swap via /trade/swap — directly into the vault."
            />
            <FeatureCard
              icon={Zap}
              title="Gasless relayers"
              desc="Withdraw to a fresh wallet without paying gas. Relayers cover fees and earn a small protocol share."
            />
            <FeatureCard
              icon={Cpu}
              title="Noir + Groth16"
              desc="Compact ZK proofs generated client-side, verified on-chain through the Sunspot Verifier CPI. Sub-second proof times."
            />
            <FeatureCard
              icon={FileKey}
              title="Self-custodial notes"
              desc="Only you hold the secret note that unlocks your deposit. BagsVault never stores or relays your private inputs."
            />
          </div>
        </div>
      </section>

      {/* COMPARISON */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-20">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div>
              <p className="text-xs font-medium text-[#14F195] mb-2">The problem</p>
              <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight leading-tight">
                Your public wallet is a public spreadsheet.
              </h2>
              <p className="text-zinc-400 text-sm lg:text-base mt-4 leading-relaxed max-w-lg">
                On Solana, every creator fee, donation, and token swap is forever
                visible. Competitors, stalkers, and scrapers can map your entire
                income. BagsVault breaks that chain using cryptography, not promises.
              </p>
              <ul className="mt-6 space-y-3 text-sm">
                {[
                  "Receive tips and fees to a stealth identity",
                  "Move tokens between wallets without a traceable link",
                  "Maintain public proof of compliance without KYC",
                  "Compatible with Phantom, Solflare & Bags wallet",
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2.5">
                    <CheckCircle2 className="w-4 h-4 text-[#14F195] flex-shrink-0 mt-0.5" />
                    <span className="text-zinc-300">{t}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="border border-white/10 bg-[#0a0b0d] p-6 rounded-md">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <p className="text-xs text-zinc-500">Wallet transparency</p>
                  <p className="text-base font-semibold mt-0.5">Compare</p>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <Eye className="w-3.5 h-3.5" />
                  public ledger
                </div>
              </div>

              <div className="border border-white/5 rounded-md p-4 space-y-2.5 mb-3 bg-[#07080a]">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-zinc-400">Public wallet</span>
                  <span className="font-mono text-[10px] text-red-400">EXPOSED</span>
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

              <div className="border border-[#14F195]/30 bg-[#14F195]/[0.04] rounded-md p-4 space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-[#14F195] flex items-center gap-1.5">
                    <EyeOff className="w-3.5 h-3.5" /> BagsVault wallet
                  </span>
                  <span className="font-mono text-[10px] text-[#14F195]">PRIVATE</span>
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
                <div className="pt-2.5 border-t border-white/5 flex items-center justify-between text-xs font-mono">
                  <span className="text-zinc-500">anonymity set</span>
                  <span className="text-[#14F195]">1 of 47,129</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-20">
          <div className="grid lg:grid-cols-3 gap-10">
            <div className="lg:col-span-1">
              <p className="text-xs font-medium text-[#14F195] mb-2">How it works</p>
              <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight leading-tight">
                From deposit to anonymous payout.
              </h2>
              <p className="text-zinc-500 text-sm mt-4 leading-relaxed">
                Two phases decouple sender from recipient on-chain. Your secret note
                is the only link — and only you hold it.
              </p>
              <Link
                to="/architecture"
                className="inline-flex items-center gap-1.5 mt-6 text-[#14F195] text-sm hover:gap-2 transition-all"
              >
                Full architecture <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="lg:col-span-2">
              <FlowStep
                n="01"
                title="Pre-deposit risk check"
                desc="Your source wallet is screened via Range Risk API for sanctions, hacks, and illicit flows. Clean wallets proceed; flagged ones are blocked before funds enter the pool."
              />
              <FlowStep
                n="02"
                title="Generate commitment"
                desc="Client-side, you generate a secret + nullifier. We compute a commitment hash and send it on-chain as your deposit receipt."
                mono="commitment = hash(nullifier, secret, amount)"
              />
              <FlowStep
                n="03"
                title="Merkle tree update"
                desc="Your commitment is inserted into the BagsVault Merkle tree. The on-chain root updates — adding you to the anonymity set."
              />
              <FlowStep
                n="04"
                title="ZK-proof withdrawal"
                desc="To withdraw, paste your note. A Groth16 proof is generated in-browser proving you own a valid commitment, without revealing which one."
                mono="proof = Noir.prove(secret, nullifier, merkle_path)"
              />
              <div className="flex gap-5">
                <div className="w-9 h-9 border border-white/10 bg-[#0a0b0d] rounded-md flex items-center justify-center font-mono text-xs text-zinc-300">
                  05
                </div>
                <div className="flex-1">
                  <h4 className="text-base font-semibold text-white">Gasless payout</h4>
                  <p className="text-zinc-500 text-sm mt-1.5 leading-relaxed max-w-lg">
                    A relayer submits your transaction. Funds land in a fresh wallet —
                    with zero on-chain link to the original deposit.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="border-t border-white/5">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-20">
          <div className="border border-white/10 bg-[#0a0b0d] rounded-md p-8 lg:p-12">
            <div className="grid lg:grid-cols-2 gap-10 items-center">
              <div>
                <p className="text-xs font-medium text-[#14F195] mb-2">Ready to disappear?</p>
                <h2 className="text-2xl lg:text-3xl font-semibold tracking-tight leading-tight">
                  Start claiming fees privately today.
                </h2>
                <p className="text-zinc-400 mt-4 max-w-md text-sm lg:text-base leading-relaxed">
                  No KYC. No leaks. Just cryptography doing what it does best.
                </p>
                <div className="flex flex-wrap gap-3 mt-6">
                  <Link
                    to={primaryCtaTo}
                    data-testid="cta-deposit-btn"
                    className="inline-flex items-center gap-2 bg-white text-black h-10 px-5 rounded-md text-sm font-medium hover:bg-zinc-200 transition-colors"
                  >
                    {wallet ? "Open dashboard" : "Deposit now"}{" "}
                    <ArrowRight className="w-4 h-4" />
                  </Link>
                  <Link
                    to="/compliance"
                    className="inline-flex items-center gap-2 h-10 px-5 rounded-md border border-white/15 hover:bg-white/[0.04] text-sm font-medium"
                  >
                    Run compliance check
                  </Link>
                </div>
              </div>

              <div>
                <div className="border border-white/10 bg-[#07080a] rounded-md p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-zinc-500">Live anonymity set</span>
                    <FileKey className="w-3.5 h-3.5 text-[#14F195]" />
                  </div>
                  <div className="grid grid-cols-7 gap-1.5">
                    {Array.from({ length: 49 }).map((_, i) => (
                      <div
                        key={i}
                        className={`aspect-square rounded-sm ${
                          i % 7 === 0
                            ? "bg-[#14F195]/30 border border-[#14F195]/50"
                            : "border border-white/5 bg-white/[0.02]"
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
        </div>
      </section>
    </div>
  );
}
