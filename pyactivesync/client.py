"""EAS client: one method per MS-ASCMD command, WBXML in and out."""
from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable
from email.message import Message
from types import TracebackType

from ._http import Transport
from ._mime import to_crlf_bytes
from ._wbxml import Node, NodeBuilder, WBXMLReader, WBXMLWriter, find, find_all, leaves, text_of, wtag
from .exceptions import ProtocolError, ProvisionError, StatusError
from .models import (
    BodyType,
    FindItem,
    FindResult,
    Folder,
    FolderType,
    GalEntry,
    OofMessage,
    OofSettings,
    OofState,
    PingResult,
    Recipient,
    SyncItem,
    SyncResult,
)

_OOF_APPLIES_TO_TAGS = {
    "Internal": "AppliesToInternal",
    "ExternalKnown": "AppliesToExternalKnown",
    "ExternalUnknown": "AppliesToExternalUnknown",
}

_PROVISION_STATUS_MEANINGS = {"165": "DeviceInformationRequired"}
_SENDMAIL_STATUS_MEANINGS = {"101": "InvalidContent"}
_MOVEITEMS_STATUS_MEANINGS = {"1": "InvalidSourceId", "2": "InvalidDestinationId"}


def _check_status(command: str, status: str | None, meanings: dict[str, str] | None = None) -> None:
    if status is not None and status != "1":
        raise StatusError(command, status, (meanings or {}).get(status))


