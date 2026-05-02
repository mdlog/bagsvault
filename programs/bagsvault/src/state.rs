use anchor_lang::prelude::*;

/// Depth of the on-chain commitment Merkle tree. 20 levels = 1,048,576 leaves
/// — far above any realistic single-pool deposit count for the hackathon
/// while still fitting comfortably inside a single account.
pub const MERKLE_TREE_DEPTH: usize = 20;
/// Size of the rolling root history (matches the architecture doc's
/// "menyimpan hingga 10 roots terbaru" line). Withdrawals can prove
/// against any root within this window, which gives wallets time to build
/// a proof without racing new deposits.
pub const ROOT_HISTORY_SIZE: usize = 10;

/// Singleton state of a single privacy pool.
///
/// The PDA is derived from `[b"merkle_tree", token_mint]` so the program can
/// host one pool per supported token (SOL is represented by the system
/// program mint). Account size is fixed for a given depth so it's safe to
/// realloc-free.
#[account]
pub struct MerkleTreeState {
    /// Authority allowed to pause / rotate config. 32 bytes.
    pub authority: Pubkey,
    /// Token mint this pool services (System Program mint = native SOL).
    pub token_mint: Pubkey,
    /// Fixed deposit denomination. Equal-amount deposits are critical for
    /// the anonymity set — variable amounts leak information.
    pub denomination: u64,
    /// Number of commitments inserted so far. Doubles as the next leaf
    /// index, so it must be < 2^MERKLE_TREE_DEPTH.
    pub commitment_count: u64,
    /// Index of the next slot to overwrite in `roots` (ring buffer cursor).
    pub root_cursor: u8,
    /// True when admin has paused the pool.
    pub paused: bool,
    /// `MERKLE_TREE_DEPTH` zero/sub-tree caches used by the incremental
    /// insertion algorithm. Each entry is the current "filled" sub-tree
    /// root at that level — see `merkle::insert`.
    pub filled_subtrees: [[u8; 32]; MERKLE_TREE_DEPTH],
    /// Last `ROOT_HISTORY_SIZE` roots, oldest-overwritten-first.
    pub roots: [[u8; 32]; ROOT_HISTORY_SIZE],
    /// PDA bump for stable derivation.
    pub bump: u8,
}

impl MerkleTreeState {
    pub const SEED_PREFIX: &'static [u8] = b"merkle_tree";

    /// Total serialized size: 8-byte discriminator added by Anchor on top.
    pub const SIZE: usize = 32      // authority
        + 32                        // token_mint
        + 8                         // denomination
        + 8                         // commitment_count
        + 1                         // root_cursor
        + 1                         // paused
        + (32 * MERKLE_TREE_DEPTH)  // filled_subtrees
        + (32 * ROOT_HISTORY_SIZE)  // roots
        + 1; // bump

    /// Returns true if `candidate_root` matches any root in the recent
    /// history window. Used by the withdrawal verifier to accept proofs
    /// built against a slightly stale tree.
    pub fn root_is_known(&self, candidate_root: &[u8; 32]) -> bool {
        if candidate_root == &[0u8; 32] {
            return false;
        }
        self.roots.iter().any(|r| r == candidate_root)
    }
}

/// One PDA per spent nullifier (`[b"nullifier", &nullifier_hash]`). The
/// account's mere existence is the spent-flag — we never read its body.
/// Keeping the struct empty (just discriminator + bump) keeps rent low.
#[account]
pub struct Nullifier {
    pub bump: u8,
}

impl Nullifier {
    pub const SEED_PREFIX: &'static [u8] = b"nullifier";
    pub const SIZE: usize = 1; // bump only
}

/// Off-chain receipt emitted on every successful deposit. Indexers
/// subscribe to logs/events to update their commitment caches without
/// re-scanning the full account.
#[event]
pub struct DepositEvent {
    pub commitment: [u8; 32],
    pub leaf_index: u64,
    pub timestamp: i64,
}

#[event]
pub struct WithdrawEvent {
    pub nullifier_hash: [u8; 32],
    pub recipient: Pubkey,
    pub amount: u64,
    pub timestamp: i64,
}

#[event]
pub struct RootUpdatedEvent {
    pub new_root: [u8; 32],
    pub commitment_count: u64,
}
