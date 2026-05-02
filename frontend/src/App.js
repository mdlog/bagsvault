import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { WalletProvider } from "@/context/WalletContext";
import Layout from "@/components/Layout";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import Deposit from "@/pages/Deposit";
import Withdraw from "@/pages/Withdraw";
import Relayers from "@/pages/Relayers";
import Compliance from "@/pages/Compliance";
import Architecture from "@/pages/Architecture";

function App() {
  return (
    <div className="App min-h-screen bg-[#07080a] text-white">
      <WalletProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Landing />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/deposit" element={<Deposit />} />
              <Route path="/withdraw" element={<Withdraw />} />
              <Route path="/relayers" element={<Relayers />} />
              <Route path="/compliance" element={<Compliance />} />
              <Route path="/architecture" element={<Architecture />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#0c0d10",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "#fff",
              borderRadius: "8px",
            },
          }}
        />
      </WalletProvider>
    </div>
  );
}

export default App;
