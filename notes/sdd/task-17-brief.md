### Task 17: Encrypted case store

**Files:**
- Create: `src/themask/keystore/__init__.py`, `src/themask/keystore/crypto.py`, `src/themask/keystore/secrets.py`, `src/themask/keystore/cases.py`
- Modify: `tests/conftest.py` (fixtures `keystore` = `MemoryKeyStore()`, `case_store`)
- Test: `tests/keystore/test_crypto.py`, `tests/keystore/test_cases.py`

**Interfaces:**
- Produces (`crypto.py`): `encrypt(key: bytes, plaintext: bytes) -> bytes` (12-byte random nonce ‖ AES-256-GCM ciphertext+tag), `decrypt(key: bytes, blob: bytes) -> bytes` (raises `CaseCorruptError` on tag failure).
- Produces (`secrets.py`): `class KeyStore(Protocol): def get_or_create_master_key(self) -> bytes`; `class KeychainKeyStore` (`keyring.get_password("The MASK", "master-key")`, creating 32 random bytes base64 on first use); `class MemoryKeyStore`.
- Produces (`cases.py`): `@dataclass CaseSummary(id, created_at, expires_at, source_files, n_entries)`; `class CaseStore(dir: Path, keystore: KeyStore)` with `save(case: Case) -> Path` (`<dir>/<id>.mask`, mode 0o600), `load(case_id) -> Case`, `list() -> list[CaseSummary]` (newest first; summaries need decryption, so the listing decrypts headers only — store `id, created_at, retention_days, source_files, n_entries` as a separate unencrypted-but-content-free JSON header line before the blob), `delete(case_id)`, `delete_all()`, `purge_expired(now: datetime | None = None) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_roundtrip_and_tamper():
    k = os.urandom(32); blob = encrypt(k, b"secret"); assert decrypt(k, blob) == b"secret"
    with pytest.raises(CaseCorruptError): decrypt(k, blob[:-1] + bytes([blob[-1] ^ 1]))
def test_memory_keystore_stable(): ks = MemoryKeyStore(); assert ks.get_or_create_master_key() == ks.get_or_create_master_key() and len(ks.get_or_create_master_key()) == 32
def test_save_load_list_delete(case_store, sample_case):
    p = case_store.save(sample_case); assert case_store.load(sample_case.id) == sample_case and oct(p.stat().st_mode)[-3:] == "600"
    assert [s.id for s in case_store.list()] == [sample_case.id]; case_store.delete(sample_case.id); assert case_store.list() == []
def test_values_not_on_disk(case_store, sample_case):
    p = case_store.save(sample_case); raw = p.read_bytes(); assert b"John Smith" not in raw and b"NL91" not in raw and sample_case.source_files[0].encode() in raw
def test_purge_expired(case_store, sample_case):
    case_store.save(sample_case); assert case_store.purge_expired(sample_case.created_at + timedelta(days=31)) == [sample_case.id] and case_store.list() == []
    case_store.save(sample_case); assert case_store.purge_expired(sample_case.created_at + timedelta(days=29)) == []
def test_wrong_key_is_corrupt(case_store, sample_case, tmp_path):
    case_store.save(sample_case); other = CaseStore(case_store.dir, MemoryKeyStore())
    with pytest.raises(CaseCorruptError): other.load(sample_case.id)
```

- [ ] **Step 2–5:** verify failure → implement → verify pass → `git commit -m "feat: AES-GCM case store with Keychain-backed master key and retention purge"`

---

