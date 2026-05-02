use anchor_lang::prelude::*;

use crate::errors::BagsVaultError;
use crate::state::MerkleTreeState;

#[derive(Accounts)]
pub struct AdminAction<'info> {
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [MerkleTreeState::SEED_PREFIX, tree_state.token_mint.as_ref()],
        bump = tree_state.bump,
        has_one = authority @ BagsVaultError::Unauthorized,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,
}

pub fn pause(ctx: Context<AdminAction>) -> Result<()> {
    ctx.accounts.tree_state.paused = true;
    Ok(())
}

pub fn unpause(ctx: Context<AdminAction>) -> Result<()> {
    ctx.accounts.tree_state.paused = false;
    Ok(())
}

pub fn rotate_authority(ctx: Context<AdminAction>, new_authority: Pubkey) -> Result<()> {
    ctx.accounts.tree_state.authority = new_authority;
    Ok(())
}
