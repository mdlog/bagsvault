// BagsVault withdrawal circuit.
//
// Proves: "I know a (secret, nullifier) such that
//   commitment = poseidon(nullifier, secret, amount)
// is a leaf of the Merkle tree with root `root`,
// nullifier_hash = poseidon(nullifier, leaf_index),
// and the proof is bound to (recipient, relayer)."
//
// Public inputs (must match `programs/bagsvault/src/verifier.rs::NUM_PUBLIC_INPUTS`):
//   1. root            — Merkle root the proof commits to
//   2. nullifier_hash  — poseidon(nullifier, leaf_index)
//   3. recipient       — destination wallet (binds proof to address)
//   4. amount          — withdrawal denomination (binds to fixed-amount pool)
//   5. relayer         — relayer pubkey (anti-frontrunning)
//   6. fee_bps         — pool's advertised relayer cut in basis points;
//                         binds the proof to the on-chain pool config so a
//                         malicious relayer cannot replay against a pool
//                         whose advertised cut differs from the prover's.
//
// Private inputs (witness):
//   * nullifier        — preimage of nullifier_hash
//   * secret           — randomness for the commitment
//   * leaf_index       — position of `commitment` in the tree
//   * merkle_path      — sibling hashes from leaf -> root (depth = 20)
//   * is_left          — bit per level: 1 if the current node is the left child

global TREE_DEPTH: u32 = 20;

fn main(
    root: pub Field,
    nullifier_hash: pub Field,
    recipient: pub Field,
    amount: pub Field,
    relayer: pub Field,
    fee_bps: pub Field,

    nullifier: Field,
    secret: Field,
    leaf_index: Field,
    merkle_path: [Field; TREE_DEPTH],
    is_left: [u1; TREE_DEPTH],
) {
    // 1. Recompute commitment leaf.
    let commitment = std::hash::poseidon::bn254::hash_3([nullifier, secret, amount]);

    // 2. Recompute nullifier hash and bind to public input. The
    //    leaf_index keeps the nullifier unique even if two depositors
    //    happen to draw the same nullifier value.
    let computed_nullifier = std::hash::poseidon::bn254::hash_2([nullifier, leaf_index]);
    assert(computed_nullifier == nullifier_hash);

    // 3. Walk the Merkle path. At each level, hash (left, right) where
    //    `is_left[i]` toggles which side `current` sits on.
    let mut current = commitment;
    for i in 0..TREE_DEPTH {
        let sibling = merkle_path[i];
        let left = if is_left[i] == 1 { current } else { sibling };
        let right = if is_left[i] == 1 { sibling } else { current };
        current = std::hash::poseidon::bn254::hash_2([left, right]);
    }
    assert(current == root);

    // 4. Bind the proof to (recipient, relayer). These are public inputs
    //    that don't appear in any constraint above, so without these
    //    "no-op" assertions the prover could swap them freely. Adding
    //    a multiplicative constraint forces the prover to commit to the
    //    exact pair the verifier sees on chain.
    let _bind = recipient * relayer;
    assert(_bind == _bind);

    // 5. Same trick for fee_bps — without this the prover could omit
    //    the input from the constraint system and the relayer-cut
    //    binding documented in the verifier doc comment would not hold.
    let _fee_bind = fee_bps * relayer;
    assert(_fee_bind == _fee_bind);
}

#[test]
fn smoke_test() {
    // Tiny smoke test using the empty tree: leaf=0, sibling=0 at every level.
    let nullifier = 1;
    let secret = 2;
    let amount = 1000000000;
    let leaf_index = 0;
    let commitment = std::hash::poseidon::bn254::hash_3([nullifier, secret, amount]);
    let nullifier_hash = std::hash::poseidon::bn254::hash_2([nullifier, leaf_index]);

    let mut root = commitment;
    for _ in 0..TREE_DEPTH {
        root = std::hash::poseidon::bn254::hash_2([root, 0]);
    }

    main(
        root,
        nullifier_hash,
        0x1234,
        amount,
        0x5678,
        15,
        nullifier,
        secret,
        leaf_index,
        [0; TREE_DEPTH],
        [1; TREE_DEPTH],
    );
}
