from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from pyactivesync import Client
from pyactivesync._wbxml import Node, WBXMLReader, WBXMLWriter, find, find_all, text_of, wtag


def _client(*, provisioned: bool = True) -> Client:
    client = Client("example.invalid", "user", "password", device_id="PingTest")
    client._provisioned = provisioned
    return client


def _child(node: Node, name: str) -> Node:
    match = next((child for child in node[2] if child[0] == name), None)
    assert match is not None, f"missing direct child {name} of {node[0]}"
    return cast(Node, match)


def _response(*changed_folder_ids: str) -> bytes:
    w = WBXMLWriter()
    children = [wtag("Ping", "Status", text="2")]
    if changed_folder_ids:
        children.append(
            wtag(
                "Ping",
                "Folders",
                children=[wtag("Ping", "Folder", text=folder_id) for folder_id in changed_folder_ids],
            )
        )
    w.tag("Ping", "Ping", children=children)
    return w.render()


def test_ping_sends_all_folders_and_returns_all_changed_folder_ids() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response("9", "12")) as post:
        result = client.ping(["9", "12", "15"], heartbeat=120, timeout=125)

    assert post.call_args.args[0] == "Ping"
    assert post.call_args.kwargs == {"timeout": 125, "idempotent": True}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "Ping.Ping")
    assert root is not None
    assert text_of(_child(root, "Ping.HeartbeatInterval")) == "120"
    folders = find_all(_child(root, "Ping.Folders")[2], "Ping.Folder")
    assert [text_of(_child(folder, "Ping.Id")) for folder in folders] == ["9", "12", "15"]
    assert [text_of(_child(folder, "Ping.Class")) for folder in folders] == ["Email", "Email", "Email"]
    assert result.status == "2"
    assert result.changed_folder_ids == ["9", "12"]


def test_ping_preserves_single_folder_positional_and_keyword_calls() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response()) as post:
        positional = client.ping("9")
        keyword = client.ping(folder_id="12")

    assert post.call_count == 2
    assert positional.changed_folder_ids == []
    assert keyword.changed_folder_ids == []


@pytest.mark.parametrize("folder_ids", [[], [""], ["9", ""], ["9", 12]])
def test_ping_rejects_invalid_folder_sets_before_provisioning_or_http(folder_ids: list[object]) -> None:
    client = _client(provisioned=False)
    with (
        patch.object(client, "_ensure_provisioned") as provision,
        patch.object(client, "_post") as post,
        pytest.raises(ValueError),
    ):
        client.ping(folder_ids)  # type: ignore[arg-type]
    provision.assert_not_called()
    post.assert_not_called()


def test_ping_rejects_both_folder_argument_forms() -> None:
    client = _client(provisioned=False)
    with pytest.raises(TypeError, match="not both"):
        client.ping(["9"], folder_id="12")  # type: ignore[call-overload]
