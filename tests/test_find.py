from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from pyactivesync import Client
from pyactivesync._wbxml import Node, WBXMLReader, WBXMLWriter, find, text_of, wtag

SEARCH_ID = "01234567-89ab-cdef-0123-456789abcdef"


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="FindTest")
    client._provisioned = True
    return client


def _child(node: Node, name: str) -> Node:
    match = next((child for child in node[2] if child[0] == name), None)
    assert match is not None, f"missing direct child {name} of {node[0]}"
    return cast(Node, match)


def _mailbox_response() -> bytes:
    w = WBXMLWriter()
    w.tag(
        "Find",
        "Find",
        children=[
            wtag("Find", "Status", text="1"),
            wtag(
                "Find",
                "Response",
                children=[
                    wtag("Find", "Status", text="1"),
                    wtag(
                        "Find",
                        "Result",
                        children=[
                            wtag("AirSync", "CollectionId", text="9"),
                            wtag("AirSync", "ServerId", text="9:1"),
                            wtag(
                                "Find",
                                "Properties",
                                children=[
                                    wtag("Email", "Subject", text="needle found"),
                                    wtag("Find", "Preview", text="matching body"),
                                    wtag("Find", "HasAttachments", text="1"),
                                ],
                            ),
                        ],
                    ),
                    wtag("Find", "Range", text="5-5"),
                    wtag("Find", "Total", text="8"),
                ],
            ),
        ],
    )
    return w.render()


def test_find_mailbox_uses_correct_eas_16_1_hierarchy_and_parses_result() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_mailbox_response()) as post:
        result = client.find_mailbox(
            "needle",
            folder_id="9",
            range_start=5,
            max_results=5,
            deep_traversal=True,
            search_id=SEARCH_ID,
        )

    assert post.call_args.args[0] == "Find"
    assert post.call_args.kwargs == {"idempotent": True}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "Find.Find")
    assert root is not None
    assert text_of(_child(root, "Find.SearchId")) == SEARCH_ID
    execute = _child(root, "Find.ExecuteSearch")
    criterion = _child(execute, "Find.MailBoxSearchCriterion")
    query = _child(criterion, "Find.Query")
    assert text_of(_child(query, "Find.FreeText")) == "needle"
    assert text_of(_child(query, "AirSync.Class")) == "Email"
    assert text_of(_child(query, "AirSync.CollectionId")) == "9"
    options = _child(criterion, "Find.Options")
    assert text_of(_child(options, "Find.Range")) == "5-9"
    _child(options, "Find.DeepTraversal")

    assert result.search_id == SEARCH_ID
    assert result.status == "1"
    assert result.range == "5-5"
    assert result.total == 8
    assert len(result.items) == 1
    assert result.items[0].server_id == "9:1"
    assert result.items[0].collection_id == "9"
    assert result.items[0].fields == {
        "Email.Subject": "needle found",
        "Find.Preview": "matching body",
        "Find.HasAttachments": "1",
    }


def test_find_gal_uses_gal_criterion_and_generates_search_id() -> None:
    w = WBXMLWriter()
    w.tag(
        "Find",
        "Find",
        children=[
            wtag("Find", "Status", text="1"),
            wtag(
                "Find",
                "Response",
                children=[
                    wtag("Find", "Status", text="1"),
                    wtag(
                        "Find",
                        "Result",
                        children=[
                            wtag(
                                "Find",
                                "Properties",
                                children=[wtag("GAL", "DisplayName", text="Martin Example")],
                            )
                        ],
                    ),
                    wtag("Find", "Range", text="0-0"),
                    wtag("Find", "Total", text="1"),
                ],
            ),
        ],
    )
    client = _client()
    with patch.object(client, "_post", return_value=w.render()) as post:
        result = client.find_gal("Mart")

    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "Find.Find")
    assert root is not None
    criterion = _child(_child(root, "Find.ExecuteSearch"), "Find.GALSearchCriterion")
    assert text_of(_child(criterion, "Find.Query")) == "Mart"
    assert text_of(_child(_child(criterion, "Find.Options"), "Find.Range")) == "0-9"
    assert result.total == 1
    assert result.items[0].fields["GAL.DisplayName"] == "Martin Example"
    assert result.search_id == text_of(_child(root, "Find.SearchId"))


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("find_mailbox", {"query": " "}),
        ("find_mailbox", {"query": "x", "range_start": -1}),
        ("find_mailbox", {"query": "x", "range_start": 999, "max_results": 2}),
        ("find_mailbox", {"query": "x", "search_id": "not-a-uuid"}),
        ("find_gal", {"query": "abc"}),
    ],
)
def test_find_validates_arguments(method: str, kwargs: dict[str, object]) -> None:
    client = _client()
    with pytest.raises(ValueError):
        getattr(client, method)(**kwargs)
