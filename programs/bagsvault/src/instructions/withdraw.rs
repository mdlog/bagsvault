//! Withdrawal instructions — splits the original `withdraw` into:
//!
//!   * `withdraw_sol` — pays out via direct lamport mutation on the
//!     vault PDA. Equivalent to the original `withdraw` ix and is
//!     re-exported under that name from `lib.rs` for backward compat.
//!   * `withdraw_spl` — pays out via `anchor_spl::token::transfer` with
//!     the vault PDA signing the CPI using its `[b"vault", mint]` seeds.
//!
//! The Groth16 verification + nullifier-PDA-init prelude lives in
//! `core::verify_and_record` so both variants share the same cryptographic
//! contract — including the `fee_bps` binding (public input #5) that
//! prevents a malicious relayer from front-running with a different cut.
//! The lamport / SPL transfer paths in each handler then split the
//! payout between recipient and relayer.
//!
//! Sunspot CPI fallback: each variant exposes an OPTIONAL trailing
//! `verifier_program` account. When supplied, `core::verify_and_record`
//! routes proof verification through `sunspot::verify_via_sunspot`;
//! otherwise the inline `groth16-solana` path runs.

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer as SplTransfer};

use crate::errors::BagsVaultError;
use crate::state::{MerkleTreeState, Nullifier, WithdrawEvent};
use crate::sunspot::verify_via_sunspot;
use crate::verifier::{
    pubkey_to_field, u64_to_field, verify_withdraw_proof, NUM_PUBLIC_INPUTS,
};

/// Compute the relayer cut and recipient amount for a withdrawal of
/// `amount` lamports/units against a pool advertising `fee_bps` bps.
/// `u128` multiplication keeps the math correct over the full `u64`
/// range without overflow.
pub(crate) fn split_payout(amount: u64, fee_bps: u16) -> Result<(u64, u64)> {
    let relayer_cut: u64 = ((amount as u128)
        .checked_mul(fee_bps as u128)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?
        / 10_000u128) as u64;
    let recipient_amount = amount
        .checked_sub(relayer_cut)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;
    Ok((recipient_amount, relayer_cut))
}

// ---------------------------------------------------------------------------
// Shared verification + nullifier-record prelude.
// ---------------------------------------------------------------------------
pub(crate) mod core {
    use super::*;

