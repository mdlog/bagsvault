import { Outlet, NavLink, Link, useLocation } from "react-router-dom";
import { useState, useEffect } from "react";
import { useWallet } from "@/context/WalletContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Shield, Menu, X, Copy, LogOut, LayoutDashboard } from "lucide-react";

// Primary navigation. The "feature" group is the protocol surface
// (Deposit, Withdraw); "network" is the supporting infra
// (Relayers, Compliance). Architecture / docs live in the footer to
// keep the navbar focused on actionable pages.
const NAV_FEATURES = [
  { to: "/deposit", label: "Deposit", desc: "Add tokens to the pool" },
  { to: "/withdraw", label: "Withdraw", desc: "Claim anonymously" },
];
const NAV_NETWORK = [
  { to: "/relayers", label: "Relayers", desc: "Gas-paying nodes" },
  { to: "/compliance", label: "Compliance", desc: "Range Risk scans" },
];

// `ConnectModal` is intentionally removed — the real wallet adapter
// ships its own modal via `WalletModalProvider` and the
// `useWalletModal().setVisible(true)` hook (called by `connect()`),
// which auto-discovers installed wallets via the wallet-standard.

// Dashboard link only renders when the user has a connected wallet.
// Highlights as a primary action so the connected user immediately
// sees their pool overview entry-point.
const DashboardNavLink = () => {
  const { wallet } = useWallet();
  if (!wallet) return null;
  return (
    <NavLink
      to="/dashboard"
      data-testid="nav-dashboard"
      className={({ isActive }) =>
        `inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
          isActive
            ? "text-[#14F195] bg-[#14F195]/[0.08] border border-[#14F195]/25"
            : "text-zinc-300 hover:text-white hover:bg-white/[0.03] border border-transparent"
        }`
      }
    >
      <LayoutDashboard className="w-3.5 h-3.5" />
      Dashboard
    </NavLink>
  );
};

