use anchor_lang::prelude::*;

use crate::errors::BagsVaultError;
use crate::state::{MerkleTreeState, Nullifier, WithdrawEvent};
use crate::sunspot::verify_via_sunspot;
use crate::verifier::{
    pubkey_to_field, u64_to_field, verify_withdraw_proof, NUM_PUBLIC_INPUTS,
};

#[derive(Accounts)]
#[instruction(
    proof: Vec<u8>,
    root: [u8; 32],
    nullifier_hash: [u8; 32],
    recipient: Pubkey,
    amount: u64,
)]
pub struct Withdraw<'info> {
    /// Relayer paying the gas. Bound into the proof's public inputs so a
    /// front-runner who lifts the tx from the mempool can't redirect the
    /// payout to themselves — the proof is keyed to this exact pubkey.
    #[account(mut)]
    pub relayer: Signer<'info>,

    #[account(
        mut,
        seeds = [b"vault", tree_state.token_mint.as_ref()],
        bump,
    )]
    /// CHECK: PDA-owned native account holding pooled SOL.
    pub vault: AccountInfo<'info>,

    #[account(
        mut,
        seeds = [MerkleTreeState::SEED_PREFIX, tree_state.token_mint.as_ref()],
        bump = tree_state.bump,
        constraint = !tree_state.paused @ BagsVaultError::PoolPaused,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    /// Per-nullifier PDA. `init` will fail if the nullifier was already
    /// spent — Anchor's account-already-in-use error is the protocol's
    /// double-spend guard.
    #[account(
        init,
        payer = relayer,
        space = 8 + Nullifier::SIZE,
        seeds = [Nullifier::SEED_PREFIX, nullifier_hash.as_ref()],
        bump,
    )]
    pub nullifier_pda: Account<'info, Nullifier>,

    /// Recipient of the unmasked funds. Untrusted — we send lamports
    /// here only after the proof passes.
    /// CHECK: receives lamports; no data assumptions.
    #[account(mut, address = recipient)]
    pub recipient_account: AccountInfo<'info>,

    pub system_program: Program<'info, anchor_lang::system_program::System>,

    /// OPTIONAL — Sunspot verifier program (CPI fallback). When supplied,
    /// the handler routes proof verification through `sunspot::verify_via_sunspot`
    /// instead of the inline `verifier::verify_withdraw_proof` path.
    /// Operators opt in by passing this account; omitting it preserves
    /// the default in-program verifier behaviour. See `src/sunspot.rs`
    /// for the layout assumption (still a stub — confirm before mainnet).
    /// CHECK: validated lazily by the CPI itself; we only forward it.
    pub verifier_program: Option<UncheckedAccount<'info>>,
}

pub fn handler(
    ctx: Context<Withdraw>,
    proof: Vec<u8>,
    root: [u8; 32],
    nullifier_hash: [u8; 32],
    recipient: Pubkey,
    amount: u64,
) -> Result<()> {
    // 1. Cheap pre-checks before the expensive proof verify.
    require!(
        ctx.accounts.tree_state.root_is_known(&root),
        BagsVaultError::UnknownRoot
    );
    require!(
        amount == ctx.accounts.tree_state.denomination,
        BagsVaultError::DenominationMismatch
    );

    // 2. Build the public-input array (must match circuit ordering).
    let public_inputs: [[u8; 32]; NUM_PUBLIC_INPUTS] = [
        root,
        nullifier_hash,
        pubkey_to_field(&recipient),
        u64_to_field(amount),
        pubkey_to_field(&ctx.accounts.relayer.key()),
    ];

    // 3. Groth16 verification. Returns InvalidProof on any failure.
    //    Two routes:
    //      a) operator opted into the Sunspot CPI fallback by passing a
    //         `verifier_program` account → forward to `sunspot::verify_via_sunspot`;
    //      b) default → in-program `groth16-solana` verifier.
    if let Some(verifier_program) = ctx.accounts.verifier_program.as_ref() {
        verify_via_sunspot(
            &verifier_program.to_account_info(),
            &proof,
            &public_inputs,
            &[],
        )?;
    } else {
        verify_withdraw_proof(&proof, &public_inputs)?;
    }

    // 4. Persist nullifier. The Nullifier PDA is created by Anchor's
    //    `init` constraint above — its existence is the spent flag.
    ctx.accounts.nullifier_pda.bump = ctx.bumps.nullifier_pda;

    // 5. Pay the recipient. Native-SOL transfer from the vault PDA.
    //    `try_borrow_mut_lamports` is the canonical Anchor pattern for
    //    PDA-owned native accounts where signer seeds aren't needed
    //    because the program owns the account directly.
    let vault_info = &ctx.accounts.vault;
    let recipient_info = &ctx.accounts.recipient_account;
    **vault_info.try_borrow_mut_lamports()? = vault_info
        .lamports()
        .checked_sub(amount)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;
    **recipient_info.try_borrow_mut_lamports()? = recipient_info
        .lamports()
        .checked_add(amount)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;

    let clock = Clock::get()?;
    emit!(WithdrawEvent {
        nullifier_hash,
        recipient,
        amount,
        timestamp: clock.unix_timestamp,
    });

    Ok(())
}
