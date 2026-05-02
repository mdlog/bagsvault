//! Fee Share V2 CPI scaffold.
//!
//! Bags' Fee Share V2 program (`FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`)
//! is the on-chain primitive that distributes creator-token fees. BagsVault
//! registers its vault PDA as a recipient so creator fees can flow into
//! the privacy pool directly, anonymising the receiving wallet.
//!
//! NOTE on the wire format
//! -----------------------
//! The Fee Share V2 instruction layout is **not publicly documented in
//! this repo**. The constants below encode an assumed Anchor-style ix:
//!
//!   discriminator(8) || recipient: Pubkey(32) || bps: u16(2)
//!
//! The discriminator is a placeholder; the real value must be confirmed
//! against the on-chain program before this CPI lands on mainnet.
//! Search inline for `TODO(fee-share)` to find the substitution points.

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{instruction::Instruction, program::invoke_signed};

use crate::errors::BagsVaultError;

/// Bags Fee Share V2 program ID. Source: `docs/arsitektur-sistem.md`
/// section 2.B and Bags docs (`https://docs.bags.fm/principles/program-ids`).
pub const FEE_SHARE_V2_PROGRAM_ID: Pubkey =
    anchor_lang::solana_program::pubkey!("FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK");

/// Anchor-style sighash for the `register_recipient` ix on Fee Share V2.
///
/// TODO(fee-share): confirm against on-chain program when public docs land.
/// The placeholder is `sha256("global:register_recipient")[..8]`. If the
/// program uses a different naming or non-Anchor framing (e.g. raw u8
/// instruction tag) replace this constant accordingly — the rest of the
/// CPI plumbing stays the same.
pub const REGISTER_RECIPIENT_DISCRIMINATOR: [u8; 8] = [
    // sha256("global:register_recipient")[..8]
    0xc1, 0x4f, 0x40, 0x95, 0xa3, 0x4c, 0x37, 0x21,
];

/// Build and dispatch the `register_recipient` CPI.
///
/// `recipient` is the BagsVault vault PDA. `bps` is the share in basis
/// points. The vault PDA signs the CPI using `[b"vault", token_mint]`
/// seeds — Fee Share V2 verifies the recipient matches the signer
/// (assumed; see TODO above).
pub fn register_fee_share_recipient<'info>(
    fee_share_program: &AccountInfo<'info>,
    recipient: Pubkey,
    bps: u16,
    signer_seeds: &[&[&[u8]]],
    extra_accounts: &[AccountMeta],
    extra_account_infos: &[AccountInfo<'info>],
) -> Result<()> {
    require!(bps <= 10_000, BagsVaultError::DenominationMismatch);

    // Expected layout: [u8; 8] discriminator | Pubkey(32) | u16 LE
    //
    // TODO(fee-share): confirm field order + sighash against the deployed
    // Fee Share V2 program. If the program expects additional context
    // (e.g. config PDA, treasury) callers pass those via `extra_accounts`
    // / `extra_account_infos` so we don't have to re-architect the
    // wrapper.
    let mut data = Vec::with_capacity(8 + 32 + 2);
    data.extend_from_slice(&REGISTER_RECIPIENT_DISCRIMINATOR);
    data.extend_from_slice(recipient.as_ref());
    data.extend_from_slice(&bps.to_le_bytes());

    let ix = Instruction {
        program_id: FEE_SHARE_V2_PROGRAM_ID,
        accounts: extra_accounts.to_vec(),
        data,
    };

    // Build the AccountInfo slice the runtime needs. The fee-share
    // program account itself plus any extras supplied by the caller.
    let mut infos: Vec<AccountInfo<'info>> = Vec::with_capacity(extra_account_infos.len() + 1);
    infos.push(fee_share_program.clone());
    for info in extra_account_infos.iter() {
        infos.push(info.clone());
    }

    invoke_signed(&ix, &infos, signer_seeds)
        .map_err(|_| error!(BagsVaultError::InvalidProof))?;

    Ok(())
}
