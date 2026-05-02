//! BagsVault — privacy pool for the Bags creator ecosystem.
//!
//! Architecture mirrors the Tornado-style Solana mixers (Sunspot, the
//! `albertoslavicadev/solana-mixer` reference implementation), with two
//! BagsVault-specific additions:
//!
//! 1. **Compliance-gated deposit**. The on-chain program is permissionless
//!    here — gating happens off-chain in
//!    [`backend/app/services/compliance_service.py`] before the deposit
//!    tx is signed. This matches the "Range Risk pre-deposit" pattern
//!    documented in `docs/arsitektur-sistem.md`.
//! 2. **Relayer-bound proofs**. The withdrawal circuit hashes the relayer
//!    pubkey into the proof's public inputs. A front-runner who copies
//!    the tx from the mempool can't redirect the payout because the proof
//!    won't verify against their pubkey.
//!
//! Public surface:
//!   * `initialize(denomination)` — admin creates a new pool.
//!   * `deposit_sol(commitment)` / `deposit_spl(commitment)` — caller
//!     pays `denomination` (native SOL or SPL token, respectively) and
//!     inserts a leaf into the Merkle tree. `deposit` remains as an
//!     alias for `deposit_sol` for backward compat with existing clients.
//!   * `withdraw_sol(...)` / `withdraw_spl(...)` — anyone holding a
//!     valid proof can claim the corresponding asset. `withdraw` is the
//!     SOL alias for backward compat.
//!   * `register_fee_share(bps)` — register the vault PDA as a Bags Fee
//!     Share V2 recipient. The Fee Share V2 ix layout is assumed; see
//!     `fee_share.rs` for the `TODO(fee-share)` substitution points.
//!   * `pause` / `unpause` / `rotate_authority` — admin guard rails.

use anchor_lang::prelude::*;

pub mod errors;
pub mod fee_share;
pub mod instructions;
pub mod merkle;
pub mod state;
pub mod sunspot;
pub mod verifier;
pub mod verifier_vk;

use instructions::*;

declare_id!("BAGSVau1tProgram11111111111111111111111111111");

#[program]
pub mod bagsvault {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        denomination: u64,
        relayer_fee_bps: u16,
    ) -> Result<()> {
        instructions::initialize::handler(ctx, denomination, relayer_fee_bps)
    }

    // ----- Deposits -----------------------------------------------------
    pub fn deposit_sol(ctx: Context<DepositSol>, commitment: [u8; 32]) -> Result<()> {
        instructions::deposit::handler_sol(ctx, commitment)
    }

    pub fn deposit_spl(ctx: Context<DepositSpl>, commitment: [u8; 32]) -> Result<()> {
        instructions::deposit::handler_spl(ctx, commitment)
    }

    /// Backward-compat alias for `deposit_sol`. Existing clients that
    /// call `deposit` (e.g. the seed_relayers script + the original
    /// backend builder) keep working.
    pub fn deposit(ctx: Context<DepositSol>, commitment: [u8; 32]) -> Result<()> {
        instructions::deposit::handler_sol(ctx, commitment)
    }

    // ----- Withdrawals --------------------------------------------------
    pub fn withdraw_sol(
        ctx: Context<Withdraw>,
        proof: Vec<u8>,
        root: [u8; 32],
        nullifier_hash: [u8; 32],
        recipient: Pubkey,
        amount: u64,
    ) -> Result<()> {
        instructions::withdraw::handler(ctx, proof, root, nullifier_hash, recipient, amount)
    }

    pub fn withdraw_spl(
        ctx: Context<WithdrawSpl>,
        proof: Vec<u8>,
        root: [u8; 32],
        nullifier_hash: [u8; 32],
        recipient: Pubkey,
        amount: u64,
    ) -> Result<()> {
        instructions::withdraw::handler_spl(
            ctx, proof, root, nullifier_hash, recipient, amount,
        )
    }

    /// Backward-compat alias for `withdraw_sol`.
    pub fn withdraw(
        ctx: Context<Withdraw>,
        proof: Vec<u8>,
        root: [u8; 32],
        nullifier_hash: [u8; 32],
        recipient: Pubkey,
        amount: u64,
    ) -> Result<()> {
        instructions::withdraw::handler(ctx, proof, root, nullifier_hash, recipient, amount)
    }

    // ----- Fee Share V2 -------------------------------------------------
    pub fn register_fee_share(ctx: Context<RegisterFeeShare>, bps: u16) -> Result<()> {
        instructions::fee_share::handler(ctx, bps)
    }

    // ----- Admin --------------------------------------------------------
    pub fn pause(ctx: Context<AdminAction>) -> Result<()> {
        instructions::admin::pause(ctx)
    }

    pub fn unpause(ctx: Context<AdminAction>) -> Result<()> {
        instructions::admin::unpause(ctx)
    }

    pub fn rotate_authority(ctx: Context<AdminAction>, new_authority: Pubkey) -> Result<()> {
        instructions::admin::rotate_authority(ctx, new_authority)
    }
}
