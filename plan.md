# py-eas: implementation & publishing plan

**Goal**: a real, installable (`pip install py-eas`) Python client library for
Exchange ActiveSync (EAS/MS-ASCMD/MS-ASWBXML), generalizing the protocol
knowledge validated this session in `../eas-experiment/eas_test.py` against
a live server (`webmail.kth.se`) into a clean, tested, documented, properly
packaged library — not a script hardcoded to one account.

**Why this is worth publishing**: confirmed by exhaustively grepping the
full PyPI index (874,722 packages) — nothing maintained exists. The closest
hit, `wbxml` (PyPI), is a decade-stale wrapper around the C library
`libwbxml` that only does the binary-XML codec layer, with zero EAS
command-layer, auth, or HTTP client on top. `py-eas` is a green field.

## 1. Naming

- **PyPI distribution name: `py-eas`** — confirmed available (`pypi.org/pypi/py-eas/json` → 404).
- **Import package name: `py_eas`** (not `pyeas`) — `pyeas` is already taken on PyPI by an unrelated evolutionary-algorithms library (confirmed this session while checking for existing EAS libraries); reusing that import name would collide for anyone with both installed. `py-eas` → `py_eas` is the standard dash→underscore mapping and PEP 503 already treats them as the same normalized project name, so there's no mismatch to explain in docs.
- Action item: publish a placeholder `0.0.1` early to reserve the name on PyPI (common practice; a name that's free today isn't guaranteed free next week).

## 2. Scope for v1

Every command below was empirically validated end-to-end against a real
Exchange server this session (see `../eas-experiment/README.md`'s feature
table) — v1 covers exactly that validated surface, nothing speculative:

| Command | Client method |
|---|---|
| `Provision` (incl. required `Settings.DeviceInformation` on request 1) | `Client.provision()` — also called lazily on first use |
| `FolderSync` | `Client.list_folders()` |
| `Sync` (bootstrap + incremental via `SyncKey`) | `Client.sync_folder(folder_id, sync_key=...)` |
| `GetItemEstimate` | `Client.get_item_estimate(folder_id, sync_key)` |
| `ItemOperations` Fetch (body) | `Client.fetch_item(folder_id, item_id, ...)` |
| `ItemOperations` Fetch (attachment via `FileReference`) | `Client.fetch_attachment(file_reference)` |
| `SendMail` (WBXML `ComposeMail` wrapper, protocol v14.1) | `Client.send_mail(message, ...)` |
| `FolderCreate`/`FolderUpdate`/`FolderDelete` | `Client.create_folder()`/`update_folder()`/`delete_folder()` |
| `MoveItems` | `Client.move_item(item_id, src_folder_id, dst_folder_id)` |
| `Ping` | `Client.ping(folder_id, ...)` |
| `ResolveRecipients` | `Client.resolve_recipients(address)` |
| `Search` (GAL scope; mailbox scope with a structured query also works, see §7 — only `FreeText`/full-text is broken server-side, confirmed not a library bug) | `Client.search_gal(query)` / `Client.search_mailbox(folder_id, condition)` |

**Explicitly out of scope for v1** (not executed this session, for good
reason — real side effects or no test coverage): `MeetingResponse`,
`ValidateCert`, `SmartForward`/`SmartReply`. Documented as unimplemented,
not silently missing — same "documented gap, not a silent bug" discipline
`jmap-proxy-go`'s README uses for its own known limitations.

**Also out of scope for v1, explicit non-goals**: Autodiscover (EAS has one,
like EWS; this library takes a server URL directly, matching how
`eas_test.py` was validated — no autodiscovery flow was tested this
session, don't claim support for one that hasn't been exercised). Calendar/
Contacts *write* operations (read-only `Sync` against those folders was
validated and is in scope as data, see §4; creating/editing events or
contacts was not tested).

## 3. Package layout

Flat layout, `_`-prefixed internal modules, matching the Python
conventions already in use for this user's other PyPI packages:

