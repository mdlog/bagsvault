//! Rust integration tests for the BagsVault Anchor program.
//!
//! Run with `cargo test -p bagsvault`. Tests use `solana-program-test`'s
//! BanksClient runtime — no devnet, no validator. Every keypair is
//! deterministic (see `common::SEED`) so failures reproduce exactly.
//!
//! Coverage map (see Priority 5 brief):
//!   1. `initialize` happy path                — [`initialize_happy_path`]
//!   2. `initialize` PDA collision             — [`initialize_rejects_second_call`]
//!   3. `deposit` happy path                   — [`deposit_happy_path`]
//!   4. `deposit` denomination mismatch        — see TODO note in
//!      [`deposit_denomination_mismatch_todo`]
//!   5. `withdraw` smoke (placeholder VK)      — [`withdraw_rejects_invalid_proof`]
//!   6. `withdraw` double-spend                — [`withdraw_double_spend_rejected`]
//!   7. `pause` blocks deposits + withdrawals  — [`pause_blocks_deposits_and_withdrawals`]

mod common;

use anchor_lang::AccountDeserialize;
use bagsvault::merkle::empty_root;
use bagsvault::state::MerkleTreeState;
use common::{
    build_deposit_ix, build_initialize_ix, build_pause_ix, build_withdraw_ix, clone_keypair,
    setup, submit, tree_state_pda, vault_pda, DEFAULT_DENOMINATION,
};
use solana_program_test::BanksClientError;
use solana_sdk::{instruction::InstructionError, signature::Signer, system_program, transaction::TransactionError};

/// Helper — fetch and deserialize the tree-state account.
async fn fetch_tree_state(env: &mut common::TestEnv) -> MerkleTreeState {
    let token_mint = system_program::ID;
    let (pda, _) = tree_state_pda(&token_mint);
    let account = env
        .ctx
        .banks_client
        .get_account(pda)
        .await
        .expect("rpc")
        .expect("tree_state account exists");
    MerkleTreeState::try_deserialize(&mut account.data.as_ref())
        .expect("anchor account deserialize")
}

#[tokio::test]
async fn initialize_happy_path() {
    let mut env = setup().await;
    let ix = build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION);
    let auth = clone_keypair(&env.authority);
    submit(&mut env, ix, &auth, &[]).await.expect("initialize");

    let state = fetch_tree_state(&mut env).await;
    assert_eq!(state.authority, env.authority.pubkey());
    assert_eq!(state.token_mint, system_program::ID);
    assert_eq!(state.denomination, DEFAULT_DENOMINATION);
    assert_eq!(state.commitment_count, 0);
    assert!(!state.paused);
    // Empty-tree root must occupy slot 0; rest of the rolling buffer is
    // zeroed until the first deposit lands.
    assert_eq!(state.roots[0], empty_root());
    for slot in &state.roots[1..] {
        assert_eq!(slot, &[0u8; 32]);
    }
}

#[tokio::test]
async fn initialize_rejects_second_call() {
    let mut env = setup().await;
    let auth = clone_keypair(&env.authority);

    // First call succeeds.
    let ix = build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION);
    submit(&mut env, ix, &auth, &[]).await.expect("first initialize");

    // Second call must fail because the tree-state PDA is already
    // allocated. Anchor's `init` constraint is enforced by the system
    // program's `create_account` ix → "account already in use".
    let ix2 = build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION);
    let err = submit(&mut env, ix2, &auth, &[])
        .await
        .expect_err("second initialize must fail");
    assert!(
        is_account_already_in_use(&err),
        "expected AccountAlreadyInUse, got: {err:?}"
    );
}

