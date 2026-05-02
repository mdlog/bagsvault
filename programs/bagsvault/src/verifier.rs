//! Groth16 verification helper for the BagsVault withdrawal proof.
//!
//! The verifying key was generated alongside the Noir circuit at
//! `circuits/bagsvault_withdraw/` (see `circuits/bagsvault_withdraw/README.md`
//! for the ceremony command). The bytes embedded below are placeholders —
//! the build script substitutes them with the real BN254-encoded VK once
//! `nargo` produces it. This keeps the program compileable in a fresh
//! checkout while making the substitution surface explicit.
//!
//! Public-input layout (must match `Prover.toml` ordering in the circuit):
//!   1. `root`            — bytes32 BE, Merkle root committed to by the proof
//!   2. `nullifier_hash`  — bytes32 BE
//!   3. `recipient`       — pubkey, 32 BE bytes (Solana address as field)
//!   4. `amount`          — u64 BE → 32-byte field element
//!   5. `relayer`         — pubkey, 32 BE bytes (anti-frontrunning binding)

use anchor_lang::prelude::*;
use groth16_solana::groth16::Groth16Verifier;

use crate::errors::BagsVaultError;

/// Number of public inputs the circuit exposes.
pub const NUM_PUBLIC_INPUTS: usize = 5;

/// Placeholder verifying key — replace with the trusted-setup output for
/// `bagsvault_withdraw.r1cs`. Sizes match the `groth16-solana` layout:
///   * vk_alpha_g1: 64 bytes
///   * vk_beta_g2:  128 bytes
///   * vk_gamma_g2: 128 bytes
///   * vk_delta_g2: 128 bytes
///   * vk_ic[i]:    64 bytes each (NUM_PUBLIC_INPUTS + 1 entries)
pub const VK_ALPHA_G1: [u8; 64] = [0u8; 64];
pub const VK_BETA_G2: [u8; 128] = [0u8; 128];
pub const VK_GAMMA_G2: [u8; 128] = [0u8; 128];
pub const VK_DELTA_G2: [u8; 128] = [0u8; 128];
pub const VK_IC: [[u8; 64]; NUM_PUBLIC_INPUTS + 1] = [[0u8; 64]; NUM_PUBLIC_INPUTS + 1];

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
