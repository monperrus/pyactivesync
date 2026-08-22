from __future__ import annotations

from unittest.mock import patch

import pytest

from pyactivesync import BodyType, Client, FetchedItem
from pyactivesync._wbxml import NodeBuilder, WBXMLReader, WBXMLWriter, find, text_of, wtag
from pyactivesync.exceptions import ProtocolError, StatusError


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="FetchTest")
    client._provisioned = True
    return client


def _response(*, fetch_status: str = "1", properties: list[NodeBuilder] | None = None) -> bytes:
    fetch_children = [wtag("ItemOperations", "Status", text=fetch_status)]
    if properties is not None:
        fetch_children.append(wtag("ItemOperations", "Properties", children=properties))
    w = WBXMLWriter()
    w.tag(
        "ItemOperations",
        "ItemOperations",
        children=[
            wtag("ItemOperations", "Status", text="1"),
            wtag(
                "ItemOperations",
                "Response",
                children=[wtag("ItemOperations", "Fetch", children=fetch_children)],
            ),
        ],
    )
    return w.render()


def _properties() -> list[NodeBuilder]:
    return [
        wtag("Email", "Subject", text="two attachments"),
        wtag("Email", "Read", text="0"),
        wtag(
            "AirSyncBase",
            "Body",
            children=[
                wtag("AirSyncBase", "Type", text="4"),
                wtag("AirSyncBase", "EstimatedDataSize", text="42"),
                wtag("AirSyncBase", "Truncated", text="0"),
                wtag("AirSyncBase", "Data", text="Subject: fetched\r\n\r\nbody\r\n"),
                wtag("ItemOperations", "Part", text="7"),
                wtag("AirSyncBase", "Preview", text="body"),
            ],
        ),
        wtag(
            "AirSyncBase",
            "Body",
            children=[
                wtag("AirSyncBase", "Type", text="2"),
                wtag("AirSyncBase", "Data", opaque=b"<p>opaque html</p>"),
            ],
        ),
        wtag(
            "AirSyncBase",
            "Attachments",
            children=[
                wtag(
                    "AirSyncBase",
                    "Attachment",
                    children=[
                        wtag("AirSyncBase", "DisplayName", text="one.txt"),
                        wtag("AirSyncBase", "FileReference", text="ref-1"),
                        wtag("AirSyncBase", "Method", text="1"),
                        wtag("AirSyncBase", "EstimatedDataSize", text="10"),
                        wtag("AirSyncBase", "ContentId", text="cid-1"),
                        wtag("AirSyncBase", "ContentLocation", text="one.txt"),
                        wtag("AirSyncBase", "IsInline"),
                        wtag("AirSyncBase", "ContentType", text="text/plain"),
                    ],
                ),
                wtag(
                    "AirSyncBase",
                    "Attachment",
                    children=[
                        wtag("AirSyncBase", "DisplayName", text="two.bin"),
                        wtag("AirSyncBase", "FileReference", text="ref-2"),
                        wtag("AirSyncBase", "Method", text="1"),
                        wtag("AirSyncBase", "EstimatedDataSize", text="20"),
                    ],
                ),
            ],
        ),
        wtag("AirSyncBase", "NativeBodyType", text="2"),
        wtag("AirSyncBase", "ContentType", text="message/rfc822"),
    ]


def test_fetch_item_preserves_repeated_bodies_and_attachments() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response(properties=_properties())) as post:
        item = client.fetch_item("9", "9:1", body_type=BodyType.MIME)

    nodes = WBXMLReader(post.call_args.args[1]).parse()
    options = find(nodes, "ItemOperations.Options")
    assert options is not None
    assert text_of(find(options[2], "AirSyncBase.Type")) == "4"
    assert text_of(find(options[2], "AirSync.MIMESupport")) == "2"
    assert post.call_args.kwargs == {"idempotent": True}

    assert item.fields == {"Email.Subject": "two attachments", "Email.Read": "0"}
    assert item.native_body_type == BodyType.HTML
    assert item.content_type == "message/rfc822"
    assert len(item.bodies) == 2
    assert item.body == item.bodies[0]
    assert item.bodies[0].type == BodyType.MIME
    assert item.bodies[0].data == b"Subject: fetched\r\n\r\nbody\r\n"
    assert item.bodies[0].estimated_data_size == 42
    assert item.bodies[0].truncated is False
    assert item.bodies[0].part == "7"
    assert item.bodies[0].preview == "body"
    assert item.bodies[1].type == BodyType.HTML
    assert item.bodies[1].data == b"<p>opaque html</p>"

    assert [attachment.file_reference for attachment in item.attachments] == ["ref-1", "ref-2"]
    first = item.attachments[0]
    assert first.display_name == "one.txt"
    assert first.method == 1
    assert first.estimated_data_size == 10
    assert first.content_id == "cid-1"
    assert first.content_location == "one.txt"
    assert first.content_type == "text/plain"
    assert first.is_inline
    assert not item.attachments[1].is_inline


def test_fetch_item_without_properties_returns_empty_typed_result() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response()):
        assert client.fetch_item("9", "missing") == FetchedItem()


def test_fetch_item_checks_per_fetch_status() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response(fetch_status="6")), pytest.raises(StatusError) as exc:
        client.fetch_item("9", "missing")
    assert "Status=6" in str(exc.value)


def test_fetch_item_rejects_attachment_without_file_reference() -> None:
    properties = [
        wtag(
            "AirSyncBase",
            "Attachments",
            children=[wtag("AirSyncBase", "Attachment", children=[wtag("AirSyncBase", "DisplayName", text="bad")])],
        )
    ]
    client = _client()
    with patch.object(client, "_post", return_value=_response(properties=properties)), pytest.raises(
        ProtocolError, match="FileReference"
    ):
        client.fetch_item("9", "9:1")
