# BagsVault Withdrawal Circuit

Noir circuit (`bagsvault_withdraw`) that produces the Groth16 proof the
on-chain `withdraw` instruction verifies.

## Public inputs (in order)

The order **must** match `programs/bagsvault/src/verifier.rs::NUM_PUBLIC_INPUTS`:

1. `root` — Merkle root committed to by the proof
2. `nullifier_hash` — `poseidon(nullifier, leaf_index)`
3. `recipient` — destination wallet (binds the payout)
4. `amount` — withdrawal denomination (binds to the pool's fixed amount)
5. `relayer` — relayer pubkey (anti-frontrunning)

## Private inputs (witness)

* `nullifier`, `secret` — preimage of the leaf commitment
* `leaf_index` — position in the tree (0..2^20)
* `merkle_path` — 20 sibling hashes from leaf to root
* `is_left` — 20 bits indicating the current node's side at each level

## Build & ceremony

```bash
# Compile the circuit and emit ACIR + proving/verifying keys
nargo check
nargo compile
bb prove -b ./target/bagsvault_withdraw.json -w ./Prover.toml -o ./target/proof
bb write_vk -b ./target/bagsvault_withdraw.json -o ./target/vk

# Convert the verifying key to BN254-encoded bytes for the on-chain
# verifier and substitute them into programs/bagsvault/src/verifier.rs.
# The backend script `backend/scripts/build_vk.py` will do this once
# the ceremony output is available.
```

## Smoke test

Run `nargo test` from this directory to exercise the embedded
`smoke_test` against an empty tree.

## Notes

* The circuit depends on `std::hash::poseidon::bn254` so the on-chain
  Merkle insertion (`programs/bagsvault/src/merkle.rs`) and the off-chain
  prover hash with the **same** parameters.
* `is_left` could be derived from the binary expansion of `leaf_index`,
  but we expose it as an explicit witness to keep the constraint count
  predictable for the trusted-setup phase.
