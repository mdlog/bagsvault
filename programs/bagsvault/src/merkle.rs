//! Incremental BN254-Poseidon Merkle tree.
//!
//! The on-chain tree mirrors the off-chain Noir circuit's hashing exactly
//! — each non-leaf node is `Poseidon(left, right)` over BN254 — so a
//! commitment inserted by `instructions::deposit` produces the same root
//! the prover sees client-side.
//!
//! Storage strategy is the standard "Tornado-style" incremental tree:
//! we don't store leaves on chain, only `MERKLE_TREE_DEPTH` filled
//! sub-tree roots and a ring buffer of recent computed roots. Insertion
//! cost is O(depth) hashes per deposit, independent of tree population.

use anchor_lang::prelude::*;
use light_poseidon::{Poseidon, PoseidonBytesHasher};
use ark_bn254::Fr;

use crate::errors::BagsVaultError;
use crate::state::{MerkleTreeState, MERKLE_TREE_DEPTH, ROOT_HISTORY_SIZE};

/// Hard-coded sub-tree zero values for an empty tree. `ZERO_VALUES[i]`
/// is the root of an all-zero sub-tree at level `i`. They're computed
/// once with the same Poseidon parameters used by the Noir circuit so
/// the off-chain prover and on-chain verifier agree on the empty-leaf
/// representation.
///
/// We pre-compute lazily (inside a `static` once-cell) the first time
/// the program initialises a pool — generating them at compile time
/// would require a const Poseidon implementation we don't have.
fn zero_values() -> [[u8; 32]; MERKLE_TREE_DEPTH] {
    let mut hasher = Poseidon::<Fr>::new_circom(2).expect("poseidon init");
    let mut current = [0u8; 32];
    let mut levels = [[0u8; 32]; MERKLE_TREE_DEPTH];
    for level in levels.iter_mut() {
        *level = current;
        let next = hasher
            .hash_bytes_be(&[&current, &current])
            .expect("zero-leaf poseidon hash");
        current = next;
    }
    levels
}

/// Initialise an empty tree's `filled_subtrees` array. Called once from
/// `instructions::initialize`.
pub fn empty_filled_subtrees() -> [[u8; 32]; MERKLE_TREE_DEPTH] {
    zero_values()
}

/// Initial root for an empty tree of `MERKLE_TREE_DEPTH` levels.
pub fn empty_root() -> [u8; 32] {
    let mut hasher = Poseidon::<Fr>::new_circom(2).expect("poseidon init");
    let mut current = [0u8; 32];
    for _ in 0..MERKLE_TREE_DEPTH {
        current = hasher
            .hash_bytes_be(&[&current, &current])
            .expect("zero-tree poseidon hash");
    }
    current
}

/// Insert `leaf` (the commitment) into `state`'s incremental tree and
/// push the resulting root onto the history buffer. Mutates state in
/// place. Returns the new root for downstream emission.
pub fn insert(state: &mut MerkleTreeState, leaf: [u8; 32]) -> Result<[u8; 32]> {
    let mut current_index: usize = state
        .commitment_count
        .try_into()
        .map_err(|_| error!(BagsVaultError::TreeFull))?;
    if current_index >= 1usize << MERKLE_TREE_DEPTH {
        return err!(BagsVaultError::TreeFull);
    }

    let zeros = zero_values();
    let mut hasher = Poseidon::<Fr>::new_circom(2).map_err(|_| error!(BagsVaultError::TreeFull))?;
    let mut current_hash = leaf;

    for level in 0..MERKLE_TREE_DEPTH {
        let (left, right) = if current_index % 2 == 0 {
            // Even index: this node is on the left, sibling is the
            // pre-computed empty sub-tree root for this level. Cache the
            // current hash so the next deposit at this index level can
            // pair with it.
            state.filled_subtrees[level] = current_hash;
            (current_hash, zeros[level])
        } else {
            // Odd index: pair with the cached left sibling.
            (state.filled_subtrees[level], current_hash)
        };
        current_hash = hasher
            .hash_bytes_be(&[&left, &right])
            .map_err(|_| error!(BagsVaultError::TreeFull))?;
        current_index /= 2;
    }

    // Push onto the rolling root window. `root_cursor` points at the
    // *next* slot to overwrite; we wrap mod ROOT_HISTORY_SIZE.
    let cursor = state.root_cursor as usize % ROOT_HISTORY_SIZE;
    state.roots[cursor] = current_hash;
    state.root_cursor = ((cursor + 1) % ROOT_HISTORY_SIZE) as u8;
    state.commitment_count = state
        .commitment_count
        .checked_add(1)
        .ok_or_else(|| error!(BagsVaultError::TreeFull))?;

    Ok(current_hash)
}
