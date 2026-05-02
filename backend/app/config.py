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

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def keypair_path(self, relative_or_abs: str) -> Path:
        """Resolve a keypair path: absolute as-is, otherwise relative to backend root."""
        p = Path(relative_or_abs)
        return p if p.is_absolute() else ROOT_DIR / p


settings = Settings()
