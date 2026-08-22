# pyactivesync

A Python client library exclusively for Exchange ActiveSync (EAS) 16.1, implementing
enough of [MS-ASCMD] (the command protocol) and [MS-ASWBXML] (the binary
XML encoding) to talk to a real Exchange server: folder listing, mail
sync, item/attachment fetch, sending mail, folder management, moving
items, directory search, and push notifications via `Ping`.

[MS-ASCMD]: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-ascmd/
[MS-ASWBXML]: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-aswbxml/

## Protocol version

Pyactivesync targets **EAS 16.1 exclusively**. Every request carries
`MS-ASProtocolVersion: 16.1`; the version is not configurable and the
library does not negotiate or fall back to older protocol versions. The
server must advertise EAS 16.1 support.

## Install

```
pip install pyactivesync
```

## Usage

```python
from email.message import EmailMessage
from pyactivesync import Client, FolderType, BodyType

with Client(
    server="mail.example.com",
    username=r"CORP\jdoe",       # NTLM-style domain\user, or a plain email -- both work
    password="...",
    device_id="MyApp01",          # caller-provided; persist it yourself for a stable
                                    # device identity across runs -- pyactivesync doesn't
                                    # persist anything to disk on its own
) as client:
    folders = client.list_folders()
    inbox = next(f for f in folders if f.type == FolderType.INBOX)

    result = client.sync_folder(inbox.id)                              # bootstrap
    result = client.sync_folder(inbox.id, sync_key=result.sync_key)     # Add/Change/Delete

    for item in result.added:
        print(item.fields.get("Email.Subject"))
        body = client.fetch_item(inbox.id, item.server_id, body_type=BodyType.HTML)

    msg = EmailMessage()
    msg["To"] = "someone@example.com"
    msg["Subject"] = "hello from pyactivesync"
    msg.set_content("plain text body")
    client.send_mail(msg)
```

`Client` is a context manager wrapping one `requests.Session` -- EAS is
stateless HTTP (an auth header plus a `PolicyKey` header), so unlike an
IMAP connection there's no server-side session to tear down; `__exit__`
just closes the HTTP session. `provision()` (the device policy handshake)
is called lazily on first use if you don't call it explicitly.

Folder and item ids are plain strings (`"9"`, `"9:1"`), matching EAS's
own `ServerId` format exactly -- there's no synthetic id layer to keep in
sync with a local cache.

## Command coverage

| Command | Client method |
|---|---|
| `Provision` | `Client.provision()` (also called lazily) |
| `FolderSync` | `Client.list_folders()` |
| `Sync` | `Client.sync_folder()` |
| `GetItemEstimate` | `Client.get_item_estimate()` |
| `ItemOperations` Fetch (body) | `Client.fetch_item()` |
| `ItemOperations` Fetch (attachment) | `Client.fetch_attachment()` |
| `SendMail` | `Client.send_mail()` |
| `FolderCreate`/`FolderUpdate`/`FolderDelete` | `Client.create_folder()`/`update_folder()`/`delete_folder()` |
| `MoveItems` | `Client.move_item()` |
| `Ping` | `Client.ping()` |
| `ResolveRecipients` | `Client.resolve_recipients()` |
| `Search` (GAL) | `Client.search_gal()` |
| `Search` (Mailbox, structured) | `Client.search_mailbox()` |
| `Find` (GAL/Mailbox free text) | `Client.find_gal()`/`Client.find_mailbox()` |
| `Settings` (Oof get/set) | `Client.get_oof()`/`set_oof()` |

**Not implemented**: `MeetingResponse`, `ValidateCert`, `SmartForward`/`SmartReply`.
Documented as unimplemented, not silently missing.

**Non-goals**: an EAS *server*; Autodiscover (pass a server hostname
directly); Calendar/Contacts *write* operations (read via `Sync` is
supported); NTLM auth (Basic auth only -- `requests` doesn't do NTLM
without an extra dependency); credential storage of any kind (that's the
caller's business).

`search_mailbox()` deliberately has no `free_text=` parameter: full-text
`Search` conditions are known to fail against real Exchange servers with
`Store.Status=110`, a server-side bug in EAS's `Search` handling rather
than a WBXML encoding issue (confirmed by cross-checking the same
mailbox's content index through an unrelated protocol, which returns
correct results for the same query). Shipping that parameter would just
reproduce the failure for every caller.

EAS 16.1's separate `Find` command is available through `find_mailbox()`
and `find_gal()`. Both return a `FindResult` containing the server's status,
range, actual number of returned items, reusable search id, and flattened
result properties. This is the supported free-text mailbox-search path:
unlike the older `Search` command, `Find` returned matching mailbox results
in live EAS 16.1 testing. `FindResult.total` is computed from the returned
results rather than trusting the server's advisory `Find:Total` value.

## Development

```
pip install -e '.[dev]'
pytest
ruff check .
mypy pyactivesync tests
```

Unit tests (WBXML codec against golden byte fixtures, codepage table
sanity checks) require no network and run in CI on every push. Live
integration tests in `tests/test_client_live.py` are skipped unless
`PYACTIVESYNC_TEST_SERVER`, `PYACTIVESYNC_TEST_USER`, and `PYACTIVESYNC_TEST_PASSWORD` are
set, and only ever create/rename/delete objects they create themselves --
pre-existing folders and items are never touched.

## License

MIT
