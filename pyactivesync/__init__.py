"""pyactivesync: a Python client for Exchange ActiveSync (EAS / MS-ASCMD / MS-ASWBXML)."""
from __future__ import annotations

from .client import Client
from .exceptions import EASError, ProtocolError, ProvisionError, StatusError
from .models import (
    AttachmentInfo,
    BodyType,
    Folder,
    FolderType,
    GalEntry,
    PingResult,
    Recipient,
    SyncItem,
    SyncResult,
)

__version__ = "0.1.0"

__all__ = [
    "Client",
    "EASError",
    "ProtocolError",
    "ProvisionError",
    "StatusError",
    "AttachmentInfo",
    "BodyType",
    "Folder",
    "FolderType",
    "GalEntry",
    "PingResult",
    "Recipient",
    "SyncItem",
    "SyncResult",
    "__version__",
]