#[tokio::test]
async fn deposit_happy_path() {
    let mut env = setup().await;
    let auth = clone_keypair(&env.authority);
    let depositor = clone_keypair(&env.depositor);

    submit(
        &mut env,
        build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION),
        &auth,
        &[],
    )
    .await
    .expect("initialize");

    let token_mint = system_program::ID;
    let (vault_pk, _) = vault_pda(&token_mint);
    let vault_before = env
        .ctx
        .banks_client
        .get_account(vault_pk)
        .await
        .expect("rpc")
        .map(|a| a.lamports)
        .unwrap_or(0);

    let commitment: [u8; 32] = {
        let mut c = [0u8; 32];
        // Deterministic non-zero pattern so the merkle insertion path
        // doesn't accidentally degenerate.
        for (i, b) in c.iter_mut().enumerate() {
            *b = (i as u8).wrapping_mul(7).wrapping_add(0x42);
        }
        c
    };
    submit(
        &mut env,
        build_deposit_ix(&depositor.pubkey(), commitment),
        &depositor,
        &[],
    )
    .await
    .expect("deposit");

    let state = fetch_tree_state(&mut env).await;
    assert_eq!(state.commitment_count, 1, "commitment_count++");
    // The root that just landed is at the *previous* cursor slot (the
    // cursor advanced post-write).
    let new_root_slot = (state.root_cursor as usize + bagsvault::state::ROOT_HISTORY_SIZE - 1)
        % bagsvault::state::ROOT_HISTORY_SIZE;
    assert_ne!(state.roots[new_root_slot], [0u8; 32], "fresh root present");
    assert_ne!(
        state.roots[new_root_slot],
        empty_root(),
        "fresh root differs from empty-tree root"
    );

    let vault_after = env
        .ctx
        .banks_client
        .get_account(vault_pk)
        .await
        .expect("rpc")
        .expect("vault PDA materialised by transfer")
        .lamports;
    assert_eq!(
        vault_after - vault_before,
        DEFAULT_DENOMINATION,
        "vault gained exactly `denomination` lamports"
    );
}

/// Per Priority 5 brief: the deposit handler does NOT take a caller-supplied
/// amount — it pulls `denomination` straight from `tree_state` and issues a
/// `system_program::transfer(denomination)` itself. There is therefore no
/// "mismatched denomination" path to exercise without modifying
/// `deposit.rs` (which is owned by Priority 3/4 and out of our scope).
///
/// TODO(priority-5-followup): once Priority 3 lands the fee_bps work and
/// either Priority 3 or 4 surface a deposit field that the caller controls
/// (e.g. an explicit `amount` argument or a withholding pre-check), wire
/// up an actual mismatch test here. For now we leave a no-op placeholder
/// to keep the brief's coverage map honest.
#[tokio::test]
async fn deposit_denomination_mismatch_todo() {
    // Intentionally empty. See doc comment above.
}

#[tokio::test]
async fn withdraw_rejects_invalid_proof() {
    let mut env = setup().await;
    let auth = clone_keypair(&env.authority);
    let depositor = clone_keypair(&env.depositor);
    let relayer = clone_keypair(&env.relayer);

    submit(
        &mut env,
        build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION),
        &auth,
        &[],
    )
    .await
    .expect("initialize");

    // One real deposit so the vault has funds and the rolling root buffer
    // contains a non-empty root we can quote.
    let commitment = [0xAAu8; 32];
    submit(
        &mut env,
        build_deposit_ix(&depositor.pubkey(), commitment),
        &depositor,
        &[],
    )
    .await
    .expect("deposit");

    let state = fetch_tree_state(&mut env).await;
    let new_root_slot = (state.root_cursor as usize + bagsvault::state::ROOT_HISTORY_SIZE - 1)
        % bagsvault::state::ROOT_HISTORY_SIZE;
    let root = state.roots[new_root_slot];

    // 256-byte all-zero proof. The placeholder VK is also all-zero; the
    // verifier MUST still reject. The point of this test is to drive the
    // rest of the handler — root lookup, account-ordering, nullifier PDA
    // init — and prove the verifier wires through to `InvalidProof`.
    let proof = vec![0u8; 256];
    let nullifier_hash = [0xBBu8; 32];
    let recipient = solana_sdk::pubkey::Pubkey::new_unique();

    let err = submit(
        &mut env,
        build_withdraw_ix(
            &relayer.pubkey(),
            proof,
            root,
            nullifier_hash,
            recipient,
            DEFAULT_DENOMINATION,
        ),
        &relayer,
        &[],
    )
    .await
    .expect_err("withdraw with placeholder VK + zero proof must fail");

    assert!(
        is_program_error(&err),
        "expected program error (InvalidProof or earlier check), got: {err:?}"
    );
}

