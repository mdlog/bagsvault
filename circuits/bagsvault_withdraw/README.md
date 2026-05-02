# BagsVault Withdrawal Circuit

Noir circuit (`bagsvault_withdraw`) that produces the Groth16 proof the
on-chain `withdraw` instruction verifies.

## Public inputs (in order)

The order **must** match `programs/bagsvault/src/verifier_vk.rs::NUM_PUBLIC_INPUTS`
and the `Prover.toml` ordering:

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

## Operator runbook — trusted-setup ceremony

These commands rebuild the Groth16 verifying key and substitute it into
the on-chain verifier. **Run them on a build machine that has both
`nargo` and `bb` (Barretenberg) installed.** Read the toxic-waste
warning at the bottom before running on anything but devnet.

### Prerequisites

```bash
# 1. Install Noir + nargo
#    https://noir-lang.org/docs/getting_started/installation
nargo --version       # must be >= 0.31

# 2. Install Barretenberg (bb)
#    https://github.com/AztecProtocol/aztec-packages/tree/master/barretenberg/cpp
bb --version

# 3. Backend deps for the build script (typer is already in
#    backend/requirements.txt).
cd backend && pip install -r requirements.txt
```

### Run the ceremony

From the **repository root**:

```bash
# 1. Compile the circuit (ACIR + bytecode).
python -m scripts.build_vk compile

# 2. Run `bb write_vk` to emit the verifying key (binary + JSON sibling).
python -m scripts.build_vk setup

# 3. Convert the JSON VK into Rust constants and overwrite
#    programs/bagsvault/src/verifier_vk.rs.
python -m scripts.build_vk convert

# Or, end-to-end:
python -m scripts.build_vk all
```

`build_vk.py` lives at `backend/scripts/build_vk.py`; invoke it from
the `backend/` directory (`cd backend && python -m scripts.build_vk all`)
so the package layout resolves. Pass `--ceremony-dir <abs-path>` if your
build machine mounts the repo somewhere unusual.

### How to verify the substitution worked

After `convert` writes the new `verifier_vk.rs`:

1. **Compile the on-chain program.** The unit test in
   `programs/bagsvault/src/verifier.rs` (`vk_ic_table_matches_public_input_count`)
   checks `VK_IC.len() == NUM_PUBLIC_INPUTS + 1`. If the circuit has
   drifted from the VK, this fails at `cargo test --workspace` and the
   substitution is rejected:

   ```bash
   cargo build-sbf --manifest-path programs/bagsvault/Cargo.toml
   cargo test --manifest-path programs/bagsvault/Cargo.toml verifier
   ```

2. **Smoke proof end-to-end.** With `ZK_PROOF_STUB_MODE=false` and
   `nargo` / `bb` on PATH, run:

   ```bash
   cd backend
   python -m scripts.dev_smoke_proof
   ```

   The script prints the proof + public inputs as hex. Submit them to a
   local validator running the deployed program; `verify_withdraw_proof`
   must return `Ok(())`. If verification fails after a fresh ceremony,
   the most likely culprits are (in order):

   * Public-input ordering drift between `main.nr`, `verifier.rs`, and
     `zk_proof_service._render_prover_toml`.
   * Endianness mismatch in `verifier_vk.rs` — see the inline note in
     `backend/scripts/build_vk.py::_encode_g2`.
   * `NUM_PUBLIC_INPUTS` increased without re-running the ceremony.

## Smoke test (circuit only)

Run `nargo test` from this directory to exercise the embedded
`smoke_test` against an empty tree. This does not produce a proof; it
just runs the constraint system on a hand-coded witness.

## Trusted-setup ceremony — toxic-waste warning

Groth16 requires a per-circuit "powers of tau" (PoT) trusted setup. The
random scalar `tau` used to derive the verifying key **must be
destroyed** after the ceremony — anyone who keeps it can forge proofs
indefinitely. A single-machine ceremony embeds `tau` on that machine,
so:

* **Do NOT use the single-machine output for mainnet.** It is fine for
  devnet hackathon demos and for the placeholder zeros that ship in this
  repo (which fail closed on chain — no one can spend).
* **For production, run a multi-party computation (MPC).** Each
  participant adds entropy; as long as one honest participant deletes
  their share, the resulting VK is sound. Coordinate via the
  Aztec / `snarkjs powersoftau` ceremony tooling, archive the
  attestations, and only then run `python -m scripts.build_vk convert`
  against the final VK.
* The on-chain program has no upgrade path for the VK (it's a `pub
  const`). A re-ceremony requires a program redeploy and migration of
  the Merkle state.

## Notes

* The circuit depends on `std::hash::poseidon::bn254` so the on-chain
  Merkle insertion (`programs/bagsvault/src/merkle.rs`) and the off-chain
  prover hash with the **same** parameters.
* `is_left` could be derived from the binary expansion of `leaf_index`,
  but we expose it as an explicit witness to keep the constraint count
  predictable for the trusted-setup phase.
* The placeholder zeros in `programs/bagsvault/src/verifier_vk.rs` make
  `cargo check` pass on a fresh checkout, but every proof is rejected
  by the on-chain verifier until an operator runs the ceremony. This is
  intentional — the program fails closed without a real VK.