```
py-eas/
  py_eas/
    __init__.py        # public surface: Client, exceptions, models re-exported
    client.py           # Client class — one method per command in §2's table
    exceptions.py        # EASError, ProtocolError, StatusError(code, meaning), ProvisionError
    models.py             # dataclasses: Folder, SyncResult, Attachment, GalEntry, Recipient, PingResult
    _wbxml.py              # WBXMLWriter/WBXMLReader — ported near-verbatim from eas_test.py
    _codepages.py           # CODEPAGES/PAGE_INDEX tables, verified against the MS-ASWBXML spec
    _mime.py                 # MIME construction (send) / parsing (fetch) helpers, stdlib email-based
    _http.py                  # thin requests.Session wrapper: auth header, PolicyKey header, retries
    cli.py                     # `py-eas` console-script: list-folders, sync, send, fetch, ping
  tests/
    conftest.py
    test_wbxml.py         # golden-byte codec tests captured from real request/response bytes this
                            # session — no network needed, this is the highest-value test suite
    test_codepages.py      # structural sanity: no duplicate tokens per page, etc.
    test_models.py
    test_client_live.py     # gated behind PY_EAS_TEST_SERVER/PY_EAS_TEST_USER/PY_EAS_TEST_PASSWORD
                              # env vars; skipped (not failed) when unset, so `pytest` stays green on
                              # a plain checkout — same pattern jmap-proxy-go's difftest suite uses
  .github/workflows/ci.yml     # lint + type-check + unit tests, every push/PR
  .github/workflows/release.yml # build + publish to PyPI via trusted publisher, on GitHub Release
  pyproject.toml               # hatchling backend
  README.md
  LICENSE                       # MIT
  .gitignore
```

## 4. Public API sketch

```python
from py_eas import Client, FolderType, BodyType

with Client(
    server="webmail.kth.se",
    username=r"ug.kth.se\monp",   # NTLM-style domain\user, or a plain email — both validated
    password=...,
    device_id="MyApp01",           # caller-provided; persisted by the caller if they want stable
                                     # device identity across runs (this library doesn't persist
                                     # anything to disk itself — no config/credential storage,
                                     # that's the caller's job, matching keyring usage in
                                     # eas_test.py being CLI-only, not baked into the library)
) as client:
    folders = client.list_folders()
    inbox = next(f for f in folders if f.type == FolderType.INBOX)

    result = client.sync_folder(inbox.id)          # bootstrap (SyncKey="0" internally)
    result = client.sync_folder(inbox.id, sync_key=result.sync_key)  # actual Add/Change/Delete

    for item in result.added:
        body = client.fetch_item(inbox.id, item.server_id, body_type=BodyType.HTML)

    client.send_mail(my_email_message)              # stdlib email.message.EmailMessage in, MIME
                                                       # built + WBXML-wrapped + POSTed
```

Design decisions worth stating up front:

- **`email.message.EmailMessage` (stdlib) as the message type for `send_mail`**, not a custom
  message class — every Python user already knows this API, and `_mime.py`'s job is exactly
  "turn a stdlib email object into the CRLF-normalized bytes EAS's `ComposeMail.MIME` opaque
  field needs" (§7's CRLF gotcha), which is a solved, narrow translation problem.
- **`Client` is a context manager** wrapping one `requests.Session` — EAS is stateless HTTP
  (Basic/NTLM auth header + `PolicyKey` header), so unlike an IMAP `Conn` there's no persistent
  server-side session to keep alive or tear down; `__exit__` just closes the HTTP session.
- **`provision()` is called lazily** on first command if not called explicitly — most callers
  shouldn't need to think about the two-round-trip `Provision` handshake at all.
- **Folder ids and item ids are plain strings** (`"9"`, `"9:1"`), matching EAS's own `ServerId`
  format exactly — no synthetic id layer, nothing to keep in sync with a local cache.

## 5. Milestones

- **M0 — codec port.** Port `eas_test.py`'s `WBXMLWriter`/`WBXMLReader` and the verified
  `CODEPAGES`/`PAGE_INDEX` tables to `_wbxml.py`/`_codepages.py`, `from __future__ import
  annotations` + full type hints throughout. Golden-byte tests from the exact request/response
  hex dumps captured this session (Provision, FolderSync, Sync bootstrap+delta, SendMail) —
  these bytes are already known-correct against a real server, capture them once as fixtures
  instead of needing a live server for every codec-level test run.
