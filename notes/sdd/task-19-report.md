# Task 19 report: network guard, offline tldextract, content-free logging

**Status:** DONE_WITH_CONCERNS (the concerns are small; they are listed at the end)
**Branch / worktree:** `task-19` in `/Users/alijoeee/Developer/the-mask-worktrees/task-19`, from `mac-v1` at 7548a97
**Commit:** `6beb246 feat: network guard, offline tldextract and content-free logging`
**Tests:** 27 new tests (17 in `tests/test_netguard.py`, 8 in `tests/test_logging.py`, 2 in `tests/test_main.py`). Full suite **2490 passed in 50.0 s** with the guard installed (baseline before the task: 2463 passed in 51.9 s), no warnings (the new files also pass under `-W error`). `ruff check src tests tools`, `ruff format --check src tests tools` and `mypy src` (35 files) are clean.

Scope per ruling R77: `test_log_has_no_document_content` waited for Task 15's export; it is added in Round 2 at the end of this report.

## What I implemented

### `src/themask/netguard.py` (new)

- `NetworkBlockedError(OSError)` and `MESSAGE = "The MASK never uses the network."`.
- `install_network_guard() -> None`, idempotent through a module flag (a second call returns at once and changes nothing, tldextract's extractor included).
  - **Socket methods** `connect`, `connect_ex`, `sendto`, `bind`, `listen` on `socket.socket`: each is replaced by a `functools.wraps` wrapper that raises `NetworkBlockedError(MESSAGE)` when `self.family` is `AF_INET` or `AF_INET6`, and otherwise calls the original. So `AF_UNIX` (and any other family) is untouched (R77).
  - **Module functions** `socket.create_connection` and `socket.getaddrinfo` always raise.
  - **tldextract:** `tldextract.extract` is replaced by `TLDExtract(cache_dir=None, suffix_list_urls=(), fallback_to_snapshot=True)` (see decision 1 below for `cache_dir=None`). Presidio's own `EmailRecognizer.validate_result` is the only caller in the dependency tree (`tldextract.extract(...)`, looked up at call time); our `EmailAddressRecognizer` overrides it and our `WebAddressRecognizer` does not use tldextract, so the line is a safety net, and it runs before Presidio is ever used (conftest, `__main__`).
  - `mypy` rejects a plain assignment to the function `tldextract.extract`, and this ruff version has B010 on by default, so the assignment carries `# type: ignore[assignment]` (checked: it is needed, `warn_unused_ignores` would flag it otherwise).
- The module docstring says what is blocked, why only internet sockets, and what the tldextract line is for.

### `src/themask/logging_setup.py` (new)

- Module docstring = **the rule** ("a log line carries counts, types, durations and file sizes, and nothing else", with a model line, and a sentence that it covers exception messages and file-name stems too), plus how the handler is placed.
- `setup_logging(level="INFO") -> Path`: a `RotatingFileHandler` (`MAX_BYTES = 1_000_000`, `BACKUP_COUNT = 3`, UTF-8) on `log_dir() / "themask.log"`, format `"%(asctime)s %(name)s %(levelname)s %(message)s"`, level applied to the `themask` logger; the `presidio-analyzer` logger is set to WARNING. The handler is on the `themask` logger only, so other libraries' records never reach the file.
- One handler only: the handler is registered under a name and found again with `logging.getHandlerByName` (new in Python 3.12, which the project requires). A second call with the same file does nothing to the handler; a call after the data folder changed closes the old handler and opens the new file (decision 3).

### `src/themask/detect/engine.py` (modified)

`Engine.analyze` writes one INFO line per call through `logging.getLogger("themask.detect.engine")`: `analyze characters=<n> findings=<n> seconds=<x.xx>` and nothing else. Behaviour is otherwise unchanged (the whole existing suite passes). Module and method docstrings mention the line.

### `src/themask/__main__.py` (new, temporary until Task 20)

`main()` = `install_network_guard()`, `setup_logging()`, `print(f"{APP_NAME} {VERSION}")`; run with `if __name__ == "__main__"`. The README note about `uv run python -m themask` is now true; I left it as instructed.

### `tests/conftest.py` (modified)

`install_network_guard()` is called at import, after the `QT_QPA_PLATFORM` line and before `pytest_plugins` is evaluated, so it runs before any fixture module loads. `paths.py` needed nothing: `log_dir()` already exists (Task 8).

## Decisions, and where I went beyond or beside the brief (please check these)

1. **`cache_dir=None` added to the `TLDExtract(...)` call.** R77 names `suffix_list_urls=()` and `fallback_to_snapshot=True`. With only those, tldextract still keeps a cache under `$HOME/.cache/python-tldextract/…` (default `cache_dir`): the app would write outside its data folder, and when that folder cannot be written tldextract logs "unable to cache … the Public Suffix List …", which is exactly the text `test_url_recognizer_works_offline` forbids (this would hit a sandboxed or read-only home in the packaged app). `cache_dir=None` disables the disk cache, tldextract's own suggested way to silence that warning; the snapshot is parsed once per process on first use. Tested by a subprocess with `HOME` pointing to an empty folder (the folder stays empty); mutation-checked.
2. **"1 MB" is `1_000_000` bytes**, the smaller of the two readings, so any test that writes "more than 1 MB" rotates under either. The test pins `(maxBytes, backupCount) == (1_000_000, 3)`.
3. **`setup_logging` re-points the file when the data folder changes**, instead of keeping the first handler forever. Without it, the brief's `test_log_has_no_document_content` (which sets `THEMASK_DATA_DIR` to its own `tmp_path` and then reads the returned file) would find an empty file whenever another test had called `setup_logging` earlier in the same process. Same folder twice = no change (one handler), as required.
4. **`tests/test_main.py` is a new file** (the brief lists only `test_netguard.py` and `test_logging.py`). The entry-point tests cover the guard and the log together, and Task 20 will replace or delete them, so they sit in a file of their own.
5. **The log line is `key=value`** (`analyze characters=… findings=… seconds=…`): no plural grammar, easy to grep. The tests pin the exact shape, so a later task changing it must change the test knowingly.
6. **Commit trailer.** The boilerplate demands the exact trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; the session's own attribution reminder named `Claude Sonnet 5.5`. I followed the boilerplate (the process rule you pointed me to). The repo's history carries other model names too (`Claude Opus 5.5` on the fix commits). Amend the trailer if you want the other one.

## Guard coverage: what it does not catch (by the R77 list, not oversights)

*Superseded by Fix round 1 (R80) at the end of this report: `sendmsg` and the name lookups are now blocked; child processes, native libraries and Windows `socketpair` remain, and the module docstring says so.*

- `socket.socket.sendmsg` with an address, `socket.gethostbyname*`, `gethostbyaddr`, `getfqdn`: not on the R77 list, so not blocked. A name lookup through them would reach DNS. One line each to add if you want them.
- Code that calls the C type directly (`_socket.socket`) or native libraries (Qt's network module, system frameworks) is not covered; the app uses neither.
- The guard is per process: a child process the app starts (e.g. `multiprocessing` with spawn) begins unguarded unless it calls `install_network_guard()` itself.
- **Windows (later phase):** CPython builds `socket.socketpair()` on Windows from a loopback AF_INET socket (bind, listen, connect), so asyncio and anything using it would hit this guard there. The Windows port will need a loopback or `socketpair` exception. Not an issue on macOS (`socketpair` is AF_UNIX there; tested).

## Tests

### `tests/test_netguard.py` (17)

| Test | Checks |
| --- | --- |
| `test_guard_blocks_connect` (brief) | `create_connection(("127.0.0.1", 9))` and `getaddrinfo("example.com", 443)` raise `NetworkBlockedError` |
| `test_url_recognizer_works_offline` (brief) | the engine still finds a URL, no "Public Suffix List" in `caplog` |
| `test_the_error_is_an_os_error_with_a_plain_message` | subclass of `OSError`, exact message |
| `test_internet_sockets_cannot_connect_send_bind_or_listen` x10 | `connect`, `connect_ex`, `sendto`, `bind`, `listen` x IPv4, IPv6 |
| `test_local_sockets_still_work` | `socketpair`, and AF_UNIX `bind`/`listen`/`connect`/`connect_ex`/`accept` and datagram `sendto` (relative socket names: macOS test folders exceed the 104-character limit) |
| `test_installing_twice_changes_nothing` | the five methods, the two functions and `tldextract.extract` are the same objects after a second call (so never wrapped twice) |
| `test_tldextract_reads_the_list_it_ships_with` | extractor is a `TLDExtract` with `suffix_list_urls == ()` and the snapshot fallback; `forums.bbc.co.uk` splits to `co.uk`; no warning |
| `test_tldextract_leaves_no_cache_behind` | subprocess with an empty `HOME`: right answer, empty stderr, no file written under `HOME` |

### `tests/test_logging.py` (8)

File in the log folder; line format (time, module, level, message); level decides what is written; second call keeps one handler and one line per record; another data folder moves the log (one handler, old file untouched); rotation (1.1 MB gives exactly `themask.log` + `.1`; 5 MB gives `.1` to `.3` and no `.4`, every file at most 1 MB; `maxBytes`/`backupCount` pinned); presidio logger is WARNING after setup even if it was DEBUG before; the engine's line for a sample (name, amount, e-mail) fully matches the `key=value` pattern, holds no finding text and shares no 3-letter word with the input.
An autouse fixture puts the `themask` and `presidio-analyzer` loggers back after each test and closes the handlers it did not find (no leaked file handles; `-W error` passes).

### `tests/test_main.py` (2)

`python -m themask` in a subprocess with `THEMASK_DATA_DIR` set: exit 0, stdout exactly `The MASK 0.1.0\n`, empty stderr, `logs/themask.log` exists; and `runpy.run_module("themask", run_name="__main__")` followed by `socket.create_connection` in the same process raises `NetworkBlockedError` (the entry point installs the guard).

## TDD evidence

**RED** (before any production code):

```
$ uv run pytest -q tests/test_netguard.py tests/test_logging.py tests/test_main.py
ERROR tests/test_netguard.py   ... ModuleNotFoundError: No module named 'themask.netguard'
ERROR tests/test_logging.py    ... ModuleNotFoundError: No module named 'themask.logging_setup'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.21s
$ uv run pytest -q tests/test_main.py
FAILED tests/test_main.py::test_python_m_themask_prints_the_name_and_version
FAILED tests/test_main.py::test_the_entry_point_installs_the_network_guard   (No module named themask.__main__)
2 failed in 0.37s
```

Expected: the modules did not exist.

**GREEN**: `uv run pytest -q tests/test_netguard.py tests/test_logging.py tests/test_main.py` gave `27 passed in 2.76s` on the first run after the implementation. Because that was smooth, I checked that the tests can fail: 13 mutations, each applied to a copy of the source, run, and restored (the sources were compared byte for byte afterwards). Each was caught:

| Mutation | Test that failed |
| --- | --- |
| socket-method check never true (guard does nothing) | `...[IPv4-connect]` |
| `create_connection`/`getaddrinfo` return instead of raising | `test_guard_blocks_connect` |
| AF_UNIX blocked too | `test_local_sockets_still_work` |
| no "already installed" memo | `test_installing_twice_changes_nothing` |
| tldextract without `cache_dir=None` | `test_tldextract_leaves_no_cache_behind` |
| tldextract with its default URLs | `test_tldextract_reads_the_list_it_ships_with` |
| a new handler on every call | `test_the_level_decides_what_is_written` |
| limit 2 MB instead of 1 MB | rotation test |
| presidio logger not held | `test_the_presidio_logger_is_held_at_warning` |
| handler never moves with the data folder | `test_another_data_folder_moves_the_log_there` |
| engine logs the first 20 characters of the text | engine log test |
| engine logs the first finding's text | engine log test |
| engine logs at DEBUG instead of INFO | engine log test |

## The whole suite under the guard

`uv run pytest -q` (conftest installs the guard): **2490 passed in 50.03 s**, no existing test or dependency needed a change. Because a library may catch the `OSError` and fall back silently (a pass would hide it), I ran the suite once more with a scratch plugin (not committed, in the scratchpad) that records a stack trace whenever a `NetworkBlockedError` is created. Result: the guard fired **13 times, all 13 from `tests/test_netguard.py`** (2 in `test_guard_blocks_connect`, 1 in the message test, 10 parametrised), none from any other test, spaCy, Presidio, keyring, pdfplumber, Faker or the corpus builder. So nothing in the suite so much as tried an internet socket.
Also checked by hand: with the guard on, a default `tldextract.TLDExtract(cache_dir=None)` does try the net and logs `WARNING:tldextract:Exception reading Public Suffix List url https://publicsuffix.org/...` (then falls back to the snapshot); the installed extractor gives the same answer silently.
`uv run python -m themask` prints `The MASK 0.1.0` and creates `logs/themask.log` (empty) in `THEMASK_DATA_DIR`.

## Files changed

- New: `src/themask/netguard.py`, `src/themask/logging_setup.py`, `src/themask/__main__.py`, `tests/test_netguard.py`, `tests/test_logging.py`, `tests/test_main.py`
- Modified: `src/themask/detect/engine.py` (+18/-2), `tests/conftest.py` (+6)
- Not touched: `paths.py` (already has `log_dir()`), README, pyproject, any other test.

## Self-review

- Completeness: every item of the brief and of R77 is there except the deferred `test_log_has_no_document_content`. When it is added it can live in `tests/test_logging.py` (the autouse fixture there already restores the loggers), and the log-line rule in the docstring is what it enforces.
- Quality: one responsibility per file; the guard has no logging dependency, logging has no guard dependency. Names follow the repo's plain-English style; comments say why (the relative AF_UNIX names, `cache_dir=None`, the type ignore).
- Discipline: no extras beyond the decisions listed above. I did not add `sendmsg`/`gethostbyname*` blocking because R77 lists the functions explicitly.
- Testing: tests check behaviour (real sockets, real files, a real subprocess), run in any order and alone, leave no logger or handler state behind.

## Concerns

1. Decisions 1 to 6 above deviate from, or interpret, the brief; none changes an interface the brief names.
2. The known gaps of the guard (`sendmsg`, `gethostbyname*`, child processes, Windows `socketpair`) are by the R77 list; decide whether any should be closed now.
3. Task 15's export reaches `Engine.analyze` again through the leak check's re-analysis of the masked file (`leakcheck.rescan_detection` calls `pipeline.analyze`), which only adds lines of the same counts-only kind; the later content test should still pass with them.

---

## Fix round 1 (R80)

**Commit:** `94fda8e fix: guard sendmsg, create_server and the resolver calls; offline submodule extractor (R80)` (on top of `6beb246`; tree clean)
**Result:** full suite **2500 passed in 49.9 s** (2490 + 10 new tests), under the guard. `ruff check src tests tools`, `ruff format --check src tests tools` and `mypy src` (35 files) clean; the three test files also pass under `-W error`.

### The review's findings, reproduced first

On `6beb246`, with only loopback and `localhost` used so nothing could leave the computer:

```
sendmsg: SENT 1 bytes (not blocked)
gethostbyname: returned '127.0.0.1' (not blocked)
gethostbyname_ex: returned ('localhost', [], ['127.0.0.1']) (not blocked)
gethostbyaddr: returned ('localhost', ['1.0.0.127.in-addr.arpa'], ['127.0.0.1']) (not blocked)
getnameinfo: returned ('localhost', 'http') (not blocked)
create_server raised OSError | [Errno None] None (while attempting to bind on address ('127.0.0.1', 0)) | is NetworkBlockedError: False
getfqdn('127.0.0.1') -> 1.0.0.127.in-addr.arpa
```

All of them as the review said. My original report listed `sendmsg` and `gethostbyname*` as "not on the R77 list"; R80 closes them.

### What changed

`src/themask/netguard.py`
- `sendmsg` joins `_GUARDED_METHODS` (raises for AF_INET and AF_INET6 only, exactly like `sendto`).
- `create_server`, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr` and `getnameinfo` join `_BLOCKED_FUNCTIONS`; each always raises `NetworkBlockedError` itself. `create_server` therefore no longer reaches `bind()`, whose error the standard library rebuilds as a bare `OSError` from `errno`/`strerror` (both `None` for our error), so the type and the message are kept now.
- `socket.getfqdn` needed no change of its own: it asks `gethostbyaddr`, catches the `OSError` and returns the name it was given, so it now makes no lookup (a Mac answered `1.0.0.127.in-addr.arpa` before). It is stated in the docstring and has a test.
- `tldextract.tldextract.TLD_EXTRACTOR = offline`, the same object as `tldextract.extract`. The submodule's `extract()` reads that global on every call, so a `from tldextract import extract` made before the guard went on stays offline. `mypy` accepts this assignment without an ignore.
- The module docstring now lists exactly what raises (methods, functions), what `getfqdn` does, what stays open (Unix-domain and every other non-internet socket), and a "What the guard does not cover" list: the C module `_socket` and native libraries; a child process (starts unguarded, has to call `install_network_guard()` itself); Windows (`socketpair` there is a loopback AF_INET socket, so the Windows phase needs an exception). It calls the guard a tripwire, not a sandbox.
- Still open on purpose: creating a socket, `socketpair`, `gethostname`, `getservbyname`/`getprotobyname` (they read the computer's own settings and tables, no network).

`tests/test_netguard.py` (17 -> 27 tests)
- `sendmsg` added to the parametrized internet test: IPv4 and IPv6 (+2).
- `test_servers_and_name_lookups_raise_the_guards_own_error`: `create_server` on IPv4 and IPv6, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`, `getnameinfo`, each with `pytest.raises(NetworkBlockedError, match=<the message>)`, so a bare `OSError` from `create_server` fails it (+6). Only `localhost`, `127.0.0.1` and `::1` are used.
- `test_getfqdn_makes_no_lookup` (+1): `getfqdn("127.0.0.1") == "127.0.0.1"`.
- `test_local_sockets_still_work` also does `sendmsg` on an AF_UNIX `socketpair` and `sendmsg` with an address on an AF_UNIX datagram socket.
- `test_installing_twice_changes_nothing` covers all seven functions and `tldextract.tldextract.TLD_EXTRACTOR`.
- `test_the_functions_a_program_took_earlier_use_the_same_extractor` (+1): `TLD_EXTRACTOR is tldextract.extract`; the submodule's own `extract` function is a different object and answers `co.uk`.
- `test_tldextract_leaves_no_cache_behind` now also takes `extract` with `from tldextract import extract` before installing the guard, and calls both it and the new one in the subprocess (empty `HOME`): both print `co.uk`, stderr empty, no file under `HOME`.
- My own `test_the_error_is_an_os_error_with_a_plain_message` now asks `getaddrinfo` for `localhost`; only the brief's `test_guard_blocks_connect` still names `example.com`. The module docstring says so.

### TDD evidence

**RED** (new tests first, against the unchanged guard): `uv run pytest -q tests/test_netguard.py` gave `11 failed, 16 passed`. The failures, with their reasons:
- `[IPv4-sendmsg]`, `[IPv6-sendmsg]`, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`, `getnameinfo`: `Failed: DID NOT RAISE NetworkBlockedError` (6);
- `create_server-IPv4/IPv6`: `OSError: [Errno None] None (while attempting to bind on address ('127.0.0.1', 0))`, not our error (2);
- `test_getfqdn_makes_no_lookup`: `assert '1.0.0.127.in-addr.arpa' == '127.0.0.1'`;
- `test_the_functions_a_program_took_earlier_use_the_same_extractor`: `TLD_EXTRACTOR` is not `tldextract.extract`;
- `test_tldextract_leaves_no_cache_behind`: stderr held `Exception reading Public Suffix List url ...` from the function taken before the guard.

**GREEN**: `uv run pytest -q tests/test_netguard.py tests/test_logging.py tests/test_main.py` gave `37 passed in 2.99s`; the whole suite `2500 passed in 49.87s`.

**Mutation checks** of the new behaviour (a copy of the source is changed, the tests run, the file is restored and compared byte for byte); each was caught:

| Mutation | Test that failed |
| --- | --- |
| `sendmsg` not in `_GUARDED_METHODS` | `[IPv4-sendmsg]` |
| `create_server` not blocked | `create_server-IPv4` |
| `gethostbyname` / `gethostbyname_ex` / `gethostbyaddr` / `getnameinfo` not blocked (one run each) | the case of the same name |
| `gethostbyaddr` not blocked, `getfqdn` test alone | `test_getfqdn_makes_no_lookup` |
| `sendmsg` also blocked for AF_UNIX | `test_local_sockets_still_work` |
| `TLD_EXTRACTOR` not replaced | `test_the_functions_a_program_took_earlier_use_the_same_extractor`, and alone `test_tldextract_leaves_no_cache_behind` |
| no "already installed" memo | `test_installing_twice_changes_nothing` |

### Does anything new fire in the full suite?

No. I ran the whole suite once more with the same scratch plugin as before (not committed; it now records the test id of every `NetworkBlockedError` created in the process): `2500 passed in 50.58s`, and the guard fired **22 times, every one from `tests/test_netguard.py`, none from any other test**. The tally matches what the tests do: the earlier 13 + 2 (`sendmsg` IPv4/IPv6) + 6 (`create_server` x2, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`, `getnameinfo`) + 1 (`getfqdn`, whose error is raised inside `gethostbyaddr` and swallowed by `getfqdn`) = 22. Nothing else in the suite (spaCy, Presidio, keyring, pdfplumber, Faker, the corpus builder, pytest itself) calls `sendmsg` on an internet socket, `create_server` or any of the lookup functions, not even in a way that a library would catch and hide. The subprocess tests run in processes the plugin does not see; they pass.

### Files changed in the fix

- Modified: `src/themask/netguard.py`, `tests/test_netguard.py`. Nothing else.

### Remaining

- The log-content test (`test_log_has_no_document_content`) still waits for Task 15, as before.
- Open by design, now written in the docstring: `_socket` and native libraries, child processes, Windows `socketpair`.

---

## Round 2: the log-content test (Task 15 is in)

**Commit:** `6bec7ea test: the log holds no document content; pdfminer held at WARNING like Presidio`
**Head it sits on:** `92d396f` (mac-v1 with Tasks 15, 20 and 21). The branch was fast-forwarded to `39419f5` (Task 15) before I started and again to `92d396f` (Tasks 20+21) while I worked; my commit is on top of the second and everything below ran on it. Task 20 has already replaced my temporary `__main__.py` and `tests/test_main.py` with the real window entry point, as planned; `ui/app.py` calls `setup_logging()` and the worker's three log lines (`engine loaded seconds=…`, `engine failed error=<TypeName>`, `analysis failed error=<TypeName>`) follow the rule.
**Result:** full suite **2719 passed in 87.1 s** on `6bec7ea`, under the guard; `ruff check src tests tools`, `ruff format --check` and `mypy src` (43 files) clean; tree clean.

### 1. The brief's test, as written

`test_log_has_no_document_content` is in `tests/test_logging.py`: `THEMASK_DATA_DIR` to `tmp_path`, `setup_logging("DEBUG")`, `load_sources([corpus / "supply-01.docx"], False)`, `ReviewState.from_analysis(analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set()))`, `export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None)`, then `text = normalize(log.read_text())`, `assert text`, and no `normalize(t["value"])` of the 41 truth values of `supply-01.truth.json` in it. Only ruff's line breaks and type hints differ from the brief.

It **passed on the first run** (`1 passed in 6.57s`). The log it checks holds the engine's counts lines. A pass the first time proves little, so I checked that it can fail: with `Engine.analyze` changed to log each finding's text at DEBUG, it fails (together with the engine counts test and the fresh-process test below).

### 2. Who quotes the document at DEBUG, measured

I did not stop at the pass. With the **root** logger at DEBUG and a listener on it (the worst case), a Word and a PDF export of supply-01 produced:

| Top-level logger | Records | Records holding a truth value | Example (made-up corpus data) |
| --- | --- | --- | --- |
| `pdfminer` | 21,467 | **192** | `nexttoken: (626, b'Northwind Trading B.V.')` |
| `presidio-analyzer` | 529 | **22** | `Context list is: register company … number 59192807 …` |
| `themask` | 4 | 0 | the engine's counts lines |
| `spacy` | 0 | 0 | none; its logging calls (read in the source) name pipeline components, model paths and training steps, not text |

The size of the leak is the point: neither library reaches **our file** today, because the file handler is on the `themask` logger only (structural), and the root logger is at WARNING in a normal run. But the brief's test cannot see a handler that someone later puts on the root logger (see the mutation table: the test stays green), and Presidio was the only library held.

### 3. The fix to the logging

`setup_logging` now holds `pdfminer` at WARNING next to `presidio-analyzer` (`_HELD_AT_WARNING = ("presidio-analyzer", "pdfminer")`). Why these two and not spaCy: spaCy printed nothing of the text in the probe and its code logs only pipeline and model events; the tuple takes one more name if you want it held anyway. The module docstring now says which libraries quote the document and how, that the hold sits on the name the library logs under so that loggers it makes on import (`pdfminer.psparser`) inherit it whichever came first, and that spaCy is not held and why. Presidio's other logger, `decision_process` (it has its own stderr handler and is set to INFO when Presidio is imported), only speaks when an `AnalyzerEngine` is built with `log_decision_process=True`; ours is not, so it is left alone.

### 4. Library loggers created later, in a fresh process

`test_libraries_imported_after_the_log_is_set_up_stay_quiet` runs a subprocess in the app's own order: guard, `setup_logging("DEBUG")`, **then** the root logger set to DEBUG with a listener, and only then the imports of the engine (Presidio, spaCy) and, through the export, pdfminer. It exports supply-01 as a Word file and as a PDF and prints a JSON report. Asserted: the listener heard the engine's lines; **no record of any logger** carries a truth value; the log file is non-empty and holds none; and the effective levels of `presidio-analyzer`, `pdfminer` and `pdfminer.psparser` (made when pdfminer was imported, after the setup) are all WARNING. By hand, the report was `heard: 15` (the engine's 4 lines and 11 Presidio registry notices at WARNING, "Recognizer not added to registry because language is not supported ..."), `leaks: []`, `file_leaks: []`, levels 30/30/30, empty stderr; the log file holds the four counts lines and nothing else. It takes about 5 s. `test_libraries_that_quote_the_document_are_held_at_warning` replaced the Presidio-only test: both libraries, plus a logger made later under the same name.

### 5. TDD and mutation evidence

**RED** (the two new tests against the unchanged `setup_logging`): `2 failed, 9 passed`: the hold test for pdfminer (`assert 10 == 30`: `<Logger pdfminer (DEBUG)>.level`) and the fresh-process test (leaks from `pdfminer.pdfinterp` and `pdfminer.psparser`). **GREEN**: `11 passed in 9.82s` for `tests/test_logging.py`, then the full suite.

**Mutations** (each applied to a copy, run, restored; the sources were compared byte for byte afterwards):

| Mutation | Failing tests |
| --- | --- |
| pdfminer not held | hold test `[pdfminer]`, fresh-process test |
| presidio-analyzer not held | hold test `[presidio-analyzer]`, fresh-process test |
| the engine logs every finding's text at DEBUG | the brief's content test, the engine counts test, fresh-process test |
| file handler on the **root** logger and nothing held | six tests, among them both hold tests and the fresh-process test; **the brief's content test stays green** (root is at WARNING in a normal process, so no library record exists to be collected) |

The last row is why the fresh-process test exists: it sets the root to DEBUG and is the one that sees a structural leak.

### 6. The guard over the new code

I ran the full suite once more with the same scratch plugin as before (not committed): `2719 passed`, and the guard fired **22 times, all in `tests/test_netguard.py`** (as in Fix round 1). Nothing in Task 15's export, the PDF reading (pdfplumber/pdfminer) or Tasks 20 and 21 tried an internet socket or a name lookup, not even one that a library would catch.

### 7. Files changed in Round 2

Modified: `src/themask/logging_setup.py` (+ the hold, docstring), `tests/test_logging.py` (the content test, the hold test for both libraries, the fresh-process test, the restoring fixture covering both libraries). Nothing else.

### Open

Nothing from the brief is left. A decision for you: whether to hold `spacy` too (one name in `_HELD_AT_WARNING`; I did not, for the reasons in section 3).
