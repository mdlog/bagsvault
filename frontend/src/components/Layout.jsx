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
import { Shield, Menu, X, Copy, LogOut } from "lucide-react";

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
      <DialogContent
        className="bg-[#0c0d10] border-white/10 text-white max-w-md rounded-lg"
        data-testid="connect-wallet-modal"
      >
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold">Connect wallet</DialogTitle>
          <DialogDescription className="text-zinc-500 text-sm">
            Choose a Solana wallet to access the BagsVault privacy pool.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 mt-2">
          {wallets.map((w) => (
            <button
              key={w.name}
              data-testid={`connect-${w.name.toLowerCase()}-btn`}
              onClick={() => handleConnect(w.name)}
              className="w-full flex items-center justify-between p-3.5 bg-[#0a0b0d] border border-white/10 hover:border-white/25 hover:bg-white/[0.02] transition-colors rounded-md group"
            >
              <span className="flex items-center gap-3">
                <span
                  className="w-9 h-9 flex items-center justify-center text-sm font-semibold rounded-md"
                  style={{ background: w.color, color: "#000" }}
                >
                  {w.name[0]}
                </span>
                <span className="font-medium text-sm">{w.name}</span>
              </span>
              <span className="text-[11px] text-zinc-500 group-hover:text-zinc-300">
                Detected
              </span>
            </button>
          ))}
        </div>
        <p className="text-xs text-zinc-600 mt-3">
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
          className="bg-white text-black hover:bg-zinc-200 rounded-md font-medium px-4 h-9 text-sm"
        >
          Connect wallet
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
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                data-testid={`nav-${n.label.toLowerCase()}`}
                className={({ isActive }) =>
                  `px-3 py-1.5 text-sm rounded-md transition-colors ${
                    isActive
                      ? "text-white bg-white/[0.06]"
                      : "text-zinc-400 hover:text-white hover:bg-white/[0.03]"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
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
        {mobile && (
          <div className="lg:hidden border-t border-white/5 bg-[#07080a]">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `block px-6 py-3.5 border-b border-white/5 text-sm ${
                    isActive ? "text-white bg-white/[0.04]" : "text-zinc-400"
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
              <li><Link to="/deposit" className="hover:text-white transition-colors">Deposit</Link></li>
              <li><Link to="/withdraw" className="hover:text-white transition-colors">Withdraw</Link></li>
              <li><Link to="/relayers" className="hover:text-white transition-colors">Relayer network</Link></li>
              <li><Link to="/architecture" className="hover:text-white transition-colors">Architecture</Link></li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-medium text-zinc-300 mb-3">Resources</p>
            <ul className="space-y-2 text-sm text-zinc-500">
              <li><a href="#" className="hover:text-white transition-colors">Documentation</a></li>
              <li><a href="#" className="hover:text-white transition-colors">ZK circuits (Noir)</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Bags API</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Security audit</a></li>
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
