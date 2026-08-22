"""MIME helpers: turn a stdlib ``email.message`` object into the CRLF bytes
EAS's ``ComposeMail.MIME`` opaque field requires, and parse MIME bytes back.
"""
from __future__ import annotations

from email import message_from_bytes, policy
from email.message import Message


def to_crlf_bytes(message: Message) -> bytes:
    """Render an ``email.message`` object to CRLF-terminated bytes.

    EAS requires CRLF line endings in the MIME payload; LF-only bytes (the
    default from ``Message.as_bytes()`` on POSIX) are rejected by the
    server with ``Status=101`` (``InvalidContent``).
    """
    raw = message.as_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def to_7bit_crlf_text(message: Message) -> str:
    """Render a message as MIME suitable for ``AirSyncBase:Body/Data``.

    Unlike ``ComposeMail:MIME``, ``Body:Data`` is a WBXML string rather than
    opaque data.  A 7-bit transfer encoding keeps arbitrary message bodies and
    attachments representable as valid UTF-8 WBXML without losing MIME
    semantics.
    """
    raw = message.as_bytes(policy=policy.SMTP.clone(cte_type="7bit"))
    return raw.decode("ascii")


def parse_mime(data: bytes) -> Message:
    return message_from_bytes(data)
