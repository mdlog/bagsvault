# Arsitektur Sistem BagsVault: Protokol Privasi Kreator Terdesentralisasi

**BagsVault** adalah protokol privasi yang dirancang khusus untuk ekosistem kreator di Bags.fm. Sistem ini memungkinkan kreator dan pengguna untuk menerima fee, melakukan donasi, dan memindahkan token secara anonim menggunakan *Zero-Knowledge Proofs* (ZK-SNARKs), sambil tetap mematuhi regulasi melalui integrasi verifikasi risiko on-chain.

![BagsVault Architecture Diagram](./bagsvault_architecture.png)

## 1. Ringkasan Protokol

Ekosistem kreator sering kali menghadapi masalah transparansi radikal di blockchain publik. Ketika dompet seorang kreator diketahui, seluruh riwayat transaksi, donasi, dan pendapatan *fee* mereka terekspos ke publik. BagsVault memecahkan masalah ini dengan mengimplementasikan arsitektur *mixer/tumbler* menggunakan sirkuit Noir ZK dan verifikasi Groth16 on-chain di Solana.

Protokol ini beroperasi melalui dua fase utama yang memutus hubungan on-chain antara pengirim (deposit) dan penerima (withdrawal), menciptakan *anonymity set* yang kuat [1].

## 2. Arsitektur Komponen Utama

Sistem BagsVault terdiri dari empat pilar utama yang saling terintegrasi:

### A. Lapisan Smart Contract (Solana On-Chain)
Lapisan ini menangani logika inti dari privasi dan penyimpanan dana.

| Komponen | Fungsi | Integrasi Bags/Solana |
|----------|--------|----------------------|
| **BagsVault Program** | Kontrak utama yang menerima deposit, memvalidasi bukti ZK, dan mengeksekusi penarikan. | Anchor Framework |
| **Merkle Tree State** | Menyimpan riwayat *commitment* (hash dari deposit) untuk membangun *anonymity set*. | Menyimpan hingga 10 *roots* terbaru |
| **Nullifier Set** | Melacak *nullifier* yang sudah digunakan untuk mencegah serangan *double-spending*. | Set data on-chain |
| **Groth16 Verifier** | Memverifikasi validitas ZK Proof secara on-chain melalui *Cross-Program Invocation* (CPI). | Sunspot Verifier Program [2] |

### B. Integrasi Bags API Layer
Protokol ini secara mendalam memanfaatkan infrastruktur Bags API untuk manajemen token dan pendapatan.

*   **Trade Tokens API (`/trade/swap`)**: Digunakan untuk melakukan *swap* token secara otomatis sebelum deposit jika pengguna ingin mendepositkan token kreator spesifik [3].
*   **Claim Token Fees API (`/token-launch/claim-txs/v3`)**: Kreator dapat mengklaim *fee* mereka langsung ke dalam BagsVault secara anonim [4].
*   **Fee Share Configuration (`FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`)**: Berinteraksi dengan program *Fee Share V2* Bags untuk memastikan distribusi pendapatan yang tepat [5].

### C. Lapisan Privasi & Kepatuhan (Backend)
Lapisan ini menyeimbangkan antara privasi absolut dan kepatuhan terhadap regulasi (AML/CTF).

*   **ZK Proof Generator**: Server *backend* yang menghasilkan bukti Groth16 menggunakan sirkuit Noir. Bukti ini mengonfirmasi bahwa pengguna memiliki deposit yang valid tanpa mengungkapkan deposit yang mana.
*   **Range Risk API Integration**: Melakukan pemeriksaan risiko dompet (sanctions, hacks, illicit activity) *sebelum* dana diizinkan masuk ke dalam *privacy pool*. Pendekatan ini terinspirasi dari arsitektur pemenang Solana Privacy Hack [6].

### D. Relayer Network
Jaringan relayer memungkinkan pengguna untuk melakukan penarikan dana tanpa harus memiliki SOL di dompet tujuan baru mereka (*gasless transactions*). Relayer akan membayarkan biaya gas Solana dan mengambil sebagian kecil dari dana penarikan sebagai kompensasi.

## 3. Alur Transaksi Lengkap

### Fase 1: Deposit (Pengumpulan Dana)
Fase ini terjadi ketika kreator mengklaim *fee* atau pendukung melakukan donasi.

