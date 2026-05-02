//! GENERATED — DO NOT EDIT BY HAND.
//!
//! Run `python backend/scripts/build_vk.py all` after changing the
//! circuit (`circuits/bagsvault_withdraw/src/main.nr`) to regenerate
//! these constants from a fresh trusted-setup ceremony.
//!
//! See `circuits/bagsvault_withdraw/README.md` for the operator runbook
//! and the toxic-waste warning.
//!
//! Byte layout (matches `groth16-solana 0.0.3`'s `Groth16Verifyingkey`):
//!   * `vk_alpha_g1`  — BN254 G1 element, 64 bytes (compressed BE: x ‖ y).
//!   * `vk_beta_g2`   — BN254 G2 element, 128 bytes. Light Protocol
//!     convention: each Fp2 coordinate is concatenated then reversed,
//!     producing `[c1 ‖ c0]` per coordinate (i.e. swapped Fp2 index
//!     order vs. snarkjs/circom JSON). The reference parser is
//!     `groth16-solana/parse_vk_to_rust.js` — `build_vk.py convert`
//!     mirrors that exact transformation.
//!   * `vk_gamma_g2`  — same encoding as `vk_beta_g2`.
//!   * `vk_delta_g2`  — same encoding as `vk_beta_g2`.
//!   * `vk_ic[i]`     — G1 element, 64 bytes; one entry per public
//!     input plus one for the constant term, so
//!     `VK_IC.len() == NUM_PUBLIC_INPUTS + 1`.
//!
//! These zeros are the post-checkout placeholder. They cause the
//! Groth16 pairing check to fail for every proof, which is the
//! intended fail-closed behaviour until an operator runs the
//! ceremony.

/// Number of public inputs the circuit exposes. Mirrored in
/// `verifier.rs` so the Rust unit test there can detect a circuit
/// edit that drifts away from the regenerated VK.
pub const NUM_PUBLIC_INPUTS: usize = 5;

/// `vk_alpha_g1` (G1, 64 bytes BE-compressed).
pub const VK_ALPHA_G1: [u8; 64] = [0u8; 64];

/// `vk_beta_g2` (G2, 128 bytes; see module-level note on Fp2 swap).
pub const VK_BETA_G2: [u8; 128] = [0u8; 128];

/// `vk_gamma_g2` (G2, 128 bytes; see module-level note on Fp2 swap).
pub const VK_GAMMA_G2: [u8; 128] = [0u8; 128];

/// `vk_delta_g2` (G2, 128 bytes; see module-level note on Fp2 swap).
pub const VK_DELTA_G2: [u8; 128] = [0u8; 128];

/// `vk_ic` table. Length must be `NUM_PUBLIC_INPUTS + 1`; this
/// invariant is asserted by a unit test in `verifier.rs`.
pub const VK_IC: [[u8; 64]; NUM_PUBLIC_INPUTS + 1] =
    [[0u8; 64]; NUM_PUBLIC_INPUTS + 1];
