//! Shared helpers for the BagsVault Rust integration tests.
//!
//! Determinism: every keypair is derived from a fixed seed in [`SEED`] so
//! re-runs hash identically (no time-based randomness, no
//! `Keypair::new()`). The Solana program-test runtime itself is
//! deterministic for a given start_with_context configuration.

use anchor_lang::InstructionData;
use solana_program_test::{processor, ProgramTest, ProgramTestContext};
use solana_sdk::{
    instruction::{AccountMeta, Instruction},
    pubkey::Pubkey,
    signature::{Keypair, Signer},
    system_program,
    transaction::Transaction,
};

/// Fixed seed for keypair derivation. Must not change — tests rely on
/// deterministic addresses for snapshot-style checks.
pub const SEED: u64 = 0xBA65_5A1C_DEAD_BEEF;

/// Default test denomination. 1 SOL in lamports.
pub const DEFAULT_DENOMINATION: u64 = 1_000_000_000;

/// Spawn a fresh `ProgramTest` instance with the BagsVault program loaded.
/// Funds the authority and a relayer keypair so callers don't have to
/// airdrop manually.
pub async fn setup() -> TestEnv {
    let mut program_test = ProgramTest::new(
        "bagsvault",
        bagsvault::ID,
        processor!(bagsvault::entry),
    );

    // Fixed-seed keypairs — see module docs.
    let authority = keypair_from_seed(SEED ^ 0x01);
    let relayer = keypair_from_seed(SEED ^ 0x02);
    let depositor = keypair_from_seed(SEED ^ 0x03);

    for kp in [&authority, &relayer, &depositor] {
        program_test.add_account(
            kp.pubkey(),
            solana_sdk::account::Account {
                lamports: 100 * DEFAULT_DENOMINATION,
                owner: system_program::ID,
                ..Default::default()
            },
        );
    }

    let ctx = program_test.start_with_context().await;
    TestEnv {
        ctx,
        authority,
        relayer,
        depositor,
    }
}

/// Helper struct — bundles the program-test context with the canonical
/// keypairs. Tests pull what they need.
pub struct TestEnv {
    pub ctx: ProgramTestContext,
    pub authority: Keypair,
    pub relayer: Keypair,
    pub depositor: Keypair,
}

/// Derive a deterministic keypair from a u64 seed. Uses the seed bytes as
/// the ed25519 secret seed (same input shape `Keypair::from_seed` consumes)
/// — collision-free across our tests.
pub fn keypair_from_seed(seed: u64) -> Keypair {
    let mut bytes = [0u8; 32];
    bytes[..8].copy_from_slice(&seed.to_le_bytes());
    // Spread across the rest so different seeds produce visibly distinct
    // keypairs even when only the low 8 bytes differ.
    for i in 8..32 {
        bytes[i] = (seed.rotate_left((i as u32) * 3) & 0xFF) as u8;
    }
    Keypair::from_seed(&bytes).expect("ed25519 keypair from deterministic seed")
}

/// Clone a keypair without the unstable `insecure_clone` API — cheaper
/// to round-trip via `to_bytes` / `from_bytes`.
pub fn clone_keypair(kp: &Keypair) -> Keypair {
    Keypair::from_bytes(&kp.to_bytes()).expect("clone keypair")
}

/// PDA helper — `[b"merkle_tree", token_mint]`.
pub fn tree_state_pda(token_mint: &Pubkey) -> (Pubkey, u8) {
    Pubkey::find_program_address(
        &[b"merkle_tree", token_mint.as_ref()],
        &bagsvault::ID,
    )
}

/// PDA helper — `[b"vault", token_mint]`.
pub fn vault_pda(token_mint: &Pubkey) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"vault", token_mint.as_ref()], &bagsvault::ID)
}

/// PDA helper — `[b"nullifier", &nullifier_hash]`.
pub fn nullifier_pda(nullifier_hash: &[u8; 32]) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"nullifier", nullifier_hash.as_ref()], &bagsvault::ID)
}

/// Build the `initialize` instruction for the canonical native-SOL pool
/// (token_mint = system program ID).
pub fn build_initialize_ix(authority: &Pubkey, denomination: u64) -> Instruction {
    let token_mint = system_program::ID;
    let (tree_state, _) = tree_state_pda(&token_mint);

    Instruction {
        program_id: bagsvault::ID,
        accounts: vec![
            AccountMeta::new(*authority, true),
            AccountMeta::new_readonly(token_mint, false),
            AccountMeta::new(tree_state, false),
            AccountMeta::new_readonly(system_program::ID, false),
        ],
        data: bagsvault::instruction::Initialize { denomination }.data(),
    }
}

/// Build the `deposit` instruction.
pub fn build_deposit_ix(depositor: &Pubkey, commitment: [u8; 32]) -> Instruction {
    let token_mint = system_program::ID;
    let (tree_state, _) = tree_state_pda(&token_mint);
    let (vault, _) = vault_pda(&token_mint);

    Instruction {
        program_id: bagsvault::ID,
        accounts: vec![
            AccountMeta::new(*depositor, true),
            AccountMeta::new(vault, false),
            AccountMeta::new(tree_state, false),
            AccountMeta::new_readonly(system_program::ID, false),
        ],
        data: bagsvault::instruction::Deposit { commitment }.data(),
    }
}

/// Build the `withdraw` instruction.
pub fn build_withdraw_ix(
    relayer: &Pubkey,
    proof: Vec<u8>,
    root: [u8; 32],
    nullifier_hash: [u8; 32],
    recipient: Pubkey,
    amount: u64,
) -> Instruction {
    let token_mint = system_program::ID;
    let (tree_state, _) = tree_state_pda(&token_mint);
    let (vault, _) = vault_pda(&token_mint);
    let (nullifier_pda_pk, _) = nullifier_pda(&nullifier_hash);

    Instruction {
        program_id: bagsvault::ID,
        accounts: vec![
            AccountMeta::new(*relayer, true),
            AccountMeta::new(vault, false),
            AccountMeta::new(tree_state, false),
            AccountMeta::new(nullifier_pda_pk, false),
            AccountMeta::new(recipient, false),
            AccountMeta::new_readonly(system_program::ID, false),
        ],
        data: bagsvault::instruction::Withdraw {
            proof,
            root,
            nullifier_hash,
            recipient,
            amount,
        }
        .data(),
    }
}

/// Build a `pause` admin instruction.
pub fn build_pause_ix(authority: &Pubkey) -> Instruction {
    let token_mint = system_program::ID;
    let (tree_state, _) = tree_state_pda(&token_mint);

    Instruction {
        program_id: bagsvault::ID,
        accounts: vec![
            AccountMeta::new_readonly(*authority, true),
            AccountMeta::new(tree_state, false),
        ],
        data: bagsvault::instruction::Pause {}.data(),
    }
}

/// Sign + send a single-instruction tx using `payer` as fee-payer and the
/// given signers. Returns the result so callers can assert success / error.
pub async fn submit(
    env: &mut TestEnv,
    ix: Instruction,
    payer: &Keypair,
    extra_signers: &[&Keypair],
) -> Result<(), solana_program_test::BanksClientError> {
    let mut signers: Vec<&Keypair> = vec![payer];
    signers.extend(extra_signers);
    let recent_blockhash = env.ctx.banks_client.get_latest_blockhash().await.expect("blockhash");
    let tx = Transaction::new_signed_with_payer(
        &[ix],
        Some(&payer.pubkey()),
        &signers,
        recent_blockhash,
    );
    env.ctx.banks_client.process_transaction(tx).await
}

