//! Sunspot Groth16-verifier CPI fallback.
//!
//! Background: BagsVault verifies withdrawal proofs **in-program** by default
//! (see `verifier.rs` — uses the `groth16-solana` crate). The architecture
//! doc Section 2.A and Section 3 Phase 2 step 3 also mention an alternative
//! integration path: CPI into the standalone Sunspot verifier program from
//! [catmcgee/noir-solana-private-transfers](https://github.com/catmcgee/noir-solana-private-transfers).
//!
//! Operators opt into this path by passing a `verifier_program` account to
//! `withdraw`. When present, [`verify_via_sunspot`] is invoked instead of
//! the inline path. This keeps the in-program verifier as the default
//! (simpler, no extra programs to deploy) while preserving the documented
//! escape hatch for environments that already standardise on Sunspot.
//!
//! # STATUS: STUB
//!
//! Sunspot's exact instruction layout is **outside this repo's source**.
//! The constants below are placeholders — DO NOT ship to mainnet without
//! confirming against the deployed Sunspot program. See:
//!   * <https://github.com/catmcgee/noir-solana-private-transfers>
//!   * any future Sunspot SDK / IDL release.
//!
//! Expected layout (assumption — verify before mainnet):
//!     [u8; 8]  sighash         (anchor-style discriminator)
//!     u32 LE   proof_len
//!     [u8]     proof bytes     (256 for groth16-solana shape: a 64 || b 128 || c 64)
//!     [u8; 32] public_input    (× NUM_PUBLIC_INPUTS, in circuit order)

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    instruction::{AccountMeta, Instruction},
    program::invoke,
};

use crate::errors::BagsVaultError;
use crate::verifier::NUM_PUBLIC_INPUTS;

/// Anchor-style sighash for the Sunspot `verify` entry. **Placeholder** —
/// the real value would be `sighash("global", "verify")[..8]` against the
/// upstream Sunspot program. Filled with zeros so any operator who flips
/// this on without confirming the layout fails fast (the CPI returns
/// `InstructionError`, which we map to `InvalidProof`).
///
/// TODO(sunspot): confirm against on-chain program when public docs land.
pub const SUNSPOT_VERIFY_DISCRIMINATOR: [u8; 8] = [0u8; 8];

/// CPI into the Sunspot verifier program with the BagsVault withdrawal
/// proof. Returns `Ok(())` only when Sunspot's verify call succeeds; any
/// upstream error is mapped to [`BagsVaultError::InvalidProof`] so the
/// caller never has to discriminate between Sunspot's internal error
/// codes and BagsVault's.
///
/// `verifier_program` is the on-chain address of the deployed Sunspot
/// program. It is passed as an *account* (not just a key) so the CPI
/// machinery has the actual `AccountInfo` it needs to invoke; callers in
/// `instructions::withdraw` thread it through from the instruction's
/// optional `verifier_program` account.
///
/// `extra_accounts` is reserved for future use — Sunspot may require
/// additional read-only accounts (e.g. a VK PDA) once the upstream layout
/// is finalised. Today we pass an empty slice and document the gap.
pub fn verify_via_sunspot<'info>(
    verifier_program: &AccountInfo<'info>,
    proof_bytes: &[u8],
    public_inputs: &[[u8; 32]; NUM_PUBLIC_INPUTS],
    extra_accounts: &[AccountInfo<'info>],
) -> Result<()> {
    // 1. Build the instruction data exactly as documented at the top of
    //    this file. Keeping the layout inline (vs a #[derive] struct)
    //    makes the assumption auditable in one place.
    let mut data = Vec::with_capacity(8 + 4 + proof_bytes.len() + 32 * NUM_PUBLIC_INPUTS);
    data.extend_from_slice(&SUNSPOT_VERIFY_DISCRIMINATOR);
    data.extend_from_slice(&(proof_bytes.len() as u32).to_le_bytes());
    data.extend_from_slice(proof_bytes);
    for input in public_inputs.iter() {
        data.extend_from_slice(input);
    }

    // 2. Account metas. Sunspot is a pure verifier — no signer needed,
    //    no writes — so all metas are read-only. If the upstream program
    //    later requires a writeable PDA (e.g. a verify-counter), this
    //    block grows accordingly.
    let mut metas: Vec<AccountMeta> = extra_accounts
        .iter()
        .map(|ai| AccountMeta::new_readonly(*ai.key, false))
        .collect();
    // The verifier program account itself is the executable target; some
    // verifier ABIs also require it to appear in the account list. Pass
    // it through readonly so the CPI machinery can resolve it.
    metas.push(AccountMeta::new_readonly(*verifier_program.key, false));

    let ix = Instruction {
        program_id: *verifier_program.key,
        accounts: metas,
        data,
    };

    // 3. Account-info slice for `invoke`. Must include the program's own
    //    AccountInfo plus everything we listed in `metas`.
    let mut infos: Vec<AccountInfo<'info>> = extra_accounts.to_vec();
    infos.push(verifier_program.clone());

    // 4. CPI. Map any failure (program returned non-Ok, account
    //    serialization, signer privilege escalation, etc.) to
    //    InvalidProof — operators see a single, semantic error.
    invoke(&ix, &infos).map_err(|_| error!(BagsVaultError::InvalidProof))?;
    Ok(())
}