// Compact dropdown grouping a small set of related routes. Hover- /
// focus-driven; the menu inherits the existing dark styling.
const NavGroup = ({ label, items }) => {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const activeChild = items.some((i) => location.pathname.startsWith(i.to));
  return (
    <div
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        data-testid={`nav-group-${label.toLowerCase()}`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
          activeChild
            ? "text-white bg-white/[0.06]"
            : "text-zinc-400 hover:text-white hover:bg-white/[0.03]"
        }`}
      >
        {label}
      </button>
      {open && (
        <div className="absolute left-0 top-9 w-60 bg-[#0c0d10] border border-white/10 rounded-md shadow-xl overflow-hidden z-50">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={`nav-${item.label.toLowerCase()}`}
              className={({ isActive }) =>
                `block px-3.5 py-3 hover:bg-white/[0.03] transition-colors border-b border-white/5 last:border-0 ${
                  isActive ? "bg-white/[0.05]" : ""
                }`
              }
            >
              <p className="text-sm text-white">{item.label}</p>
              <p className="text-[11px] text-zinc-500 mt-0.5">{item.desc}</p>
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
};

// Mobile drawer rendered below the navbar. Keeps the same grouped
// structure as desktop so the IA stays consistent.
const MobileNav = () => {
  const { wallet } = useWallet();
  return (
    <div className="lg:hidden border-t border-white/5 bg-[#07080a]">
      {wallet && (
        <NavLink
          to="/dashboard"
          className={({ isActive }) =>
            `block px-6 py-3.5 border-b border-white/5 text-sm ${
              isActive ? "text-[#14F195] bg-[#14F195]/[0.06]" : "text-zinc-300"
            }`
          }
        >
          Dashboard
        </NavLink>
      )}
      <p className="px-6 pt-3 pb-1 text-[10px] uppercase tracking-wider text-zinc-600">
        Protocol
      </p>
      {NAV_FEATURES.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          className={({ isActive }) =>
            `block px-6 py-3 text-sm ${
              isActive ? "text-white bg-white/[0.04]" : "text-zinc-400"
            }`
          }
        >
          {n.label}
          <span className="block text-[11px] text-zinc-600 mt-0.5">{n.desc}</span>
        </NavLink>
      ))}
      <p className="px-6 pt-3 pb-1 text-[10px] uppercase tracking-wider text-zinc-600 border-t border-white/5">
        Network
      </p>
      {NAV_NETWORK.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          className={({ isActive }) =>
            `block px-6 py-3 text-sm ${
              isActive ? "text-white bg-white/[0.04]" : "text-zinc-400"
            }`
          }
        >
          {n.label}
          <span className="block text-[11px] text-zinc-600 mt-0.5">{n.desc}</span>
        </NavLink>
      ))}
      <NavLink
        to="/architecture"
        className="block px-6 py-3 text-sm text-zinc-500 border-t border-white/5"
      >
        Architecture & docs
      </NavLink>
    </div>
  );
};

const WalletPill = () => {
  const { wallet, balance, connect, disconnect, connecting } = useWallet();
  const [menu, setMenu] = useState(false);

  if (!wallet) {
    return (
      <Button
        data-testid="connect-wallet-btn"
        onClick={() => connect()}
        disabled={connecting}
        className="bg-white text-black hover:bg-zinc-200 rounded-md font-medium px-4 h-9 text-sm disabled:opacity-60"
      >
        {connecting ? "Connecting…" : "Connect wallet"}
      </Button>
    );
  }

  return (
    <div className="relative">
      <button
        data-testid="wallet-pill"
        onClick={() => setMenu(!menu)}
        className="flex items-center gap-2.5 bg-[#0c0d10] border border-white/10 hover:border-white/20 px-3 h-9 rounded-md transition-colors"
      >
        <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
        <span className="font-mono text-xs text-white">
          {wallet.address.slice(0, 4)}…{wallet.address.slice(-4)}
        </span>
        <span className="hidden sm:inline text-xs text-zinc-500 font-mono border-l border-white/10 pl-2.5">
          {balance.toFixed(2)} SOL
        </span>
      </button>
      {menu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenu(false)} />
          <div className="absolute right-0 top-11 w-64 bg-[#0c0d10] border border-white/10 z-50 shadow-xl rounded-md overflow-hidden">
            <div className="p-3.5 border-b border-white/5">
              <p className="text-[11px] text-zinc-500">Connected</p>
              <p className="font-mono text-xs text-white mt-1 break-all">{wallet.address}</p>
            </div>
            <button
              data-testid="copy-address-btn"
              onClick={() => {
                navigator.clipboard.writeText(wallet.address);
                toast.success("Address copied");
                setMenu(false);
              }}
              className="w-full flex items-center gap-3 px-3.5 py-3 hover:bg-white/[0.03] text-sm border-b border-white/5"
            >
              <Copy className="w-3.5 h-3.5 text-zinc-500" /> Copy address
            </button>
            <button
              data-testid="disconnect-wallet-btn"
              onClick={() => {
                disconnect();
                toast("Wallet disconnected");
                setMenu(false);
              }}
              className="w-full flex items-center gap-3 px-3.5 py-3 hover:bg-white/[0.03] text-sm text-red-400"
            >
              <LogOut className="w-3.5 h-3.5" /> Disconnect
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default function Layout() {
  const [mobile, setMobile] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMobile(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="min-h-screen flex flex-col bg-[#07080a] text-white">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-white/5 bg-[#07080a]/80 backdrop-blur-md">
        <div className="max-w-[1280px] mx-auto flex items-center justify-between px-6 lg:px-8 h-14">
          <Link to="/" data-testid="logo-link" className="flex items-center gap-2">
            <span className="w-7 h-7 flex items-center justify-center bg-[#14F195]/10 border border-[#14F195]/30 rounded-md">
              <Shield className="w-3.5 h-3.5 text-[#14F195]" />
            </span>
            <span className="font-semibold text-[15px] tracking-tight">
              BagsVault
            </span>
          </Link>

          <nav className="hidden lg:flex items-center gap-1">
            <DashboardNavLink />
            <NavGroup label="Protocol" items={NAV_FEATURES} />
            <NavGroup label="Network" items={NAV_NETWORK} />
          </nav>

          <div className="flex items-center gap-2">
            <div className="hidden md:flex items-center gap-2 px-2.5 h-9 bg-[#0c0d10] border border-white/10 rounded-md">
              <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
              <span className="text-[11px] font-mono text-zinc-400">Mainnet</span>
            </div>
            <WalletPill />
            <button
              data-testid="mobile-menu-btn"
              onClick={() => setMobile(!mobile)}
              className="lg:hidden w-9 h-9 flex items-center justify-center border border-white/10 rounded-md"
            >
              {mobile ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>
        {mobile && <MobileNav />}
      </header>

      <main className="flex-1" data-testid="main-content">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 mt-24">
        <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-12 grid md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 flex items-center justify-center bg-[#14F195]/10 border border-[#14F195]/30 rounded-md">
                <Shield className="w-3.5 h-3.5 text-[#14F195]" />
              </span>
              <span className="font-semibold text-[15px]">BagsVault</span>
            </div>
            <p className="text-zinc-500 text-sm mt-4 max-w-sm leading-relaxed">
              A zero-knowledge privacy protocol for Bags.fm creators. Claim fees,
              receive donations, and move tokens without exposing your on-chain identity.
            </p>
            <p className="text-xs text-zinc-600 mt-4 font-mono">
              Built on Solana · Secured by Groth16 ZK-SNARKs
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-zinc-300 mb-3">Protocol</p>
            <ul className="space-y-2 text-sm text-zinc-500">
              <li><Link to="/dashboard" className="hover:text-white transition-colors">Dashboard</Link></li>
              <li><Link to="/deposit" className="hover:text-white transition-colors">Deposit</Link></li>
              <li><Link to="/withdraw" className="hover:text-white transition-colors">Withdraw</Link></li>
              <li><Link to="/relayers" className="hover:text-white transition-colors">Relayer network</Link></li>
              <li><Link to="/compliance" className="hover:text-white transition-colors">Compliance</Link></li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-medium text-zinc-300 mb-3">Resources</p>
            <ul className="space-y-2 text-sm text-zinc-500">
              <li><Link to="/architecture" className="hover:text-white transition-colors">Architecture &amp; docs</Link></li>
              <li>
                <a
                  href="https://github.com/mdlog/bagsvault"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  GitHub
                </a>
              </li>
              <li>
                <a
                  href="https://noir-lang.org/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  ZK circuits (Noir)
                </a>
              </li>
              <li>
                <a
                  href="https://docs.bags.fm/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-white transition-colors"
                >
                  Bags API
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/5">
          <div className="max-w-[1280px] mx-auto px-6 lg:px-8 py-4 flex flex-col md:flex-row items-center justify-between gap-2 text-xs text-zinc-600">
            <span>© 2025 BagsVault Protocol</span>
            <span className="font-mono">root 0x7a3f…c9e1 · block 293,847,201</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
