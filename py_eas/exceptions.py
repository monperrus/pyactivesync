"""Exception hierarchy for py-eas."""
from __future__ import annotations


class EASError(Exception):
    """Base class for all py-eas errors."""


class ProtocolError(EASError):
    """The server response did not match the expected MS-ASCMD/MS-ASWBXML shape."""


class StatusError(ProtocolError):
    """An EAS command returned a non-success ``Status`` code.

    ``code`` is the raw status string from the response (e.g. ``"110"``);
    ``meaning`` is a short human-readable label where known, else ``None``.
    """

    def __init__(self, command: str, code: str, meaning: str | None = None) -> None:
        self.command = command
        self.code = code
        self.meaning = meaning
        suffix = f" ({meaning})" if meaning else ""
        super().__init__(f"{command}: Status={code}{suffix}")


class ProvisionError(EASError):
    """Device provisioning failed (policy not acknowledged, no PolicyKey granted, ...)."""
