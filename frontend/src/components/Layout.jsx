import { Outlet, NavLink, Link, useLocation } from "react-router-dom";
import { useState, useEffect } from "react";
import { useWallet } from "@/context/WalletContext";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Shield, Menu, X, Copy, LogOut, Zap } from "lucide-react";

const NAV = [
  { to: "/deposit", label: "Deposit" },
  { to: "/withdraw", label: "Withdraw" },
  { to: "/relayers", label: "Relayers" },
  { to: "/compliance", label: "Compliance" },
  { to: "/architecture", label: "Architecture" },
];

const ConnectModal = ({ open, onOpenChange }) => {
  const { connect } = useWallet();
  const handleConnect = (provider) => {
    const data = connect(provider);
    toast.success(`Connected to ${provider}`, {
      description: `${data.address.slice(0, 6)}...${data.address.slice(-4)}`,
    });
    onOpenChange(false);
  };
  const wallets = [
    { name: "Phantom", color: "#AB9FF2" },
    { name: "Solflare", color: "#FC9828" },
    { name: "Backpack", color: "#E33E3F" },
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#0A0A0A] border-white/10 text-white max-w-md rounded-none" data-testid="connect-wallet-modal">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Connect Wallet</DialogTitle>
          <DialogDescription className="text-zinc-500">
            Choose a Solana wallet to access the BagsVault privacy pool.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 mt-2">
          {wallets.map((w) => (
            <button
              key={w.name}
              data-testid={`connect-${w.name.toLowerCase()}-btn`}
              onClick={() => handleConnect(w.name)}
              className="w-full flex items-center justify-between p-4 bg-black border border-white/10 hover:border-white/30 hover:bg-white/[0.02] transition-all group"
            >
              <span className="flex items-center gap-3">
                <span
                  className="w-9 h-9 flex items-center justify-center text-sm font-bold"
                  style={{ background: w.color, color: "#000" }}
                >
                  {w.name[0]}
                </span>
                <span className="font-medium text-left">{w.name}</span>
              </span>
              <span className="text-xs text-zinc-500 uppercase tracking-[0.2em] group-hover:text-[#14F195]">
                Detected
              </span>
            </button>
          ))}
        </div>
        <p className="text-xs text-zinc-600 mt-4 font-mono">
          Demo mode: wallet connection is simulated for UI preview.
        </p>
      </DialogContent>
    </Dialog>
  );
};

