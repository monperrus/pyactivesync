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
class Recipient:
    type: str | None
    display_name: str | None
    email_address: str | None


@dataclass(frozen=True, slots=True)
class PingResult:
    status: str
    changed_folder_ids: list[str] = field(default_factory=list)