    /// Run the cheap pre-checks, build the 6-element public-input array,
    /// verify the Groth16 proof, and seal the nullifier PDA.
    ///
    /// Caller is responsible for the actual fund movement (lamports vs
    /// SPL transfer). On success the function emits the `WithdrawEvent`.
    ///
    /// `sunspot_verifier`: when `Some(_)`, verification is delegated to
    /// the Sunspot CPI program at that address; when `None`, the inline
    /// `groth16-solana` verifier runs.
    ///
    /// `fee_bps` is read from the pool state by the caller and bound
    /// into public input #5 — the off-chain prover MUST commit to the
    /// same value the pool advertises, otherwise a malicious relayer
    /// could replay the proof against a pool with a different cut.
    pub fn verify_and_record(
        tree_state: &MerkleTreeState,
        nullifier_pda: &mut Account<Nullifier>,
        nullifier_pda_bump: u8,
        relayer_pubkey: Pubkey,
        proof: &[u8],
        root: [u8; 32],
        nullifier_hash: [u8; 32],
        recipient: Pubkey,
        amount: u64,
        sunspot_verifier: Option<&AccountInfo<'_>>,
    ) -> Result<()> {
        // 1. Cheap pre-checks before the expensive proof verify.
        require!(
            tree_state.root_is_known(&root),
            BagsVaultError::UnknownRoot
        );
        require!(
            amount == tree_state.denomination,
            BagsVaultError::DenominationMismatch
        );

        // 2. Build the public-input array (must match circuit ordering).
        let public_inputs: [[u8; 32]; NUM_PUBLIC_INPUTS] = [
            root,
            nullifier_hash,
            pubkey_to_field(&recipient),
            u64_to_field(amount),
            pubkey_to_field(&relayer_pubkey),
            u64_to_field(tree_state.relayer_fee_bps as u64),
        ];

        // 3. Groth16 verification. Two routes:
        //    a) operator opted into the Sunspot CPI fallback by passing a
        //       `verifier_program` account → forward to `sunspot::verify_via_sunspot`;
        //    b) default → in-program `groth16-solana` verifier.
        if let Some(verifier_program) = sunspot_verifier {
            verify_via_sunspot(verifier_program, proof, &public_inputs, &[])?;
        } else {
            verify_withdraw_proof(proof, &public_inputs)?;
        }

        // 4. Persist nullifier. Anchor's `init` constraint already
        //    rejected the tx if the PDA pre-existed.
        nullifier_pda.bump = nullifier_pda_bump;

        // 5. Emit. Funds-movement happens in the variant handler.
        let clock = Clock::get()?;
        emit!(WithdrawEvent {
            nullifier_hash,
            recipient,
            amount,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Native-SOL withdrawal
// ---------------------------------------------------------------------------
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
        constraint = tree_state.token_mint == anchor_lang::solana_program::system_program::ID
            @ BagsVaultError::DenominationMismatch,
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
    // 1-4. Shared verification + nullifier-init + event emission.
    let sunspot_account = ctx
        .accounts
        .verifier_program
        .as_ref()
        .map(|v| v.to_account_info());
    core::verify_and_record(
        &ctx.accounts.tree_state,
        &mut ctx.accounts.nullifier_pda,
        ctx.bumps.nullifier_pda,
        ctx.accounts.relayer.key(),
        &proof,
        root,
        nullifier_hash,
        recipient,
        amount,
        sunspot_account.as_ref(),
    )?;

    // 5. Split the lamport payout between recipient and relayer.
    let fee_bps = ctx.accounts.tree_state.relayer_fee_bps;
    let (recipient_amount, relayer_cut) = split_payout(amount, fee_bps)?;

    // 6. Move lamports out of the vault PDA. `try_borrow_mut_lamports`
    //    is the canonical Anchor pattern for PDA-owned native accounts.
    let vault_info = &ctx.accounts.vault;
    let recipient_info = &ctx.accounts.recipient_account;
    let relayer_info = ctx.accounts.relayer.to_account_info();

    **vault_info.try_borrow_mut_lamports()? = vault_info
        .lamports()
        .checked_sub(amount)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;
    **recipient_info.try_borrow_mut_lamports()? = recipient_info
        .lamports()
        .checked_add(recipient_amount)
        .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;
    if relayer_cut > 0 {
        **relayer_info.try_borrow_mut_lamports()? = relayer_info
            .lamports()
            .checked_add(relayer_cut)
            .ok_or_else(|| error!(BagsVaultError::InvalidProof))?;
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// SPL-token withdrawal
// ---------------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(
    proof: Vec<u8>,
    root: [u8; 32],
    nullifier_hash: [u8; 32],
    recipient: Pubkey,
    amount: u64,
)]
pub struct WithdrawSpl<'info> {
    #[account(mut)]
    pub relayer: Signer<'info>,

    /// Relayer's ATA — receives the relayer cut. Owner must be the
    /// relayer signer to keep fee accounting honest.
    #[account(
        mut,
        constraint = relayer_token_account.mint == tree_state.token_mint
            @ BagsVaultError::DenominationMismatch,
        constraint = relayer_token_account.owner == relayer.key()
            @ BagsVaultError::Unauthorized,
    )]
    pub relayer_token_account: Account<'info, TokenAccount>,