1.  **Pemeriksaan Kepatuhan**: Dompet pengirim diperiksa menggunakan Range Risk API. Jika terdeteksi sebagai entitas berisiko tinggi, deposit ditolak.
2.  **Pembuatan Komitmen**: Klien pengguna menghasilkan rahasia (*secret*) dan *nullifier* secara lokal. Klien kemudian menghitung *commitment* = `hash(nullifier, secret, amount)`.
3.  **Eksekusi Deposit**: Pengguna mengirimkan token beserta *commitment* ke smart contract BagsVault.
4.  **Pembaruan State**: Smart contract menambahkan *commitment* ke dalam Merkle Tree dan memperbarui *root* on-chain.

### Fase 2: Withdrawal (Penarikan Anonim)
Fase ini terjadi ketika kreator ingin mencairkan dana ke dompet baru (fresh wallet) tanpa jejak.

1.  **Pembuatan ZK Proof**: Klien memberikan *secret*, *nullifier*, dan *Merkle path* ke ZK Proof Generator. Generator membuat bukti matematis bahwa *commitment* ada di dalam Merkle Tree.
2.  **Permintaan Relayer**: Pengguna mengirimkan ZK Proof, *nullifier hash*, dan alamat tujuan ke Relayer.
3.  **Verifikasi On-Chain**: Relayer mengirimkan transaksi ke smart contract. Contract menggunakan CPI ke program Sunspot untuk memverifikasi ZK Proof [2].
4.  **Pencegahan Double-Spend**: Contract memeriksa apakah *nullifier hash* sudah pernah digunakan. Jika belum, *nullifier* dicatat.
5.  **Pencairan Dana**: Token dikirim ke alamat tujuan baru yang sepenuhnya bersih dari riwayat transaksi sebelumnya.

## 4. Spesifikasi Teknis & Kriptografi

Sirkuit Zero-Knowledge ditulis menggunakan bahasa **Noir**, yang dioptimalkan untuk menghasilkan bukti yang ringkas dan cepat.

**Public Inputs (Input Publik untuk Sirkuit):**
*   `root`: Merkle tree root saat ini.
*   `nullifier_hash`: Hash dari *nullifier* untuk mencegah pengeluaran ganda.
*   `recipient`: Alamat penarikan tujuan.
*   `amount`: Jumlah penarikan (opsional, dapat diatur tetap untuk privasi maksimal).

**Private Inputs (Input Rahasia dari Pengguna):**
*   `nullifier`: Bagian dari *preimage* komitmen.
*   `secret`: Bagian dari *preimage* komitmen.
*   `merkle_proof`: Jalur pembuktian dari komitmen ke *root*.
*   `is_even`: Indikator posisi dalam Merkle tree.

## 5. Keunggulan Kompetitif untuk Hackathon Bags

1.  **Blue-Ocean Track**: Mayoritas peserta hackathon Bags fokus pada "AI Agents". Memasuki *track* Privacy dengan arsitektur ZK-SNARK yang solid memberikan peluang kemenangan yang jauh lebih tinggi.
2.  **Kesesuaian Narasi**: Bags adalah platform untuk kreator. Privasi finansial adalah masalah nyata bagi kreator besar yang tidak ingin seluruh pendapatannya dilacak oleh publik.
3.  **Compliance-Ready**: Mengintegrasikan Range Risk API menunjukkan kedewasaan teknis. Protokol privasi murni sering ditolak oleh institusi, tetapi protokol privasi dengan kepatuhan pra-deposit adalah masa depan DeFi [6].
4.  **Pemanfaatan Ekosistem Maksimal**: Arsitektur ini tidak hanya berjalan di Solana, tetapi secara khusus menggunakan Bags API untuk *trading* dan klaim *fee*, menunjukkan pemahaman mendalam tentang infrastruktur penyelenggara.

---

### Referensi
[1] Solana Mixer GitHub Repository. "Solana Mixer enhances privacy on the Solana blockchain." https://github.com/albertoslavicadev/solana-mixer
[2] Noir Solana Private Transfers. "Privacy-preserving SOL transfers using Noir ZK circuits and onchain Groth16 verification via Sunspot." https://github.com/catmcgee/noir-solana-private-transfers
[3] Bags API Documentation. "Trade Tokens." https://docs.bags.fm/how-to-guides/trade-tokens
[4] Bags API Documentation. "Claim Token Fees." https://docs.bags.fm/how-to-guides/claim-fees#claim-token-fees
[5] Bags API Documentation. "Program IDs." https://docs.bags.fm/principles/program-ids
[6] Range Security Blog. "Privacy meets compliance: The winners of our Solana Privacy Hack bounty." https://www.range.org/blog/privacy-meets-compliance-the-winners-of-our-solana-privacy-hack-bounty