const WalletPill = () => {
  const { wallet, balance, disconnect } = useWallet();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);

  if (!wallet) {
    return (
      <>
        <Button
          data-testid="connect-wallet-btn"
          onClick={() => setOpen(true)}
          className="bg-white text-black hover:bg-zinc-200 rounded-none font-semibold px-5 h-10"
        >
          Connect Wallet
        </Button>
        <ConnectModal open={open} onOpenChange={setOpen} />
      </>
    );
  }

  return (
    <div className="relative">
      <button
        data-testid="wallet-pill"
        onClick={() => setMenu(!menu)}
        className="flex items-center gap-3 bg-black border border-white/10 hover:border-[#14F195]/50 px-3 h-10 transition-colors"
      >
        <span className="w-2 h-2 bg-[#14F195] rounded-full pulse-glow" />
        <span className="font-mono text-xs text-white">
          {wallet.address.slice(0, 4)}…{wallet.address.slice(-4)}
        </span>
        <span className="hidden sm:inline text-xs text-zinc-500 font-mono border-l border-white/10 pl-3">
          {balance.toFixed(2)} SOL
        </span>
      </button>
      {menu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenu(false)} />
          <div className="absolute right-0 top-12 w-64 bg-[#0A0A0A] border border-white/10 z-50 shadow-2xl">
            <div className="p-4 border-b border-white/5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Connected</p>
              <p className="font-mono text-xs text-white mt-1 break-all">{wallet.address}</p>
            </div>
            <button
              data-testid="copy-address-btn"
              onClick={() => {
                navigator.clipboard.writeText(wallet.address);
                toast.success("Address copied");
                setMenu(false);
              }}
              className="w-full flex items-center gap-3 p-4 hover:bg-white/[0.03] text-sm border-b border-white/5"
            >
              <Copy className="w-4 h-4 text-zinc-500" /> Copy address
            </button>
            <button
              data-testid="disconnect-wallet-btn"
              onClick={() => {
                disconnect();
                toast("Wallet disconnected");
                setMenu(false);
              }}
              className="w-full flex items-center gap-3 p-4 hover:bg-white/[0.03] text-sm text-red-400"
            >
              <LogOut className="w-4 h-4" /> Disconnect
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
    <div className="min-h-screen flex flex-col bg-[#050505] text-white">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-white/5 glass">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between px-6 lg:px-10 h-16">
          <Link to="/" data-testid="logo-link" className="flex items-center gap-2.5 group">
            <span className="relative w-8 h-8 flex items-center justify-center bg-black border border-white/10">
              <Shield className="w-4 h-4 text-[#14F195]" />
              <span className="absolute -inset-px border border-[#14F195]/30 animate-pulse" />
            </span>
            <span className="font-display font-bold text-base tracking-tight">
              Bags<span className="text-[#14F195]">Vault</span>
            </span>
          </Link>

          <nav className="hidden lg:flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                data-testid={`nav-${n.label.toLowerCase()}`}
                className={({ isActive }) =>
                  `px-4 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? "text-white bg-white/[0.04]"
                      : "text-zinc-500 hover:text-white"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-2 px-3 h-10 bg-black border border-white/10">
              <span className="w-1.5 h-1.5 bg-[#14F195] rounded-full" />
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-zinc-500">
                Solana · Mainnet
              </span>
            </div>
            <WalletPill />
            <button
              data-testid="mobile-menu-btn"
              onClick={() => setMobile(!mobile)}
              className="lg:hidden w-10 h-10 flex items-center justify-center border border-white/10"
            >
              {mobile ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>
        {mobile && (
          <div className="lg:hidden border-t border-white/5 bg-[#050505]">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `block px-6 py-4 border-b border-white/5 text-sm ${
                    isActive ? "text-[#14F195]" : "text-zinc-400"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </div>
        )}
      </header>

      <main className="flex-1" data-testid="main-content">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 mt-20">
        <div className="max-w-[1400px] mx-auto px-6 lg:px-10 py-14 grid md:grid-cols-4 gap-10">
          <div className="md:col-span-2">
            <div className="flex items-center gap-2.5">
              <span className="w-8 h-8 flex items-center justify-center bg-black border border-white/10">
                <Shield className="w-4 h-4 text-[#14F195]" />
              </span>
              <span className="font-display font-bold">BagsVault</span>
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
            <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">Protocol</p>
            <ul className="space-y-2 text-sm text-zinc-400">
              <li><Link to="/deposit" className="hover:text-white">Deposit</Link></li>
              <li><Link to="/withdraw" className="hover:text-white">Withdraw</Link></li>
              <li><Link to="/relayers" className="hover:text-white">Relayer Network</Link></li>
              <li><Link to="/architecture" className="hover:text-white">Architecture</Link></li>
            </ul>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">Resources</p>
            <ul className="space-y-2 text-sm text-zinc-400">
              <li><a href="#" className="hover:text-white">Documentation</a></li>
              <li><a href="#" className="hover:text-white">ZK Circuits (Noir)</a></li>
              <li><a href="#" className="hover:text-white">Bags API</a></li>
              <li><a href="#" className="hover:text-white">Security Audit</a></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/5">
          <div className="max-w-[1400px] mx-auto px-6 lg:px-10 py-5 flex flex-col md:flex-row items-center justify-between gap-2 text-xs font-mono text-zinc-600">
            <span>© 2025 BagsVault Protocol · ZK-Anonymity Set v2</span>
            <span className="flex items-center gap-2">
              <Zap className="w-3 h-3 text-[#14F195]" />
              root: 0x7a3f…c9e1 · block 293,847,201
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
