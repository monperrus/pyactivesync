"""Public data types returned by :class:`pyactivesync.client.Client`."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class FolderType(IntEnum):
    """MS-ASCMD ``FolderHierarchy:Type`` values."""

    GENERIC = 1
    INBOX = 2
    DRAFTS = 3
    DELETED_ITEMS = 4
    SENT_ITEMS = 5
    OUTBOX = 6
    TASKS = 7
    CALENDAR = 8
    CONTACTS = 9
    NOTES = 10
    JOURNAL = 11
    USER_GENERIC = 12
    USER_MAIL = 13
    USER_CALENDAR = 14
    USER_CONTACTS = 15
    USER_TASKS = 16
    USER_JOURNAL = 17
    USER_NOTES = 18
    UNKNOWN = 19
    RECIPIENT_CACHE = 20


class BodyType(IntEnum):
    """MS-ASAIRSYNCBASE ``BodyPreference:Type`` / ``Body:Type`` values."""

    PLAIN_TEXT = 1
    HTML = 2
    RTF = 3
    MIME = 4


class OofState(IntEnum):
    """MS-ASCMD ``Settings:Oof:OofState`` values."""

    DISABLED = 0
    ENABLED = 1
    ENABLED_SCHEDULED = 2


@dataclass(frozen=True, slots=True)
class Folder:
    id: str
    parent_id: str
    type: FolderType
    name: str


@dataclass(frozen=True, slots=True)
class SyncItem:
    """One ``Add`` or ``Change`` entry from a ``Sync`` response.

    ``fields`` is a flat ``{tag_name: text}`` dump of every leaf element
    under ``ApplicationData`` (e.g. ``"Email.Subject"``), so it works
    across Email/Contacts/Calendar item classes without a per-class field
    table.
    """

    server_id: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncResult:
    sync_key: str
    added: list[SyncItem] = field(default_factory=list)
    changed: list[SyncItem] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    more_available: bool = False


@dataclass(frozen=True, slots=True)
class EmailChange:
    """One client-originated email mutation sent through ``Sync``.

    ``None`` means leave that property unchanged. A delete cannot be combined
    with read or flag changes.
    """

    server_id: str
    read: bool | None = None
    flagged: bool | None = None
    delete: bool = False


@dataclass(frozen=True, slots=True)
class EmailChangesResult:
    """Result of applying one batch of email changes.

    EAS commonly omits per-item responses for successful changes. ``statuses``
    therefore starts at success (``"1"``) for every requested item and is
    overwritten by any explicit status returned by the server.
    """

    sync_key: str
    statuses: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmailAddResult:
    """Result of creating one draft email with client-originated ``Sync Add``.

    ``server_id`` is present on success.  A rejected item still advances the
    collection synchronization key and is returned with its per-item status.
    """

    sync_key: str
    client_id: str
    status: str
    server_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentInfo:
    """Attachment metadata as found in a fetched item's properties.

    Use ``file_reference`` with ``Client.fetch_attachment()`` to download
    the actual bytes.
    """

    display_name: str
    file_reference: str
    content_type: str | None = None
    estimated_data_size: int | None = None


@dataclass(frozen=True, slots=True)
class GalEntry:
    display_name: str | None = None
    email_address: str | None = None
    phone: str | None = None
    office: str | None = None
    title: str | None = None
    company: str | None = None
    alias: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    home_phone: str | None = None
    mobile_phone: str | None = None


@dataclass(frozen=True, slots=True)
class FindItem:
    """One result returned by the EAS 16.1 ``Find`` command.

    Mailbox results normally have both ids. GAL results have neither. All
    returned properties are preserved as dotted WBXML names in ``fields``.
    """

    server_id: str | None = None
    collection_id: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FindResult:
    """One page of EAS 16.1 ``Find`` results.

    ``total`` is the number of items actually present in this response page,
    not the server's advisory ``Find:Total`` value.
    """

    search_id: str
    status: str
    range: str | None = None
    total: int = 0
    items: list[FindItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Recipient:
    type: str | None
    display_name: str | None
    email_address: str | None


@dataclass(frozen=True, slots=True)
class PingResult:
    status: str
    changed_folder_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OofMessage:
    """One scope of an Out-of-Office autoreply (``Settings:Oof:OofMessage``).

    ``applies_to`` is one of ``"Internal"``, ``"ExternalKnown"``,
    ``"ExternalUnknown"``, mirroring which of the three
    ``AppliesTo*`` marker tags was present.
    """

    applies_to: str
    enabled: bool
    reply_message: str | None = None
    body_type: str | None = None


@dataclass(frozen=True, slots=True)
class OofSettings:
    state: OofState
    start_time: str | None = None
    end_time: str | None = None
    messages: list[OofMessage] = field(default_factory=list)
