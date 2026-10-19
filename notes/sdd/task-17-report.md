# Task 17: Encrypted case store — implementer report

Worktree `/Users/alijoeee/Developer/the-mask-worktrees/task-17`, branch `task-17` (from 8479e36).
Status: **DONE_WITH_CONCERNS** (concerns are hand-offs for Tasks 20/23, listed at the end; nothing blocks merging).

## Commits

| SHA | Subject |
|---|---|
| 7fec25c | fix: reject unusable stored cases and impossible mask spans (the two `model.py` fixes) |
| a5d1f27 | feat: AES-GCM case store with Keychain-backed master key and retention purge |

Both end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (the boilerplate's exact trailer, which also matches the repo history; the harness's own default trailer names a different model, the controller's rule was followed).

## What was implemented

**`src/themask/model.py` (controller decision 6)**
- `Case.from_json`: rejects a naive `created_at`; checks every field it reads (`id` text, `source_files` list of text, `retention_days` whole number, `masked_files`/`entries` lists of objects, and also the fields inside those objects: `name`, `sha256`, `placeholder`, `value`, `variants`); every failure, including a JSON syntax error, ends as one plain `ValueError("Not a stored case.")` with the original chained. A JSON `true`/`false` is refused as a retention (Python treats bool as int).
- `MaskPlan.__post_init__`: validates every replacement (`start < 0` or `end < start` raises `ValueError("Replacement [X] has an invalid span a-b.")`), then sorts by `(start, end)`, then the unchanged overlap check. An empty span (`start == end`) is allowed.

**`src/themask/keystore/`**
- `crypto.py`: `encrypt(key, plaintext)` = 12 random bytes ‖ AES-256-GCM ciphertext+tag; `decrypt(key, blob)` raises `CaseCorruptError` on `InvalidTag` and on a blob of 12 bytes or fewer ("shorter than 13"). Only 32-byte keys are accepted (`ValueError` otherwise): `AESGCM` itself would silently accept 16 and 24 bytes. The agreed message lives in one constant, `CORRUPT_MESSAGE`.
- `secrets.py`: `KeyStore` Protocol; `KeychainKeyStore` (`keyring.get_password("The MASK", "master-key")`, creates `secrets.token_bytes(32)` stored base64 on first use); `MemoryKeyStore`.
- `cases.py`: `CaseSummary(id, created_at, expires_at, source_files, n_entries)`; `CaseStore(dir, keystore)` with public `dir`, `unreadable: list[Path]`, `save`, `load`, `list`, `delete`, `delete_all`, `purge_expired`.
- `__init__.py`: re-exports the public names (`__all__`), so `from themask.keystore import CaseStore` works as well as the per-module paths from the brief.

**Tests and fixtures**
- `tests/fixtures/keystore.py`: `keystore` (= `MemoryKeyStore()`), `case_store` (= `CaseStore(tmp_path / "cases", keystore)`, a folder that does not exist yet, so every test exercises first-save creation), `sample_case` (exactly the value in decision 5).
- `tests/keystore/test_crypto.py` (37 tests): crypto, `MemoryKeyStore`, `KeychainKeyStore`. The Keychain tests use a small in-memory `KeyringBackend` subclass installed with `keyring.set_keyring` for one test and removed afterwards; a test checks the system keyring comes back.
- `tests/keystore/test_cases.py` (62 tests): the six scenarios from the brief plus the behaviours below.
- `tests/test_model.py`: +34 tests (72 total).

## Behaviour decisions I made where the brief was silent (please review)

1. **Brief test vs ruling R10.** The brief's `test_values_not_on_disk` asserts `sample_case.source_files[0].encode() in raw`, which only holds with the old plaintext-header design. R10 removes the header, so I inverted it: `a.docx`, `MASKED-K4F7.docx`, both placeholders, both values and the variant are all asserted to be absent from the raw bytes. A second test decrypts the whole file and compares it with `case.to_json()`, which proves there is no header at all.
2. **Atomic, private write.** `save` writes `.saving-<random>.tmp` in the same folder (fsync), `chmod 0o600`, then `os.replace` onto `<id>.mask`; on any failure the temp file is removed. Why: "Add file to this case" overwrites an existing case, and a crash mid-write must not destroy the only key for files already masked. The explicit chmod makes 0o600 independent of the umask (tested with umasks 000, 022, 077, 277). `delete_all` also removes `.saving-*.tmp` leftovers of a hard-killed save.
3. **Case id is a file name.** `save/load/delete` raise `ValueError("Not a valid case id: ...")` for `""`, `.`, `..` or anything with a path separator. A file whose decrypted case id differs from its file name (for example `K4F7 copy.mask` made in Finder) counts as unreadable instead of being listed twice.
4. **Master key fetched lazily and once per operation.** Nothing touches the Keychain when there is no file to open (`list`/`purge_expired` on an empty or missing folder, `delete`, `delete_all`, `load` of a missing case); `list` of N files asks once, not N times. `delete`/`delete_all` never need the key.
5. **Error behaviour.** `load` of a missing case raises `FileNotFoundError` (the case is not damaged, it is absent); `delete` of a missing case is a no-op. Bad UTF-8 or a payload that is not a case after successful decryption is also `CaseCorruptError`. A wrong-size master key (a program mistake) is deliberately *not* reported as corrupt.
6. **Retention.** A case is due when `now >= created_at + retention_days` (exactly at `expires_at` it is purged; one microsecond earlier it is kept); `now` may be in any timezone. Returned ids are sorted by id. Unreadable files are never purged (R10: no readable date).
7. **Damaged Keychain item.** If the item exists but is not a base64 32-byte key, `KeychainKeyStore` raises `ValueError` and does not overwrite it (overwriting would silently lock the owner out of every stored case).
8. `list()` sorts newest first, ties by id; `unreadable` is sorted by file name and rebuilt on every `list()` (purge does not touch it). The mypy gotcha: a method called `list` makes `list[...]` in any later signature of the class mean the method, so `list` is the last method (comment in the code).

## TDD evidence

**RED 1 — model fixes.**
`uv run pytest tests/test_model.py -q`
```
29 failed, 43 passed in 0.18s
```
Representative reasons: `Failed: DID NOT RAISE <class 'ValueError'>` for `[timestamp without a timezone]`, `[source files that are one text]`, `[retention that is true]`, `test_maskplan_rejects_a_span_that_starts_before_the_text[-1]`; and `ValueError: Replacements overlap: [B_1] at 3-6 and [A_1] at 3-3.` for `test_maskplan_orders_replacements_that_start_together_by_their_end` (the old sort key was `start` only). 8 failures are MaskPlan tests; 21 are `from_json` tests: 15 for new rules, 1 for the new wrapping test, and 5 existing inputs (`""`, `"not json"`, unknown placeholder type, timestamp that is not a date, entry type that is not text) that fail only because the assertion became stricter (`match="^Not a stored case\.$"`; before, they raised other `ValueError` messages). Expected: none of the new rules existed yet. The over-rejection guard `test_case_from_json_accepts_any_timezone_offset` passed already, as it should.

**GREEN 1.** `uv run pytest tests/test_model.py -q` → `72 passed in 0.08s`.

**RED 2 — keystore.** `uv run pytest tests/keystore -q` (tests and fixture module written, no implementation):
```
ImportError: Error importing plugin "tests.fixtures.keystore": No module named 'themask.keystore'
```
Expected: the package did not exist.

**GREEN 2.** `uv run pytest tests/keystore -q` → `98 passed in 0.18s`.

**RED 3 / GREEN 3 — one gap found in self-review** (a crashed save leaves a `.tmp`; "Delete all" must remove it): new test `test_delete_all_also_removes_what_a_crashed_save_left_behind` → `1 failed, 98 passed`; after the fix → `99 passed in 0.16s`.

**Final gate** (from the worktree root):
```
uv run pytest -q                      -> 535 passed in 0.40s   (402 before this task; no warnings)
uv run ruff check src tests           -> All checks passed!
uv run ruff format --check src tests  -> 21 files already formatted
uv run mypy src                       -> Success: no issues found in 10 source files
```

## Additional verification (so the tests are shown able to fail, and the Keychain untouched)

- **Mutation check, 26 of 26 caught.** A script (scratchpad `t17probe/mutate.py`) broke the implementation one way at a time, ran `tests/keystore -x`, and restored the file: no short-blob check; fixed nonce; 16/24-byte keys accepted; `InvalidTag` not mapped; no chmod; non-atomic save; temp file not cleaned; no id/file-name check; purge `<` instead of `<=`; key fetched when no files; list oldest first; no id guard; `unreadable` not refreshed; corrupt file escapes `list`; directories named `*.mask` not skipped; bad JSON/UTF-8 not mapped; `delete` not idempotent; purge deleting unreadable files; wrong `n_entries`; wrong suffix; wrong Keychain service; wrong account; key not stored; no key-length check; damaged item replaced; memory key changing per call. Files were verified byte-identical afterwards.
- **No real Keychain access.** `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring uv run pytest tests/keystore -q` → `98 passed` (the suite then had 98 tests; any stray use of the system keyring would have raised). After all runs `security find-generic-password -s "The MASK"` exits 44, "The specified item could not be found in the keychain." (a read-only metadata query).
- Each keystore test file passes alone; the in-memory `MemoryKeyring` is not viable for keyring's auto-detection (checked: `MemoryKeyring.viable` is `False`, absent from `get_all_keyring()`).
- The mypy gate is `mypy src` only; I also type-checked the new tests: `MYPYPATH=src uv run mypy tests/keystore tests/fixtures/keystore.py` → clean. (Without `MYPYPATH=src`, mypy resolves `themask` as `Any` from the tests directory because of the src layout.)

## How to check it yourself

```
cd /Users/alijoeee/Developer/the-mask-worktrees/task-17
uv run pytest -q && uv run ruff check src tests && uv run mypy src
uv run pytest tests/keystore -v                # every behaviour above, by name
uv run pytest tests/keystore/test_cases.py -v -k "values_not_on_disk or nothing_but_the_encrypted"
                                               # the two tests that prove no value or file name is on disk
git show 7fec25c --stat && git show a5d1f27 --stat
```

## Files changed (absolute paths)

New:
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/src/themask/keystore/__init__.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/src/themask/keystore/crypto.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/src/themask/keystore/secrets.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/src/themask/keystore/cases.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/tests/fixtures/keystore.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/tests/keystore/__init__.py` (empty)
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/tests/keystore/test_crypto.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/tests/keystore/test_cases.py`

Modified:
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/src/themask/model.py`
- `/Users/alijoeee/Developer/the-mask-worktrees/task-17/tests/test_model.py`

Nothing under `tools/`, `tests/fixtures/corpus.py`, `tests/test_corpus.py`, `src/themask/detect/`, `tests/fixtures/engine.py`, `tests/detect/` or `tests/conftest.py` was touched (the new fixtures are picked up by conftest's auto-loader). No subagents were used.

## Self-review

- **Completeness:** every item of the brief, the seven controller decisions and both model fixes are done and tested; the brief's `test_values_not_on_disk` deviation is explained above (R10).
- **Quality:** one responsibility per file; the agreed message exists once (`crypto.CORRUPT_MESSAGE`) and the tests spell it out literally; no line over 100 characters; docstrings state what is raised.
- **Discipline:** the additions beyond the brief are all failure-mode protections of a key store (atomic write, id guard, 32-byte keys, damaged Keychain item, lazy key). Each has a test that fails without it (mutation check). `CaseSummary` is a plain `@dataclass` exactly as the brief says. Tests I wrote and then removed as redundant or testing the test double: large-text roundtrip, "both key stores are key stores", `viable` assertion, key-with-cipher round trips.
- **Testing:** output pristine, no warnings; no test touches the real Keychain or the real data folder.

## Concerns and hand-offs

1. **Task 20 / 23 must catch key-store errors.** `CaseStore` operations propagate whatever the key store raises: `keyring.errors.KeyringError` (Keychain refused or locked) and the `ValueError` for a damaged Keychain item. Neither is a `MaskError`, so the interface would show a stack trace unless it catches them. Especially the startup `purge_expired` (Task 20): a Keychain failure there must not stop the app from opening. On a first launch with no case files it does not touch the Keychain at all.
2. **Task 23 should surface `case_store.unreadable`.** After a Keychain reset, or for a file copied from another computer, files cannot be opened and, by design (R10), are never purged automatically. The Cases screen should say how many there are and offer deletion (`delete(path.stem)`, or Delete all).
3. **Absurd `retention_days`.** `from_json` checks the type, not the range. A value above 999,999,999 would make `expires_at` raise `OverflowError` in `list()`/`purge_expired()`. It can only come from a file written with the master key (the Settings spin box limits 1 to 365), so I did not add a range rule that nobody asked for.
4. `Case.to_json()` still treats a naive `created_at` as local time (it was out of the model fix's scope). `from_json` now refuses to read one back.
5. The module name `secrets.py` is mandated by the brief. It imports the standard-library `secrets` (absolute import), which works; it would only clash if `src/themask/keystore` were ever put on `sys.path` (running a file from that directory as a script).
