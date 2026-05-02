import { createContext, useContext, useState, useEffect } from "react";

const WalletContext = createContext(null);

const MOCK_ADDRESSES = [
  "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
  "BqXa2c8hXJ4Fk3rT1n7mV9pLwEsYqCzNxRpDtG2bQvMh",
  "9HfC4mKjvRtPxN3LqYw2sFdA5eXoZgBhUvTpQnM7WcVK",
];

export const WalletProvider = ({ children }) => {
  const [wallet, setWallet] = useState(null);
  const [balance, setBalance] = useState(0);

  useEffect(() => {
    const saved = localStorage.getItem("bv_wallet");
    if (saved) {
      const parsed = JSON.parse(saved);
      setWallet(parsed);
      setBalance(parsed.balance || 0);
    }
  }, []);

  const connect = (provider = "Phantom") => {
    const address = MOCK_ADDRESSES[Math.floor(Math.random() * MOCK_ADDRESSES.length)];
    const bal = parseFloat((Math.random() * 50 + 5).toFixed(4));
    const data = { address, provider, balance: bal };
    setWallet(data);
    setBalance(bal);
    localStorage.setItem("bv_wallet", JSON.stringify(data));
    return data;
  };

  const disconnect = () => {
    setWallet(null);
    setBalance(0);
    localStorage.removeItem("bv_wallet");
  };

  return (
    <WalletContext.Provider value={{ wallet, balance, connect, disconnect }}>
      {children}
    </WalletContext.Provider>
  );
};

export const useWallet = () => {
  const ctx = useContext(WalletContext);
  if (!ctx) throw new Error("useWallet must be used within WalletProvider");
  return ctx;
};
