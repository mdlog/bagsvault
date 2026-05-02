// Real Solana wallet adapter integration.
//
// Wraps `@solana/wallet-adapter-react` providers and re-exports a custom
// `useWallet()` hook that maintains the legacy API surface (`wallet`,
// `balance`, `connect`, `disconnect`) so existing pages don't break,
// while exposing `signAndSendTx(base64)` + `connection` + `publicKey`
// for real on-chain interactions.
//
// RPC endpoint comes from `REACT_APP_SOLANA_RPC_URL` (default: devnet).
// Network commitment is `confirmed` to match the backend default.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ConnectionProvider,
  WalletProvider as SolanaWalletProvider,
  useConnection,
  useWallet as useSolanaWallet,
} from "@solana/wallet-adapter-react";
import {
  WalletModalProvider,
  useWalletModal,
} from "@solana/wallet-adapter-react-ui";
import {
  PhantomWalletAdapter,
  SolflareWalletAdapter,
} from "@solana/wallet-adapter-wallets";
import { clusterApiUrl } from "@solana/web3.js";

import "@solana/wallet-adapter-react-ui/styles.css";

const DEFAULT_ENDPOINT =
  process.env.REACT_APP_SOLANA_RPC_URL || clusterApiUrl("devnet");

// Adapter list. The wallet-standard auto-discovers Backpack and any
// other browser-extension wallet that implements the standard, so we
// only need to register the ones that lack standard discovery.
const ADAPTERS = [new PhantomWalletAdapter(), new SolflareWalletAdapter()];

/**
 * Public provider — drop into App.jsx as `<WalletProvider>`. Wires the
 * Solana ConnectionProvider + WalletProvider + WalletModalProvider in
 * the order the adapter expects.
 */
export const WalletProvider = ({ children }) => {
  return (
    <ConnectionProvider endpoint={DEFAULT_ENDPOINT}>
      <SolanaWalletProvider wallets={ADAPTERS} autoConnect>
        <WalletModalProvider>{children}</WalletModalProvider>
      </SolanaWalletProvider>
    </ConnectionProvider>
  );
};

/**
 * Legacy-compatible wallet hook.
 *
 * Returns:
 *   - wallet: { address, provider } | null
 *   - balance: number (SOL)
 *   - connect(): opens the wallet picker modal
 *   - disconnect(): disconnects the active adapter
 *   - publicKey: web3.js PublicKey | null
 *   - connection: web3.js Connection
 *   - signAndSendTx(base64Tx) -> Promise<string>
 *   - connecting / connected: passthrough booleans from the adapter
 */
export const useWallet = () => {
  const { connection } = useConnection();
  const solana = useSolanaWallet();
  const { setVisible } = useWalletModal();

  const [balance, setBalance] = useState(0);

  // Refresh balance whenever the connected pubkey changes, then poll
  // every 30s while connected so the navbar pill stays roughly current.
  useEffect(() => {
    let cancelled = false;
    const fetchBalance = async () => {
      if (!solana.publicKey) {
        if (!cancelled) setBalance(0);
        return;
      }
      try {
        const lamports = await connection.getBalance(solana.publicKey);
        if (!cancelled) setBalance(lamports / 1_000_000_000);
      } catch {
        if (!cancelled) setBalance(0);
      }
    };
    fetchBalance();
    const id = setInterval(fetchBalance, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [solana.publicKey, connection]);

  const wallet = useMemo(() => {
    if (!solana.publicKey) return null;
    return {
      address: solana.publicKey.toBase58(),
      provider: solana.wallet?.adapter?.name || "Unknown",
    };
  }, [solana.publicKey, solana.wallet]);

  /**
   * Open the wallet picker modal. The legacy API accepted a provider
   * name; the real adapter delegates picking to its own modal. We
   * accept the arg for backward compat but ignore it.
   */
  const connect = useCallback(
    (_provider) => {
      setVisible(true);
      return { address: "", provider: _provider || "Unknown" };
    },
    [setVisible],
  );

  const disconnect = useCallback(async () => {
    try {
      await solana.disconnect();
    } catch {
      // adapter throws if not connected — ignore.
    }
  }, [solana]);

  /**
   * Deserialize a backend-built unsigned VersionedTransaction (base64),
   * refresh its blockhash with the live one (so the build → sign → send
   * flow doesn't race the validator's expiration window), then dispatch
   * via the wallet's `sendTransaction` method and wait for confirmation.
   */
  const signAndSendTx = useCallback(
    async (txBase64) => {
      if (!solana.publicKey || !solana.sendTransaction) {
        throw new Error("Wallet is not connected.");
      }
      const { VersionedTransaction } = await import("@solana/web3.js");
      const buf = Uint8Array.from(atob(txBase64), (c) => c.charCodeAt(0));
      const tx = VersionedTransaction.deserialize(buf);

      const latest = await connection.getLatestBlockhash("confirmed");
      tx.message.recentBlockhash = latest.blockhash;

      const signature = await solana.sendTransaction(tx, connection, {
        maxRetries: 3,
        skipPreflight: false,
      });
      await connection.confirmTransaction(
        {
          signature,
          blockhash: latest.blockhash,
          lastValidBlockHeight: latest.lastValidBlockHeight,
        },
        "confirmed",
      );
      return signature;
    },
    [solana, connection],
  );

  return {
    wallet,
    balance,
    connect,
    disconnect,
    publicKey: solana.publicKey,
    connection,
    signAndSendTx,
    connecting: solana.connecting,
    connected: solana.connected,
  };
};
