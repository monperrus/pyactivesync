from __future__ import annotations

from email.message import EmailMessage
from typing import cast
from unittest.mock import patch

import pytest

from pyactivesync import Client
from pyactivesync._wbxml import Node, WBXMLReader, WBXMLWriter, find, text_of, wtag
from pyactivesync.exceptions import ProtocolError, StatusError


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="AddTest")
    client._provisioned = True
    return client


def _child(node: Node, name: str) -> Node:
    match = next((child for child in node[2] if child[0] == name), None)
    assert match is not None, f"missing direct child {name} of {node[0]}"
    return cast(Node, match)


def _response(*, item_status: str = "1", server_id: str | None = "4:1") -> bytes:
    add_children = [
        wtag("AirSync", "ClientId", text="local-1"),
        wtag("AirSync", "Status", text=item_status),
    ]
    if server_id is not None:
        add_children.insert(1, wtag("AirSync", "ServerId", text=server_id))
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "Sync",
        children=[
            wtag(
                "AirSync",
                "Collections",
                children=[
                    wtag(
                        "AirSync",
                        "Collection",
                        children=[
                            wtag("AirSync", "SyncKey", text="2"),
                            wtag("AirSync", "CollectionId", text="4"),
                            wtag("AirSync", "Status", text="1"),
                            wtag(
                                "AirSync",
                                "Responses",
                                children=[wtag("AirSync", "Add", children=add_children)],
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    return w.render()


def _message() -> EmailMessage:
    message = EmailMessage()
    message["To"] = "recipient@example.com"
    message["Subject"] = "héllo draft"
    message.set_content("draft bödy")
    message.add_attachment(b"attachment bytes", maintype="application", subtype="octet-stream", filename="a.bin")
    return message


def test_create_email_draft_builds_mime_add_and_parses_result() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response()) as post:
        result = client.create_email_draft(
            "4", "1", _message(), read=True, flagged=True, client_id="local-1"
        )

    assert post.call_args.args[0] == "Sync"
    assert post.call_args.kwargs == {}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "AirSync.Sync")
    assert root is not None
    collection = _child(_child(root, "AirSync.Collections"), "AirSync.Collection")
    assert text_of(_child(collection, "AirSync.SyncKey")) == "1"
    assert text_of(_child(collection, "AirSync.CollectionId")) == "4"
    assert text_of(_child(collection, "AirSync.GetChanges")) == "0"
    add = _child(_child(collection, "AirSync.Commands"), "AirSync.Add")
    assert text_of(_child(add, "AirSync.ClientId")) == "local-1"
    appdata = _child(add, "AirSync.ApplicationData")
    body = _child(appdata, "AirSyncBase.Body")
    assert text_of(_child(body, "AirSyncBase.Type")) == "4"
    mime = text_of(_child(body, "AirSyncBase.Data"))
    assert mime is not None
    assert "Subject: =?utf-8?" in mime
    assert "attachment bytes" not in mime
    assert "YXR0YWNobWVudCBieXRlcw==" in mime
    assert "\r\n" in mime
    assert text_of(_child(appdata, "Email.Read")) == "1"
    flag = _child(appdata, "Email.Flag")
    assert text_of(_child(flag, "Email.Status")) == "2"
    assert text_of(_child(flag, "Email.FlagType")) == "Flag for follow up"

    assert result.sync_key == "2"
    assert result.client_id == "local-1"
    assert result.status == "1"
    assert result.server_id == "4:1"


def test_create_email_draft_returns_item_failure_status() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response(item_status="6", server_id=None)):
        result = client.create_email_draft("4", "1", _message(), client_id="local-1")

    assert result.sync_key == "2"
    assert result.status == "6"
    assert result.server_id is None


@pytest.mark.parametrize(
    ("folder_id", "sync_key", "client_id", "message"),
    [
        ("", "1", "local-1", "folder_id"),
        ("4", "0", "local-1", "sync_key"),
        ("4", "1", "", "client_id"),
    ],
)
def test_create_email_draft_validates_input(
    folder_id: str, sync_key: str, client_id: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _client().create_email_draft(folder_id, sync_key, _message(), client_id=client_id)


def test_create_email_draft_rejects_non_message() -> None:
    with pytest.raises(TypeError, match="email.message.Message"):
        _client().create_email_draft("4", "1", cast(EmailMessage, object()))


def test_create_email_draft_raises_collection_status_error() -> None:
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "Sync",
        children=[
            wtag(
                "AirSync",
                "Collections",
                children=[
                    wtag(
                        "AirSync",
                        "Collection",
                        children=[wtag("AirSync", "Status", text="3")],
                    )
                ],
            )
        ],
    )
    client = _client()
    with patch.object(client, "_post", return_value=w.render()), pytest.raises(StatusError) as exc:
        client.create_email_draft("4", "1", _message(), client_id="local-1")
    assert "Status=3" in str(exc.value)


def test_create_email_draft_requires_correlated_item_response() -> None:
    response = _response().replace(b"local-1", b"other--")
    client = _client()
    with patch.object(client, "_post", return_value=response), pytest.raises(ProtocolError, match="ClientId"):
        client.create_email_draft("4", "1", _message(), client_id="local-1")