- **M1 — read path.** `provision`, `list_folders`, `sync_folder`, `get_item_estimate`,
  `fetch_item`, `fetch_attachment`. This is the highest-value, lowest-risk milestone — every
  command in it was validated end-to-end this session.
- **M2 — write path.** `create_folder`/`update_folder`/`delete_folder`, `move_item`. Test against
  a real server using the same discipline `eas_test.py` used: only ever create/rename/delete
  *objects the test suite itself created*, never touch pre-existing folders/items (`test_client_live.py`
  should assert this by construction — e.g. every test folder name prefixed `py-eas-test-`, and a
  session-scoped fixture that lists folders before and after to assert the pre-existing set is
  unchanged).
- **M3 — send path.** `send_mail`. Confirm the `ComposeMail` WBXML wrapper + CRLF handling from
  §7 ports correctly; this was the single trickiest bug this session (two silent-failure modes —
  `Status=101 InvalidContent` from wrong line endings, `Status=110`-shaped confusion from the
  wrong wrapper entirely) worth a dedicated regression test.
- **M4 — the rest.** `ping`, `resolve_recipients`, `search_gal`, `search_mailbox` (structured
  conditions only — date-range/property queries confirmed working, see §7; deliberately no
  `free_text=` parameter, since that specific condition is server-side broken against the test
  server and silently shipping it would just reproduce `Status=110` for callers). Lower priority
  than M1–M3 — useful, but not core mail-client functionality.
- **M5 — packaging & release.** `pyproject.toml` (hatchling), `ruff`+`mypy` clean, CLI
  (`cli.py`), README with real usage examples, GitHub Actions CI, PyPI trusted-publisher release
  workflow, tag `v0.1.0`.

## 6. Testing & CI

- **Unit tests** (`pytest`, no network): the WBXML codec against golden fixtures, codepage table
  sanity checks, MIME construction/parsing round-trips, model serialization. This is the bulk of
  the test suite and the part that can be verified continuously without any server.
- **Live integration tests** (`test_client_live.py`): gated behind
  `PY_EAS_TEST_SERVER`/`PY_EAS_TEST_USER`/`PY_EAS_TEST_PASSWORD`; `pytest.importorskip`-style
  skip (not fail) when unset, so `pytest` is green on a plain checkout and in CI by default. Run
  manually (or via a separate, manually-triggered CI job with repo secrets) against a real
  account before a release — mirrors `jmap-proxy-go`'s `JMAP_DIFFTEST_REFERENCE`/`_CANDIDATE`
  env-gated pattern exactly.
- **`pytest-cov`** for coverage reporting, per this user's standard Python conventions.
- **`ruff` + `mypy`** in dev deps, run in CI on every push/PR alongside tests.
- **GitHub Actions**: one workflow for CI (lint, type-check, unit tests, on push/PR), one for
  release (build sdist+wheel, `pypa/gh-action-pypi-publish` via **OIDC trusted publishing** — no
  long-lived PyPI API token stored as a repo secret — triggered on GitHub Release creation).

## 7. Protocol gotchas to carry over verbatim into the codec/client

Every one of these was found the hard way against a real server this
session (`../eas-experiment/`) and is exactly the kind of bug a fresh
implementation would silently reintroduce without this list:

- **WBXML codepage numbers must match the real MS-ASWBXML spec, not an arbitrary local enum
  order.** `_codepages.py` must use the real numbers: AirSync=0, Contacts=1, Email=2,
  AirNotify=3, Calendar=4, Move=5, ItemEstimate=6, FolderHierarchy=7, MeetingResponse=8, Tasks=9,
  ResolveRecipients=10, ValidateCert=11, Contacts2=12, Ping=13, Provision=14, Search=15, GAL=16,
  AirSyncBase=17, Settings=18, DocumentLibrary=19, ItemOperations=20, ComposeMail=21, Email2=22.
- **WBXML header is 3 bytes** (version, publicid, charset), **then a separate mb\_uint string-table
  length** — treating it as a fixed 4-byte header silently misaligns every subsequent byte.