class Client:
    """A stateless-HTTP EAS client wrapping one connection to a single mailbox.

    ``username`` is passed to HTTP Basic auth as-is (NTLM-style
    ``domain\\user`` or a plain email, both work against Basic-auth EAS
    endpoints). ``user`` is the value sent as the ``User`` query parameter
    on every command (the mailbox's SMTP address) -- it defaults to
    ``username`` and only needs to be set separately when the login
    identity and the mailbox's primary SMTP address differ.
    """

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        *,
        device_id: str,
        user: str | None = None,
        device_type: str = "pyactivesync",
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.user = user or username
        self._transport = Transport(
            server,
            username,
            password,
            device_id=device_id,
            device_type=device_type,
            verify_ssl=verify_ssl,
            timeout=timeout,
        )
        self._provisioned = False

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def _post(
        self,
        cmd: str,
        wbxml: bytes,
        *,
        extra_params: dict[str, str] | None = None,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> bytes:
        return self._transport.post(
            cmd, self.user, wbxml, extra_params=extra_params, timeout=timeout, idempotent=idempotent
        )

    def _ensure_provisioned(self) -> None:
        if not self._provisioned:
            self.provision()

    # -- Device provisioning -------------------------------------------------

    def provision(self) -> str:
        """Acknowledge device policy (two round-trips). Returns the granted PolicyKey.

        A bare ``Provision`` request is rejected with ``Status=165``
        (``DeviceInformationRequired``) unless a ``Settings.DeviceInformation``
        block is included on the first request.
        """
        w = WBXMLWriter()
        w.tag(
            "Provision",
            "Provision",
            children=[
                wtag(
                    "Settings",
                    "DeviceInformation",
                    children=[
                        wtag(
                            "Settings",
                            "Set",
                            children=[
                                wtag("Settings", "Model", text="pyactivesync"),
                                wtag("Settings", "FriendlyName", text="pyactivesync client"),
                                wtag("Settings", "OS", text="Linux"),
                                wtag("Settings", "UserAgent", text="pyactivesync/0.1"),
                            ],
                        ),
                    ],
                ),
                wtag(
                    "Provision",
                    "Policies",
                    children=[
                        wtag(
                            "Provision",
                            "Policy",
                            children=[wtag("Provision", "PolicyType", text="MS-EAS-Provisioning-WBXML")],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("Provision", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Provision.Status"))
        _check_status("Provision", status, _PROVISION_STATUS_MEANINGS)
        temp_key = text_of(find(nodes, "Provision.PolicyKey"))
        if not temp_key:
            raise ProvisionError("Provision: no PolicyKey in response")

        w2 = WBXMLWriter()
        w2.tag(
            "Provision",
            "Provision",
            children=[
                wtag(
                    "Provision",
                    "Policies",
                    children=[
                        wtag(
                            "Provision",
                            "Policy",
                            children=[
                                wtag("Provision", "PolicyType", text="MS-EAS-Provisioning-WBXML"),
                                wtag("Provision", "PolicyKey", text=temp_key),
                                wtag("Provision", "Status", text="1"),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp2 = self._post("Provision", w2.render(), extra_params={"PolicyKey": temp_key})
        nodes2 = WBXMLReader(resp2).parse()
        final_key = text_of(find(nodes2, "Provision.PolicyKey"))
        key = final_key or temp_key
        self._transport.policy_key = key
        self._provisioned = True
        return key

    # -- Folders ---------------------------------------------------------------

    def list_folders(self) -> list[Folder]:
        """Full ``FolderSync`` hierarchy listing."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag("FolderHierarchy", "FolderSync", children=[wtag("FolderHierarchy", "SyncKey", text="0")])
        resp = self._post("FolderSync", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "FolderHierarchy.Status"))
        _check_status("FolderSync", status)
        folders = []
        for _, _, children in find_all(nodes, "FolderHierarchy.Add"):
            server_id = text_of(find(children, "FolderHierarchy.ServerId"))
            parent_id = text_of(find(children, "FolderHierarchy.ParentId"))
            type_ = text_of(find(children, "FolderHierarchy.Type"))
            name = text_of(find(children, "FolderHierarchy.DisplayName"))
            if server_id is None or parent_id is None or type_ is None or name is None:
                raise ProtocolError("FolderSync: incomplete Add entry in response")
            folders.append(Folder(id=server_id, parent_id=parent_id, type=FolderType(int(type_)), name=name))
        return folders

    def _folder_sync_key(self) -> str:
        """Bootstrap ``SyncKey`` for a mutating FolderHierarchy command."""
        w = WBXMLWriter()
        w.tag("FolderHierarchy", "FolderSync", children=[wtag("FolderHierarchy", "SyncKey", text="0")])
        resp = self._post("FolderSync", w.render(), idempotent=True)
        key = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.SyncKey"))
        if not key:
            raise ProtocolError("FolderSync: no SyncKey in response")
        return key

    def create_folder(
        self, display_name: str, parent_id: str = "0", type: FolderType = FolderType.USER_GENERIC
    ) -> Folder:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderCreate",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ParentId", text=parent_id),
                wtag("FolderHierarchy", "DisplayName", text=display_name),
                wtag("FolderHierarchy", "Type", text=str(int(type))),
            ],
        )
        resp = self._post("FolderCreate", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "FolderHierarchy.Status"))
        _check_status("FolderCreate", status)
        server_id = text_of(find(nodes, "FolderHierarchy.ServerId"))
        if not server_id:
            raise ProtocolError("FolderCreate: no ServerId in response")
        return Folder(id=server_id, parent_id=parent_id, type=type, name=display_name)

    def update_folder(self, folder_id: str, display_name: str, parent_id: str = "0") -> None:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderUpdate",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ServerId", text=folder_id),
                wtag("FolderHierarchy", "ParentId", text=parent_id),
                wtag("FolderHierarchy", "DisplayName", text=display_name),
            ],
        )
        resp = self._post("FolderUpdate", w.render())
        status = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.Status"))
        _check_status("FolderUpdate", status)

    def delete_folder(self, folder_id: str) -> None:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderDelete",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ServerId", text=folder_id),
            ],
        )
        resp = self._post("FolderDelete", w.render())
        status = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.Status"))
        _check_status("FolderDelete", status)

    # -- Sync ------------------------------------------------------------------

    def sync_folder(
        self,
        folder_id: str,
        sync_key: str = "0",
        *,
        window_size: int = 25,
        filter_type: str | None = None,
    ) -> SyncResult:
        """``Sync`` one collection. Pass ``sync_key="0"`` (the default) to bootstrap.

        A bootstrap request only returns a fresh ``SyncKey``, no items --
        call again with that key to fetch the actual ``Add``/``Change``/``Delete``
        entries, exactly as the protocol requires.
        """
        self._ensure_provisioned()
        options = [wtag("AirSync", "FilterType", text=filter_type)] if filter_type else []
        collection_children = [
            wtag("AirSync", "SyncKey", text=sync_key),
            wtag("AirSync", "CollectionId", text=folder_id),
            wtag("AirSync", "WindowSize", text=str(window_size)),
        ]
        if options:
            collection_children.append(wtag("AirSync", "Options", children=options))
        w = WBXMLWriter()
        w.tag(
            "AirSync",
            "Sync",
            children=[
                wtag(
                    "AirSync",
                    "Collections",
                    children=[wtag("AirSync", "Collection", children=collection_children)],
                ),
            ],
        )
        resp = self._post("Sync", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "AirSync.Status"))
        _check_status("Sync", status)
        new_sync_key = text_of(find(nodes, "AirSync.SyncKey")) or sync_key

        added = [self._sync_item(c) for _, _, c in find_all(nodes, "AirSync.Add")]
        changed = [self._sync_item(c) for _, _, c in find_all(nodes, "AirSync.Change")]
        deleted = [
            sid
            for _, _, c in find_all(nodes, "AirSync.Delete")
            if (sid := text_of(find(c, "AirSync.ServerId"))) is not None
        ]
        more_available = find(nodes, "AirSync.MoreAvailable") is not None
        return SyncResult(
            sync_key=new_sync_key, added=added, changed=changed, deleted=deleted, more_available=more_available
        )

    @staticmethod
    def _sync_item(children: list[Node]) -> SyncItem:
        server_id = text_of(find(children, "AirSync.ServerId")) or ""
        appdata = find(children, "AirSync.ApplicationData")
        return SyncItem(server_id=server_id, fields=leaves(appdata[2]) if appdata else {})

    def get_item_estimate(self, folder_id: str, sync_key: str) -> int:
        """``GetItemEstimate`` needs a real (non-zero) ``SyncKey`` -- bootstrap one via ``sync_folder`` first."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "ItemEstimate",
            "GetItemEstimate",
            children=[
                wtag(
                    "ItemEstimate",
                    "Collections",
                    children=[
                        wtag(
                            "ItemEstimate",
                            "Collection",
                            children=[
                                wtag("AirSync", "SyncKey", text=sync_key),
                                wtag("ItemEstimate", "CollectionId", text=folder_id),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("GetItemEstimate", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ItemEstimate.Status"))
        _check_status("GetItemEstimate", status)
        estimate = text_of(find(nodes, "ItemEstimate.Estimate"))
        if estimate is None:
            raise ProtocolError("GetItemEstimate: no Estimate in response")
        return int(estimate)

    # -- Items -------------------------------------------------------------------

    def fetch_item(self, folder_id: str, item_id: str, *, body_type: BodyType = BodyType.HTML) -> dict[str, str]:
        """``ItemOperations`` Fetch: full item properties. Does not mark the item read."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "ItemOperations",
            "ItemOperations",
            children=[
                wtag(
                    "ItemOperations",
                    "Fetch",
                    children=[
                        wtag("ItemOperations", "Store", text="Mailbox"),
                        wtag("AirSync", "CollectionId", text=folder_id),
                        wtag("AirSync", "ServerId", text=item_id),
                        wtag(
                            "ItemOperations",
                            "Options",
                            children=[
                                wtag(
                                    "AirSyncBase",
                                    "BodyPreference",
                                    children=[wtag("AirSyncBase", "Type", text=str(int(body_type)))],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("ItemOperations", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ItemOperations.Status"))
        _check_status("ItemOperations", status)
        props = find(nodes, "ItemOperations.Properties")
        return leaves(props[2]) if props else {}

    def fetch_attachment(self, file_reference: str) -> bytes:
        """``ItemOperations`` Fetch by ``FileReference``. Returns decoded attachment bytes."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "ItemOperations",
            "ItemOperations",
            children=[
                wtag(
                    "ItemOperations",
                    "Fetch",
                    children=[
                        wtag("ItemOperations", "Store", text="Mailbox"),
                        wtag("AirSyncBase", "FileReference", text=file_reference),
                    ],
                ),
            ],
        )
        resp = self._post("ItemOperations", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ItemOperations.Status"))
        _check_status("ItemOperations", status)
        b64 = text_of(find(nodes, "ItemOperations.Data"))
        return base64.b64decode(b64) if b64 else b""

    def move_item(self, item_id: str, src_folder_id: str, dst_folder_id: str) -> str:
        """``MoveItems``. Returns the new (destination) ``ServerId``."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Move",
            "MoveItems",
            children=[
                wtag(
                    "Move",
                    "Move",
                    children=[
                        wtag("Move", "SrcMsgId", text=item_id),
                        wtag("Move", "SrcFldId", text=src_folder_id),
                        wtag("Move", "DstFldId", text=dst_folder_id),
                    ],
                ),
            ],
        )
        resp = self._post("MoveItems", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Move.Status"))
        if status is not None and status != "3":
            raise StatusError("MoveItems", status, _MOVEITEMS_STATUS_MEANINGS.get(status))
        new_id = text_of(find(nodes, "Move.DstMsgId"))
        if not new_id:
            raise ProtocolError("MoveItems: no DstMsgId in response")
        return new_id

    # -- Mail --------------------------------------------------------------------

    def send_mail(self, message: Message, *, save_in_sent_items: bool = True) -> None:
        """``SendMail``: WBXML ``ComposeMail`` wrapper, MIME embedded as opaque data.

        Protocol v16.1 requires the
        ``ComposeMail`` WBXML wrapper -- unlike v12.0/12.1, a raw
        ``message/rfc822`` POST body is rejected.
        """
        self._ensure_provisioned()
        mime_bytes = to_crlf_bytes(message)
        children = [wtag("ComposeMail", "ClientId", text=uuid.uuid4().hex)]
        if save_in_sent_items:
            children.append(wtag("ComposeMail", "SaveInSentItems"))
        children.append(wtag("ComposeMail", "MIME", opaque=mime_bytes))
        w = WBXMLWriter()
        w.tag("ComposeMail", "SendMail", children=children)
        resp = self._post("SendMail", w.render())
        if resp:
            status = text_of(find(WBXMLReader(resp).parse(), "ComposeMail.Status"))
            _check_status("SendMail", status, _SENDMAIL_STATUS_MEANINGS)

    # -- Device / connectivity ----------------------------------------------------

    def ping(
        self, folder_id: str, *, folder_class: str = "Email", heartbeat: int = 60, timeout: float | None = None
    ) -> PingResult:
        """``Ping``: long-poll for changes on one folder.

        ``timeout`` bounds the client-side wait; it is independent of
        ``heartbeat`` (the server-side long-poll duration requested).
        """
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Ping",
            "Ping",
            children=[
                wtag("Ping", "HeartbeatInterval", text=str(heartbeat)),
                wtag(
                    "Ping",
                    "Folders",
                    children=[
                        wtag(
                            "Ping",
                            "Folder",
                            children=[
                                wtag("Ping", "Id", text=folder_id),
                                wtag("Ping", "Class", text=folder_class),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("Ping", w.render(), timeout=timeout, idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Ping.Status")) or ""
        changed = [
            sid for _, _, c in find_all(nodes, "Ping.Folder") if (sid := text_of(find(c, "Ping.Id"))) is not None
        ]
        return PingResult(status=status, changed_folder_ids=changed)

    # -- Directory / search --------------------------------------------------------

    def resolve_recipients(self, address: str) -> list[Recipient]:
        """Resolve one address against contacts/GAL."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag("ResolveRecipients", "ResolveRecipients", children=[wtag("ResolveRecipients", "To", text=address)])
        resp = self._post("ResolveRecipients", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ResolveRecipients.Status"))
        _check_status("ResolveRecipients", status)
        recipients = []
        for _, _, children in find_all(nodes, "ResolveRecipients.Recipient"):
            data = leaves(children)
            recipients.append(
                Recipient(
                    type=data.get("ResolveRecipients.Type"),
                    display_name=data.get("ResolveRecipients.DisplayName"),
                    email_address=data.get("ResolveRecipients.EmailAddress"),
                )
            )
        return recipients

    def search_gal(self, query: str, *, max_results: int = 10) -> list[GalEntry]:
        """GAL (directory) search."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Search",
            "Search",
            children=[
                wtag(
                    "Search",
                    "Store",
                    children=[
                        wtag("Search", "Name", text="GAL"),
                        wtag("Search", "Query", text=query),
                        wtag("Search", "Options", children=[wtag("Search", "Range", text=f"0-{max_results - 1}")]),
                    ],
                ),
            ],
        )
        resp = self._post("Search", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Search.Status"))
        _check_status("Search", status)
        entries = []
        for _, _, children in find_all(nodes, "Search.Result"):
            data = leaves(children)
            entries.append(
                GalEntry(
                    display_name=data.get("GAL.DisplayName"),
                    email_address=data.get("GAL.EmailAddress"),
                    phone=data.get("GAL.Phone"),
                    office=data.get("GAL.Office"),
                    title=data.get("GAL.Title"),
                    company=data.get("GAL.Company"),
                    alias=data.get("GAL.Alias"),
                    first_name=data.get("GAL.FirstName"),
                    last_name=data.get("GAL.LastName"),
                    home_phone=data.get("GAL.HomePhone"),
                    mobile_phone=data.get("GAL.MobilePhone"),
                )
            )
        return entries

    def search_mailbox(
        self,
        folder_id: str,
        *,
        date_received_after: str,
        item_class: str = "Email",
        max_results: int = 10,
    ) -> list[dict[str, str]]:
        """Structured mailbox search: items of ``item_class`` in ``folder_id``
        received after ``date_received_after`` (an ``AirSyncBase``-style UTC
        timestamp, e.g. ``"2020-01-01T00:00:00.000Z"``).

        There is deliberately no ``free_text=`` parameter: full-text search
        conditions in ``Search`` are known to fail against real servers
        with ``Store.Status=110`` (a server-side bug, not a WBXML encoding
        issue -- confirmed by cross-checking the same mailbox's content
        index through an unrelated protocol). Shipping that parameter would
        just reproduce the failure for every caller; only the structured
        condition below is exposed.
        """
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Search",
            "Search",
            children=[
                wtag(
                    "Search",
                    "Store",
                    children=[
                        wtag("Search", "Name", text="Mailbox"),
                        wtag(
                            "Search",
                            "Query",
                            children=[
                                wtag(
                                    "Search",
                                    "And",
                                    children=[
                                        wtag("AirSync", "Class", text=item_class),
                                        wtag("AirSync", "CollectionId", text=folder_id),
                                        wtag(
                                            "Search",
                                            "GreaterThan",
                                            children=[
                                                wtag("Email", "DateReceived"),
                                                wtag("Search", "Value", text=date_received_after),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        wtag("Search", "Options", children=[wtag("Search", "Range", text=f"0-{max_results - 1}")]),
                    ],
                ),
            ],
        )
        resp = self._post("Search", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Search.Status"))
        _check_status("Search", status)
        return [leaves(children) for _, _, children in find_all(nodes, "Search.Result")]

    def find_mailbox(
        self,
        query: str,
        *,
        folder_id: str | None = None,
        item_class: str = "Email",
        range_start: int = 0,
        max_results: int = 10,
        deep_traversal: bool = False,
        search_id: str | None = None,
    ) -> FindResult:
        """Free-text mailbox search using the EAS 16.1 ``Find`` command.

        Pass the returned ``search_id`` back with a later ``range_start`` to
        request another page of the same search. If ``folder_id`` is omitted,
        Exchange searches all folders; ``deep_traversal`` requests recursive
        traversal where the server supports it.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        query_children = [
            wtag("Find", "FreeText", text=query),
            wtag("AirSync", "Class", text=item_class),
        ]
        if folder_id is not None:
            query_children.append(wtag("AirSync", "CollectionId", text=folder_id))
        return self._find(
            "MailBoxSearchCriterion",
            wtag("Find", "Query", children=query_children),
            range_start=range_start,
            max_results=max_results,
            deep_traversal=deep_traversal,
            search_id=search_id,
        )

    def find_gal(
        self,
        query: str,
        *,
        range_start: int = 0,
        max_results: int = 10,
        search_id: str | None = None,
    ) -> FindResult:
        """Search the Global Address List using the EAS 16.1 ``Find`` command."""
        if not 4 <= len(query) <= 256:
            raise ValueError("GAL Find query must contain 4 to 256 characters")
        return self._find(
            "GALSearchCriterion",
            wtag("Find", "Query", text=query),
            range_start=range_start,
            max_results=max_results,
            search_id=search_id,
        )

    def _find(
        self,
        criterion_name: str,
        query: NodeBuilder,
        *,
        range_start: int,
        max_results: int,
        deep_traversal: bool = False,
        search_id: str | None,
    ) -> FindResult:
        if range_start < 0:
            raise ValueError("range_start must be non-negative")
        if not 1 <= max_results <= 1000 or range_start + max_results > 1000:
            raise ValueError("requested range must be within 0-999")
        if search_id is None:
            search_id = str(uuid.uuid4())
        else:
            try:
                search_id = str(uuid.UUID(search_id))
            except ValueError as exc:
                raise ValueError("search_id must be a UUID") from exc

        options = [wtag("Find", "Range", text=f"{range_start}-{range_start + max_results - 1}")]
        if deep_traversal:
            options.append(wtag("Find", "DeepTraversal"))
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Find",
            "Find",
            children=[
                wtag("Find", "SearchId", text=search_id),
                wtag(
                    "Find",
                    "ExecuteSearch",
                    children=[
                        wtag(
                            "Find",
                            criterion_name,
                            children=[query, wtag("Find", "Options", children=options)],
                        )
                    ],
                ),
            ],
        )
        resp = self._post("Find", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Find.Status")) or "1"
        _check_status("Find", status)
        response = find(nodes, "Find.Response")
        if response is None:
            return FindResult(search_id=search_id, status=status)
        response_status = text_of(find(response[2], "Find.Status")) or "1"
        _check_status("Find", response_status)
        items = []
        for _, _, children in find_all(response[2], "Find.Result"):
            properties = find(children, "Find.Properties")
            items.append(
                FindItem(
                    server_id=text_of(find(children, "AirSync.ServerId")),
                    collection_id=text_of(find(children, "AirSync.CollectionId")),
                    fields=leaves(properties[2]) if properties is not None else {},
                )
            )
        return FindResult(
            search_id=search_id,
            status=response_status,
            range=text_of(find(response[2], "Find.Range")),
            # Find:Total describes available entries, not necessarily entries
            # returned, and real Exchange servers can even send Total=0 with a
            # non-empty page. Report the actual decoded Result count instead.
            total=len(items),
            items=items,
        )

    # -- Settings ------------------------------------------------------------------

    def get_oof(self) -> OofSettings:
        """``Settings`` Oof Get: current Out-of-Office autoreply configuration.

        Request shape verified against a real Exchange server; the response
        parsing below follows the MS-ASCMD schema but hasn't itself been
        cross-checked against a live response.
        """
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Settings",
            "Settings",
            children=[
                wtag(
                    "Settings",
                    "Oof",
                    children=[wtag("Settings", "Get", children=[wtag("Settings", "BodyType", text="Text")])],
                ),
            ],
        )
        resp = self._post("Settings", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        _check_status("Settings", text_of(find(nodes, "Settings.Status")))
        oof = find(nodes, "Settings.Oof")
        if oof is None:
            raise ProtocolError("Settings: no Oof in Get response")
        _check_status("Settings.Oof", text_of(find(oof[2], "Settings.Status")))
        get = find(oof[2], "Settings.Get")
        if get is None:
            raise ProtocolError("Settings: no Oof.Get in response")
        state = text_of(find(get[2], "Settings.OofState"))
        messages = [self._oof_message(children) for _, _, children in find_all(get[2], "Settings.OofMessage")]
        return OofSettings(
            state=OofState(int(state)) if state is not None else OofState.DISABLED,
            start_time=text_of(find(get[2], "Settings.StartTime")),
            end_time=text_of(find(get[2], "Settings.EndTime")),
            messages=messages,
        )

    @staticmethod
    def _oof_message(children: list[Node]) -> OofMessage:
        applies_to = next(
            (scope for scope, tag in _OOF_APPLIES_TO_TAGS.items() if find(children, f"Settings.{tag}") is not None),
            "",
        )
        return OofMessage(
            applies_to=applies_to,
            enabled=text_of(find(children, "Settings.Enabled")) == "1",
            reply_message=text_of(find(children, "Settings.ReplyMessage")),
            body_type=text_of(find(children, "Settings.BodyType")),
        )

    def set_oof(
        self,
        state: OofState,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        reply_message: str | None = None,
        body_type: str = "Text",
        applies_to: Iterable[str] = ("Internal", "ExternalKnown", "ExternalUnknown"),
    ) -> None:
        """``Settings`` Oof Set: enable/disable/schedule the Out-of-Office autoreply.

        ``start_time``/``end_time`` only apply with ``state=OofState.ENABLED_SCHEDULED``.
        If ``reply_message`` is given, it's sent identically as one
        ``OofMessage`` block per scope in ``applies_to`` -- EAS has no
        single "same message everywhere" shortcut. Unverified against a
        live server; see ``get_oof()``.
        """
        self._ensure_provisioned()
        set_children = [wtag("Settings", "OofState", text=str(int(state)))]
        if state == OofState.ENABLED_SCHEDULED:
            if start_time:
                set_children.append(wtag("Settings", "StartTime", text=start_time))
            if end_time:
                set_children.append(wtag("Settings", "EndTime", text=end_time))
        if reply_message is not None:
            for scope in applies_to:
                set_children.append(
                    wtag(
                        "Settings",
                        "OofMessage",
                        children=[
                            wtag("Settings", _OOF_APPLIES_TO_TAGS[scope]),
                            wtag("Settings", "Enabled", text="1"),
                            wtag("Settings", "ReplyMessage", text=reply_message),
                            wtag("Settings", "BodyType", text=body_type),
                        ],
                    ),
                )
        w = WBXMLWriter()
        w.tag(
            "Settings",
            "Settings",
            children=[wtag("Settings", "Oof", children=[wtag("Settings", "Set", children=set_children)])],
        )
        resp = self._post("Settings", w.render())
        nodes = WBXMLReader(resp).parse()
        _check_status("Settings", text_of(find(nodes, "Settings.Status")))
        oof = find(nodes, "Settings.Oof")
        if oof is not None:
            _check_status("Settings.Oof", text_of(find(oof[2], "Settings.Status")))
