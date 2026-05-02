use anchor_lang::prelude::*;
use anchor_lang::system_program;

use crate::errors::BagsVaultError;
use crate::merkle::insert;
use crate::state::{DepositEvent, MerkleTreeState, RootUpdatedEvent};

#[derive(Accounts)]
#[instruction(commitment: [u8; 32])]
pub struct Deposit<'info> {
    /// Caller funding the deposit. May be a hot wallet, claim-fee
    /// transaction signer, or relayer routing on the user's behalf.
    #[account(mut)]
    pub depositor: Signer<'info>,

    /// Native-SOL escrow PDA derived as `[b"vault", token_mint]`. For
    /// SPL pools the program would use a token account — keeping the
    /// SOL path inline here mirrors the simplest privacy-pool layout.
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
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    pub system_program: Program<'info, system_program::System>,
}

pub fn handler(ctx: Context<Deposit>, commitment: [u8; 32]) -> Result<()> {
    let denomination = ctx.accounts.tree_state.denomination;

    // 1. Move funds into the pool vault. Native-SOL transfer via system
    //    program; SPL-token pools would route through a token::transfer.
    let cpi_accounts = system_program::Transfer {
        from: ctx.accounts.depositor.to_account_info(),
        to: ctx.accounts.vault.to_account_info(),
    };
    let cpi_ctx = CpiContext::new(
        ctx.accounts.system_program.to_account_info(),
        cpi_accounts,
    );
    system_program::transfer(cpi_ctx, denomination)?;

    // 2. Insert commitment into the incremental Merkle tree. This mutates
    //    `filled_subtrees`, advances `commitment_count`, and pushes the
    //    new root into the rolling history buffer.
    let leaf_index = ctx.accounts.tree_state.commitment_count;
    let new_root = insert(&mut ctx.accounts.tree_state, commitment)?;

    let clock = Clock::get()?;
    emit!(DepositEvent {
        commitment,
        leaf_index,
        timestamp: clock.unix_timestamp,
    });
    emit!(RootUpdatedEvent {
        new_root,
        commitment_count: ctx.accounts.tree_state.commitment_count,
    });

    Ok(())
}
