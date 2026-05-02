//! `register_fee_share` — register the privacy vault as a Fee Share V2
//! recipient.
//!
//! Bags' Fee Share V2 program (`FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`)
//! distributes creator-token fees to a configured set of recipients. By
//! registering the vault PDA as a recipient, BagsVault receives creator
//! fees directly into the anonymised pool — no intermediate wallet step.
//!
//! NOTE: the on-chain Fee Share V2 instruction layout is assumed. See
//! `crate::fee_share` for the documented assumption and the
//! `TODO(fee-share)` markers that flag the substitution points.

use anchor_lang::prelude::*;

use crate::errors::BagsVaultError;
use crate::fee_share::{register_fee_share_recipient, FEE_SHARE_V2_PROGRAM_ID};
use crate::state::MerkleTreeState;

#[derive(Accounts)]
#[instruction(bps: u16)]
pub struct RegisterFeeShare<'info> {
    /// Pool authority — only the pool's admin can rebind the share.
    pub authority: Signer<'info>,

    #[account(
        seeds = [MerkleTreeState::SEED_PREFIX, tree_state.token_mint.as_ref()],
        bump = tree_state.bump,
        has_one = authority @ BagsVaultError::Unauthorized,
        constraint = !tree_state.paused @ BagsVaultError::PoolPaused,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    /// Vault PDA — this is the *recipient* the fee share registers.
    /// Derived as `[b"vault", token_mint]` so the same authority can
    /// later sign payouts back out of the pool.
    #[account(
        mut,
        seeds = [b"vault", tree_state.token_mint.as_ref()],
        bump,
    )]
    /// CHECK: PDA used as the registered recipient + CPI signer.
    pub vault: AccountInfo<'info>,

    /// Fee Share V2 program. Hard-pinned to `FEE_SHARE_V2_PROGRAM_ID`.
    /// CHECK: pinned by address; see `crate::fee_share`.
    #[account(address = FEE_SHARE_V2_PROGRAM_ID)]
    pub fee_share_program: AccountInfo<'info>,
}

pub fn handler(ctx: Context<RegisterFeeShare>, bps: u16) -> Result<()> {
    require!(bps <= 10_000, BagsVaultError::DenominationMismatch);

    // Vault signs the CPI with its derivation seeds so the Fee Share V2
    // program can verify the recipient matches the signer.
    let token_mint = ctx.accounts.tree_state.token_mint;
    let vault_bump = ctx.bumps.vault;
    let vault_seeds: &[&[u8]] = &[b"vault", token_mint.as_ref(), &[vault_bump]];
    let signer_seeds: &[&[&[u8]]] = &[vault_seeds];

    // TODO(fee-share): the real Fee Share V2 ix likely needs additional
    // accounts (e.g. config PDA, fee-share state, payer). Once the
    // layout is confirmed, populate `extra_accounts` / `extra_account_infos`
    // here and surface them through the `RegisterFeeShare` accounts struct.
    register_fee_share_recipient(
        &ctx.accounts.fee_share_program,
        ctx.accounts.vault.key(),
        bps,
        signer_seeds,
        &[],
        &[],
    )
}
