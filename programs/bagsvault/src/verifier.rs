//! Groth16 verification helper for the BagsVault withdrawal proof.
//!
//! The verifying key constants live in the sibling `verifier_vk` module
//! so an operator can drop in the trusted-setup output without touching
//! this file. After running the ceremony (see
//! `circuits/bagsvault_withdraw/README.md`), `backend/scripts/build_vk.py
//! convert` rewrites `verifier_vk.rs` with the real BN254-encoded VK.
//!
//! Public-input layout (must match `Prover.toml` ordering in the
//! circuit):
//!   1. `root`            — bytes32 BE, Merkle root committed to by the proof
//!   2. `nullifier_hash`  — bytes32 BE
//!   3. `recipient`       — pubkey, 32 BE bytes (Solana address as field)
//!   4. `amount`          — u64 BE → 32-byte field element
//!   5. `relayer`         — pubkey, 32 BE bytes (anti-frontrunning binding)
//!   6. `fee_bps`         — u16 cast to u64 → 32-byte field element. Binds
//!                          the proof to the on-chain advertised fee so a
//!                          malicious relayer cannot replay the proof
//!                          against a pool with a different cut.

use anchor_lang::prelude::*;
use groth16_solana::groth16::Groth16Verifier;

use crate::errors::BagsVaultError;
use crate::verifier_vk::{VK_ALPHA_G1, VK_BETA_G2, VK_DELTA_G2, VK_GAMMA_G2, VK_IC};

// Re-export the public-input arity at the path callers already use
// (`crate::verifier::NUM_PUBLIC_INPUTS`). The constant itself lives in
// `verifier_vk.rs` so the build script regenerates it alongside the
// VK byte arrays.
pub use crate::verifier_vk::NUM_PUBLIC_INPUTS;

/// Verify a Groth16 proof against the embedded VK and the supplied public
/// inputs. Returns `Ok(())` only when the proof is valid.
///
/// The proof is laid out as `[a (64) || b (128) || c (64)] = 256 bytes` —
/// the same shape `groth16-solana` consumes.
pub fn verify_withdraw_proof(
    proof_bytes: &[u8],
    public_inputs: &[[u8; 32]; NUM_PUBLIC_INPUTS],
) -> Result<()> {
    if proof_bytes.len() != 256 {
        return err!(BagsVaultError::InvalidProof);
    }
    let mut proof_a = [0u8; 64];
    let mut proof_b = [0u8; 128];
    let mut proof_c = [0u8; 64];
    proof_a.copy_from_slice(&proof_bytes[0..64]);
    proof_b.copy_from_slice(&proof_bytes[64..192]);
    proof_c.copy_from_slice(&proof_bytes[192..256]);

    let mut verifier = Groth16Verifier::new(
        &proof_a,
        &proof_b,
        &proof_c,
        public_inputs,
        &VK_ALPHA_G1,
        &VK_BETA_G2,
        &VK_GAMMA_G2,
        &VK_DELTA_G2,
        &VK_IC,
    )
    .map_err(|_| error!(BagsVaultError::InvalidProof))?;

    verifier
        .verify()
        .map_err(|_| error!(BagsVaultError::InvalidProof))?;

    Ok(())
}

/// Pack a u64 into a 32-byte big-endian field element so it matches the
/// circuit's public-input encoding.
pub fn u64_to_field(value: u64) -> [u8; 32] {
    let mut buf = [0u8; 32];
    buf[24..32].copy_from_slice(&value.to_be_bytes());
    buf
}

/// Pack a Solana pubkey directly. Public keys are 32 bytes; we treat them
/// as a field element. The circuit reduces mod r, so any high bits
/// flipped above the BN254 field modulus must be zeroed by the prover —
/// off-chain code in `backend/app/services/zk_proof_service.py` handles
/// this masking.
pub fn pubkey_to_field(key: &Pubkey) -> [u8; 32] {
    key.to_bytes()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `vk_ic` must have exactly `NUM_PUBLIC_INPUTS + 1` entries (one
    /// per input plus a constant). If a future circuit edit changes the
    /// public-input count, the operator must re-run
    /// `python backend/scripts/build_vk.py all` to regenerate
    /// `verifier_vk.rs` — this test fails compilation if they forget.
    #[test]
    fn vk_ic_table_matches_public_input_count() {
        assert_eq!(VK_IC.len(), NUM_PUBLIC_INPUTS + 1);
    }

    /// Sanity: the proof-bytes splitter rejects any length that isn't
    /// the exact 256-byte Groth16 layout.
    #[test]
    fn rejects_proof_with_wrong_length() {
        let public_inputs = [[0u8; 32]; NUM_PUBLIC_INPUTS];
        assert!(verify_withdraw_proof(&[0u8; 128], &public_inputs).is_err());
        assert!(verify_withdraw_proof(&[0u8; 257], &public_inputs).is_err());
    }
}
