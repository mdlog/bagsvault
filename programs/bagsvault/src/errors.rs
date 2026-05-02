use anchor_lang::prelude::*;

#[error_code]
pub enum BagsVaultError {
    #[msg("Merkle tree is full — initialise a new pool.")]
    TreeFull,
    #[msg("Provided Merkle root is not in the recent root window.")]
    UnknownRoot,
    #[msg("Nullifier has already been spent.")]
    DoubleSpend,
    #[msg("Groth16 proof failed verification.")]
    InvalidProof,
    #[msg("Deposit denomination does not match pool denomination.")]
    DenominationMismatch,
    #[msg("Pool is paused — admin must unpause before further use.")]
    PoolPaused,
    #[msg("Caller is not authorised for this admin action.")]
    Unauthorized,
}
