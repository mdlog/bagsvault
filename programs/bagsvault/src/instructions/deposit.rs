//! Deposit instructions — splits the original `deposit` into two flavours:
//!
//!   * `deposit_sol` — native-SOL transfer via the System Program. This is
//!     the historical path; the public `deposit` alias in `lib.rs` keeps
//!     existing clients building.
//!   * `deposit_spl` — SPL-token transfer from the depositor's ATA into the
//!     vault's ATA. The vault PDA owns the ATA so subsequent withdrawals
//!     can sign with the program's seeds.
//!
//! Both flows share `core::handle_deposit`, which applies the Merkle
//! insertion + event emission. Splitting only the funds-movement step
//! keeps the privacy-protocol bookkeeping in one place.

use anchor_lang::prelude::*;
use anchor_lang::system_program;
use anchor_spl::token::{self, Token, TokenAccount, Transfer as SplTransfer};

use crate::errors::BagsVaultError;
use crate::merkle::insert;
use crate::state::{DepositEvent, MerkleTreeState, RootUpdatedEvent};

// ---------------------------------------------------------------------------
// Shared helper — Merkle insert + events. Identical for SOL and SPL.
// ---------------------------------------------------------------------------
pub(crate) mod core {
    use super::*;

    pub fn handle_deposit(
        tree_state: &mut Account<MerkleTreeState>,
        commitment: [u8; 32],
    ) -> Result<()> {
        let leaf_index = tree_state.commitment_count;
        let new_root = insert(tree_state, commitment)?;

        let clock = Clock::get()?;
        emit!(DepositEvent {
            commitment,
            leaf_index,
            timestamp: clock.unix_timestamp,
        });
        emit!(RootUpdatedEvent {
            new_root,
            commitment_count: tree_state.commitment_count,
        });

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Native-SOL deposit
// ---------------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(commitment: [u8; 32])]
pub struct DepositSol<'info> {
    /// Caller funding the deposit. May be a hot wallet, claim-fee
    /// transaction signer, or relayer routing on the user's behalf.
    #[account(mut)]
    pub depositor: Signer<'info>,

    /// Native-SOL escrow PDA derived as `[b"vault", token_mint]`.
    #[account(
        mut,
        seeds = [b"vault", tree_state.token_mint.as_ref()],
        bump,
    )]
    /// CHECK: PDA-owned native account; no data, only lamports.
    pub vault: AccountInfo<'info>,

    #[account(
        mut,
        seeds = [MerkleTreeState::SEED_PREFIX, tree_state.token_mint.as_ref()],
        bump = tree_state.bump,
        constraint = !tree_state.paused @ BagsVaultError::PoolPaused,
        // The SOL path is only valid when the pool's mint sentinel is the
        // System Program ID; mint-bound pools must use `deposit_spl`.
        constraint = tree_state.token_mint == anchor_lang::solana_program::system_program::ID
            @ BagsVaultError::DenominationMismatch,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    pub system_program: Program<'info, system_program::System>,
}

pub fn handler_sol(ctx: Context<DepositSol>, commitment: [u8; 32]) -> Result<()> {
    let denomination = ctx.accounts.tree_state.denomination;

    // 1. Native-SOL transfer via the system program.
    let cpi_accounts = system_program::Transfer {
        from: ctx.accounts.depositor.to_account_info(),
        to: ctx.accounts.vault.to_account_info(),
    };
    let cpi_ctx = CpiContext::new(
        ctx.accounts.system_program.to_account_info(),
        cpi_accounts,
    );
    system_program::transfer(cpi_ctx, denomination)?;

    // 2. Shared Merkle bookkeeping.
    core::handle_deposit(&mut ctx.accounts.tree_state, commitment)
}

// ---------------------------------------------------------------------------
// SPL-token deposit
// ---------------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(commitment: [u8; 32])]
pub struct DepositSpl<'info> {
    /// Caller funding the deposit.
    #[account(mut)]
    pub depositor: Signer<'info>,

    /// Vault PDA — authority over the vault's ATA. We don't dereference its
    /// data; the seed-derivation alone is what binds the deposit to the
    /// correct pool.
    #[account(
        mut,
        seeds = [b"vault", tree_state.token_mint.as_ref()],
        bump,
    )]
    /// CHECK: PDA used purely as the ATA authority.
    pub vault: AccountInfo<'info>,

    /// Source token account — caller's ATA for `tree_state.token_mint`.
    #[account(
        mut,
        constraint = depositor_token_account.mint == tree_state.token_mint
            @ BagsVaultError::DenominationMismatch,
        constraint = depositor_token_account.owner == depositor.key()
            @ BagsVaultError::Unauthorized,
    )]
    pub depositor_token_account: Account<'info, TokenAccount>,

    /// Destination token account — the vault PDA's ATA. Must already
    /// exist (initialised by an admin or a prior deposit). Anchor checks
    /// the mint matches; the owner must be the vault PDA.
    #[account(
        mut,
        constraint = vault_token_account.mint == tree_state.token_mint
            @ BagsVaultError::DenominationMismatch,
        constraint = vault_token_account.owner == vault.key()
            @ BagsVaultError::Unauthorized,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [MerkleTreeState::SEED_PREFIX, tree_state.token_mint.as_ref()],
        bump = tree_state.bump,
        constraint = !tree_state.paused @ BagsVaultError::PoolPaused,
        // SPL path is only valid for non-SOL mints.
        constraint = tree_state.token_mint != anchor_lang::solana_program::system_program::ID
            @ BagsVaultError::DenominationMismatch,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, system_program::System>,
}

pub fn handler_spl(ctx: Context<DepositSpl>, commitment: [u8; 32]) -> Result<()> {
    let denomination = ctx.accounts.tree_state.denomination;

    // 1. SPL transfer from depositor's ATA -> vault's ATA. The depositor
    //    is the signer of this CPI (no PDA seeds needed for an outbound
    //    transfer they authorise themselves).
    let cpi_accounts = SplTransfer {
        from: ctx.accounts.depositor_token_account.to_account_info(),
        to: ctx.accounts.vault_token_account.to_account_info(),
        authority: ctx.accounts.depositor.to_account_info(),
    };
    let cpi_ctx = CpiContext::new(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
    );
    token::transfer(cpi_ctx, denomination)?;

    // 2. Shared Merkle bookkeeping.
    core::handle_deposit(&mut ctx.accounts.tree_state, commitment)
}
