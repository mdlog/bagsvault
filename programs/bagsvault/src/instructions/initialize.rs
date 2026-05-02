use anchor_lang::prelude::*;
use anchor_lang::system_program;

use crate::merkle::{empty_filled_subtrees, empty_root};
use crate::state::{MerkleTreeState, RootUpdatedEvent};

#[derive(Accounts)]
#[instruction(denomination: u64)]
pub struct Initialize<'info> {
    /// Pool authority — funds rent and is the only key allowed to call
    /// admin instructions later.
    #[account(mut)]
    pub authority: Signer<'info>,

    /// Token mint that this pool services. Use the System Program ID
    /// (`11111111111111111111111111111111`) as a sentinel for native SOL.
    /// CHECK: only used as a seed; we don't dereference it.
    pub token_mint: AccountInfo<'info>,

    /// PDA holding the merkle-tree state for this pool.
    #[account(
        init,
        payer = authority,
        space = 8 + MerkleTreeState::SIZE,
        seeds = [MerkleTreeState::SEED_PREFIX, token_mint.key().as_ref()],
        bump,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    pub system_program: Program<'info, system_program::System>,
}

pub fn handler(ctx: Context<Initialize>, denomination: u64) -> Result<()> {
    let bump = ctx.bumps.tree_state;
    let state = &mut ctx.accounts.tree_state;
    state.authority = ctx.accounts.authority.key();
    state.token_mint = ctx.accounts.token_mint.key();
    state.denomination = denomination;
    state.commitment_count = 0;
    state.root_cursor = 0;
    state.paused = false;
    state.filled_subtrees = empty_filled_subtrees();
    let initial = empty_root();
    state.roots = [[0u8; 32]; crate::state::ROOT_HISTORY_SIZE];
    state.roots[0] = initial;
    state.bump = bump;

    emit!(RootUpdatedEvent {
        new_root: initial,
        commitment_count: 0,
    });
    Ok(())
}