    /// Vault PDA — authority over the vault's ATA.
    #[account(
        mut,
        seeds = [b"vault", tree_state.token_mint.as_ref()],
        bump,
    )]
    /// CHECK: PDA used as the SPL transfer authority.
    pub vault: AccountInfo<'info>,

    /// Vault's token account (source of the SPL transfer).
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
        constraint = tree_state.token_mint != anchor_lang::solana_program::system_program::ID
            @ BagsVaultError::DenominationMismatch,
    )]
    pub tree_state: Account<'info, MerkleTreeState>,

    #[account(
        init,
        payer = relayer,
        space = 8 + Nullifier::SIZE,
        seeds = [Nullifier::SEED_PREFIX, nullifier_hash.as_ref()],
        bump,
    )]
    pub nullifier_pda: Account<'info, Nullifier>,

    /// Recipient pubkey — pinned by the proof. The actual SPL transfer
    /// targets `recipient_token_account`, but we still require this
    /// account to be present so the IDL layout matches the SOL variant.
    /// CHECK: address-checked by the proof binding; not dereferenced here.
    #[account(address = recipient)]
    pub recipient_account: AccountInfo<'info>,

    /// Recipient's token account for `tree_state.token_mint`. Owner must
    /// be the recipient pubkey to prevent payout redirection.
    #[account(
        mut,
        constraint = recipient_token_account.mint == tree_state.token_mint
            @ BagsVaultError::DenominationMismatch,
        constraint = recipient_token_account.owner == recipient
            @ BagsVaultError::Unauthorized,
    )]
    pub recipient_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, anchor_lang::system_program::System>,

    /// OPTIONAL — Sunspot verifier program (CPI fallback). Same semantics
    /// as the SOL variant: present → CPI dispatch, absent → in-program.
    /// CHECK: forwarded to the CPI; not dereferenced here.
    pub verifier_program: Option<UncheckedAccount<'info>>,
}

pub fn handler_spl(
    ctx: Context<WithdrawSpl>,
    proof: Vec<u8>,
    root: [u8; 32],
    nullifier_hash: [u8; 32],
    recipient: Pubkey,
    amount: u64,
) -> Result<()> {
    // 1-4. Shared verification + nullifier-init + event emission.
    let sunspot_account = ctx
        .accounts
        .verifier_program
        .as_ref()
        .map(|v| v.to_account_info());
    core::verify_and_record(
        &ctx.accounts.tree_state,
        &mut ctx.accounts.nullifier_pda,
        ctx.bumps.nullifier_pda,
        ctx.accounts.relayer.key(),
        &proof,
        root,
        nullifier_hash,
        recipient,
        amount,
        sunspot_account.as_ref(),
    )?;

    // 5. Split the SPL payout between recipient and relayer.
    let fee_bps = ctx.accounts.tree_state.relayer_fee_bps;
    let (recipient_amount, relayer_cut) = split_payout(amount, fee_bps)?;

    let token_mint = ctx.accounts.tree_state.token_mint;
    let vault_bump = ctx.bumps.vault;
    let vault_seeds: &[&[u8]] = &[b"vault", token_mint.as_ref(), &[vault_bump]];
    let signer_seeds: &[&[&[u8]]] = &[vault_seeds];

    // 6a. Recipient transfer.
    let cpi_accounts = SplTransfer {
        from: ctx.accounts.vault_token_account.to_account_info(),
        to: ctx.accounts.recipient_token_account.to_account_info(),
        authority: ctx.accounts.vault.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::transfer(cpi_ctx, recipient_amount)?;

    // 6b. Relayer cut. Skip the CPI when the cut is 0 to save compute.
    if relayer_cut > 0 {
        let fee_accounts = SplTransfer {
            from: ctx.accounts.vault_token_account.to_account_info(),
            to: ctx.accounts.relayer_token_account.to_account_info(),
            authority: ctx.accounts.vault.to_account_info(),
        };
        let fee_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            fee_accounts,
            signer_seeds,
        );
        token::transfer(fee_ctx, relayer_cut)?;
    }

    Ok(())
}