- **`OPAQUE` (`0xC3`) binary fields need explicit handling** (mb\_uint length + raw bytes) or the
  reader misinterprets binary GUIDs (`ConversationId`, calendar timezone blobs) as nested tag
  structure and desyncs.
- **`Provision` needs `Settings.DeviceInformation` on the very first request**, or the server
  returns `Status=165` (`DeviceInformationRequired`) with no `PolicyKey`.
- **`SendMail` must use the WBXML `ComposeMail` wrapper at protocol v14.1**, not a raw
  `message/rfc822` POST body (that only works at protocol ≤12.1); the MIME bytes inside the
  `ComposeMail.MIME` opaque field must use **CRLF line endings** or the server returns
  `Status=101` (`InvalidContent`).
- **Don't hand-guess WBXML token tables past the well-documented ones** — `ResolveRecipients.To`
  was first guessed as `0x1A` (wrong; that's `Picture` — real value `0x10`), and an initial
  `Search` codepage guess was off-by-one throughout. The tables in `_codepages.py` were pulled
  from the official spec (`learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-aswbxml/`,
  full codepage index at `.../ms-aswbxml/toc.json`) — verified, not guessed.
- **`Search` in Mailbox scope works fine in general — isolated the failure to specifically the
  `FreeText` condition, and confirmed it's an EAS-specific bug, not a content-indexing outage.**
  A structured query (`GreaterThan`/date range) against the same account/folder/backend server
  returns `Store.Status=1` with correct results (`Total=96` on the test Inbox); swapping in a
  `FreeText` condition for the exact same request — confirmed same backend server via
  `X-BEServer` response headers on both — gets `Store.Status=110` (generic `ServerError`) every
  time, alone or combined with a working condition. The obvious hypothesis (Exchange Search
  content index down for that mailbox) was ruled out directly: EWS's equivalent full-text search
  (`QueryString`/AQS — the same engine and same content index ActiveSync `FreeText` would use)
  against the identical mailbox returns correct, accurate results (real match counts, zero for a
  nonsense keyword). So the index itself is healthy; the fault is isolated to ActiveSync's own
  `Search` handling. Filed as a precise report to the test server's IT support
  (`../eas-experiment/BUG-REPORT.md`) rather than left as an unexplained flake. `client.py`'s
  `search_mailbox` should accept structured conditions (date ranges, `Class`/`CollectionId`
  scoping) but **not** expose a `free_text=` parameter in v1 — that's not "not implemented yet",
  it's "known broken against real servers, don't ship an API that silently reproduces
  `Status=110` for every caller."

## 8. Open risks / questions to resolve during implementation

- **No EAS analogue of IMAP `APPEND`.** There's no tested way to inject an arbitrary message into
  a folder (e.g. a draft) without sending it via `SendMail`. Untested this session — needs
  verification against a real server (likely `Sync` `Add` with a full item body) before any
  draft-creation helper is added; v1 doesn't promise one.
- **Protocol version negotiation.** v1 hardcodes `MS-ASProtocolVersion: 14.1` (what was verified
  against `webmail.kth.se`). A more portable client would `OPTIONS` the server first and pick from
  the advertised `MS-ASProtocolVersions` list — worth doing before claiming broad server
  compatibility, but not required to ship a v1 that's honest about what it's tested against.
- **NTLM vs Basic auth.** This session's server accepted Basic auth directly (confirmed via the
  `WWW-Authenticate: Basic` challenge on unauthenticated `OPTIONS`); some EAS deployments require
  NTLM. `requests` doesn't do NTLM without an extra dependency (`requests-ntlm`) — decide whether
  that's a required or optional (`py-eas[ntlm]`) dependency once a server that needs it is
  available to test against, rather than guessing at the integration.

## 9. Non-goals

Explicitly not building: an EAS *server* (some other project's problem), Calendar/Contacts
*write* support (§2), Autodiscover, connection pooling/retry policies beyond `requests`'
defaults, or any credential storage (that's every caller's own business — `eas_test.py`'s use of
`keyring` was CLI-demo convenience, not something this library should bake in as a hard
dependency).
