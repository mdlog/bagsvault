from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    mongo_url: str = Field(default="mongodb://localhost:27017", alias="MONGO_URL")
    db_name: str = Field(default="bagsvault", alias="DB_NAME")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Solana
    solana_rpc_url: str = Field(default="https://api.devnet.solana.com", alias="SOLANA_RPC_URL")
    solana_cluster: Literal["devnet", "testnet", "mainnet-beta"] = Field(
        default="devnet", alias="SOLANA_CLUSTER"
    )
    solana_commitment: Literal["processed", "confirmed", "finalized"] = Field(
        default="confirmed", alias="SOLANA_COMMITMENT"
    )
    solana_relayer_keypair: str = Field(default="keys/relayer.json", alias="SOLANA_RELAYER_KEYPAIR")
    solana_treasury_keypair: str = Field(
        default="keys/treasury.json", alias="SOLANA_TREASURY_KEYPAIR"
    )
    solana_token_authority_keypair: str = Field(
        default="keys/token_authority.json", alias="SOLANA_TOKEN_AUTHORITY_KEYPAIR"
    )

    # BagsVault on-chain (empty until program deployed)
    bagsvault_program_id: str = Field(default="", alias="BAGSVAULT_PROGRAM_ID")
    bagsvault_verifier_id: str = Field(default="", alias="BAGSVAULT_VERIFIER_ID")
    vault_token_mint: str = Field(default="", alias="VAULT_TOKEN_MINT")

    # Bags API
    bags_api_base_url: str = Field(default="https://api.bags.fm", alias="BAGS_API_BASE_URL")
    bags_api_key: str = Field(default="", alias="BAGS_API_KEY")

    # Range Risk API
    range_api_base_url: str = Field(default="https://api.range.org", alias="RANGE_API_BASE_URL")
    range_api_key: str = Field(default="", alias="RANGE_API_KEY")

    # Rate limiting
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    # Auth
    auth_message_max_age_seconds: int = Field(default=300, alias="AUTH_MESSAGE_MAX_AGE_SECONDS")

    # Relayer
    relayer_fee_bps: int = Field(default=15, alias="RELAYER_FEE_BPS")
    relayer_region: str = Field(default="US-East", alias="RELAYER_REGION")
    relayer_name: str = Field(default="BagsVault-Default", alias="RELAYER_NAME")
    relayer_max_compute_units: int = Field(default=400_000, alias="RELAYER_MAX_COMPUTE_UNITS")

    # Phase 3: indexer + tx lifecycle
    indexer_interval_seconds: int = Field(default=15, alias="INDEXER_INTERVAL_SECONDS")
    indexer_enabled: bool = Field(default=True, alias="INDEXER_ENABLED")
    bagsvault_idl_path: str = Field(
        default="../idl/bagsvault.json", alias="BAGSVAULT_IDL_PATH"
    )
    solana_ws_url: str = Field(default="", alias="SOLANA_WS_URL")
    tx_simulation_required: bool = Field(default=True, alias="TX_SIMULATION_REQUIRED")
    tx_priority_fee_microlamports: int = Field(default=1000, alias="TX_PRIORITY_FEE_MICROLAMPORTS")
    tx_retry_max_attempts: int = Field(default=3, alias="TX_RETRY_MAX_ATTEMPTS")
    tx_retry_initial_backoff_ms: int = Field(default=500, alias="TX_RETRY_INITIAL_BACKOFF_MS")
    tx_confirm_timeout_seconds: int = Field(default=60, alias="TX_CONFIRM_TIMEOUT_SECONDS")

    # Phase 4: ZK proof generation toolchain
    zk_circuit_dir: str = Field(
        default="../circuits/bagsvault_withdraw", alias="ZK_CIRCUIT_DIR"
    )
    zk_nargo_bin: str = Field(default="nargo", alias="ZK_NARGO_BIN")
    zk_bb_bin: str = Field(default="bb", alias="ZK_BB_BIN")
    # When true, the proof service emits zero-byte stubs instead of
    # invoking nargo/bb. The on-chain verifier rejects stubs by design —
    # this flag is for local plumbing tests, never for production.
    zk_proof_stub_mode: bool = Field(default=False, alias="ZK_PROOF_STUB_MODE")

    @property
    def derived_ws_url(self) -> str:
        """Return ``solana_ws_url`` or derive from RPC URL by swapping scheme."""

        if self.solana_ws_url:
            return self.solana_ws_url
        rpc = self.solana_rpc_url
        if rpc.startswith("https://"):
            return "wss://" + rpc[len("https://") :]
        if rpc.startswith("http://"):
            return "ws://" + rpc[len("http://") :]
        return rpc

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def keypair_path(self, relative_or_abs: str) -> Path:
        """Resolve a keypair path: absolute as-is, otherwise relative to backend root."""
        p = Path(relative_or_abs)
        return p if p.is_absolute() else ROOT_DIR / p


settings = Settings()