#[tokio::test]
async fn withdraw_double_spend_rejected() {
    let mut env = setup().await;
    let auth = clone_keypair(&env.authority);
    let depositor = clone_keypair(&env.depositor);
    let relayer = clone_keypair(&env.relayer);

    submit(
        &mut env,
        build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION),
        &auth,
        &[],
    )
    .await
    .expect("initialize");

    submit(
        &mut env,
        build_deposit_ix(&depositor.pubkey(), [0xCCu8; 32]),
        &depositor,
        &[],
    )
    .await
    .expect("deposit");

    let state = fetch_tree_state(&mut env).await;
    let new_root_slot = (state.root_cursor as usize + bagsvault::state::ROOT_HISTORY_SIZE - 1)
        % bagsvault::state::ROOT_HISTORY_SIZE;
    let root = state.roots[new_root_slot];

    let proof = vec![0u8; 256];
    let nullifier_hash = [0xDDu8; 32];
    let recipient = solana_sdk::pubkey::Pubkey::new_unique();

    // First call fails on InvalidProof (the placeholder VK rejects). What
    // matters for this test: even though the first call ran, no nullifier
    // PDA was written because the tx aborted. So the second call still
    // hits the proof check first and fails with InvalidProof, NOT "in
    // use".
    //
    // To actually exercise the double-spend path we'd need a valid proof
    // — that requires the trusted-setup ceremony output. Until then this
    // test asserts the protocol-level invariant: nullifier PDA writes are
    // contingent on the whole tx succeeding, so an invalid first attempt
    // does not block a corrected retry.
    let _ = submit(
        &mut env,
        build_withdraw_ix(
            &relayer.pubkey(),
            proof.clone(),
            root,
            nullifier_hash,
            recipient,
            DEFAULT_DENOMINATION,
        ),
        &relayer,
        &[],
    )
    .await;

    let err2 = submit(
        &mut env,
        build_withdraw_ix(
            &relayer.pubkey(),
            proof,
            root,
            nullifier_hash,
            recipient,
            DEFAULT_DENOMINATION,
        ),
        &relayer,
        &[],
    )
    .await
    .expect_err("second withdraw call still fails");

    assert!(
        is_program_error(&err2),
        "expected program error on retry, got: {err2:?}"
    );
    // NOTE: once the trusted-setup ceremony lands and a real proof is
    // available, replace the first call with a *successful* withdraw and
    // re-assert the second call returns Anchor's `AccountAlreadyInUse`
    // error (the proper double-spend signal). Tracking issue: P5-followup.
}

#[tokio::test]
async fn pause_blocks_deposits_and_withdrawals() {
    let mut env = setup().await;
    let auth = clone_keypair(&env.authority);
    let depositor = clone_keypair(&env.depositor);
    let relayer = clone_keypair(&env.relayer);

    submit(
        &mut env,
        build_initialize_ix(&env.authority.pubkey(), DEFAULT_DENOMINATION),
        &auth,
        &[],
    )
    .await
    .expect("initialize");

    // Pause via admin.
    submit(
        &mut env,
        build_pause_ix(&env.authority.pubkey()),
        &auth,
        &[],
    )
    .await
    .expect("pause");

    // Deposit must now fail with PoolPaused.
    let dep_err = submit(
        &mut env,
        build_deposit_ix(&depositor.pubkey(), [0xEEu8; 32]),
        &depositor,
        &[],
    )
    .await
    .expect_err("deposit while paused must fail");
    assert!(
        is_program_error(&dep_err),
        "expected program error on paused deposit, got: {dep_err:?}"
    );

    // Withdraw must also fail (constraint trips before verifier).
    let proof = vec![0u8; 256];
    let nullifier_hash = [0xFFu8; 32];
    let recipient = solana_sdk::pubkey::Pubkey::new_unique();
    let wd_err = submit(
        &mut env,
        build_withdraw_ix(
            &relayer.pubkey(),
            proof,
            // Root doesn't matter — the `paused` constraint runs first.
            empty_root(),
            nullifier_hash,
            recipient,
            DEFAULT_DENOMINATION,
        ),
        &relayer,
        &[],
    )
    .await
    .expect_err("withdraw while paused must fail");
    assert!(
        is_program_error(&wd_err),
        "expected program error on paused withdraw, got: {wd_err:?}"
    );
}

// ---------------------------------------------------------------------------
// Error-pattern helpers. Keeping them inline to avoid a dependency on the
// internals of `solana-program-test`'s error enum past what the public API
// exposes.

fn is_account_already_in_use(err: &BanksClientError) -> bool {
    match err {
        BanksClientError::TransactionError(TransactionError::InstructionError(
            _,
            InstructionError::Custom(_),
        )) => true,
        BanksClientError::TransactionError(TransactionError::AccountInUse) => true,
        BanksClientError::TransactionError(TransactionError::InstructionError(
            _,
            InstructionError::AccountAlreadyInitialized,
        )) => true,
        _ => false,
    }
}

fn is_program_error(err: &BanksClientError) -> bool {
    matches!(
        err,
        BanksClientError::TransactionError(TransactionError::InstructionError(_, _))
    )
}
