"""WBXML codec tests: structural round-trips plus one golden-byte fixture
captured from a real, verified-successful request against a live Exchange
server (a mailbox-scope structured ``Search`` that returned ``Status=1``,
``Total=96``)."""
from __future__ import annotations

from py_eas._wbxml import (
    STR_I,
    SWITCH_PAGE,
    WBXMLReader,
    WBXMLWriter,
    _mb_uint_bytes,
    find,
    leaves,
    opaque_of,
    text_of,
    wtag,
)

# Captured verbatim from a live server: mailbox Search for Class=Email,
# CollectionId=9, GreaterThan(Email.DateReceived, "2020-01-01T00:00:00.000Z"),
# Options/Range=0-9. This exact request returned Store.Status=1, Total=96.
GOLDEN_SEARCH_REQUEST_HEX = (
    "03016a00000f454748034d61696c626f780001495300005003456d61696c00015203390001"
    "000f5b00020f000f5203323032302d30312d30315430303a30303a30302e3030305a000101"
    "01014a4b03302d390001010101"
)


def test_header_is_three_bytes_plus_string_table_length():
    w = WBXMLWriter()
    w.tag("Provision", "Provision")
    rendered = w.render()
    assert rendered[:3] == bytes([0x03, 0x01, 0x6A])
    assert rendered[3] == 0x00  # zero-length string table


def test_simple_tag_roundtrip():
    w = WBXMLWriter()
    w.tag("FolderHierarchy", "FolderSync", children=[wtag("FolderHierarchy", "SyncKey", text="0")])
    nodes = WBXMLReader(w.render()).parse()
    node = find(nodes, "FolderHierarchy.FolderSync")
    assert node is not None
    assert text_of(find(node[2], "FolderHierarchy.SyncKey")) == "0"


def test_self_closing_tag_has_no_content_flag():
    w = WBXMLWriter()
    w.tag("Email", "DateReceived")  # empty element, as in a Search GreaterThan condition
    rendered = w.render()
    token = rendered[-1]  # header(4) + SWITCH_PAGE + page-num + token, self-closing so nothing follows
    assert token & 0x40 == 0  # no "has content" bit
    assert token & 0x3F == 0x0F


def test_switch_page_only_emitted_on_page_change():
    # Page 7 (FolderHierarchy) and text-free tags avoid ambiguity with the
    # 0x00 SWITCH_PAGE opcode showing up as a STR_I null terminator or as
    # page 0's own number byte.
    w = WBXMLWriter()
    w.tag(
        "FolderHierarchy",
        "FolderSync",
        children=[wtag("FolderHierarchy", "Add"), wtag("FolderHierarchy", "Delete")],
    )
    body = w.render()[4:]  # strip the 4-byte header
    # Exactly one SWITCH_PAGE (into FolderHierarchy at the very start); none
    # between Add and Delete since both are on the same page.
    assert body.count(bytes([SWITCH_PAGE])) == 1


def test_opaque_binary_field_roundtrip():
    """OPAQUE fields (e.g. ComposeMail.MIME, binary GUIDs) must carry their
    own mb_uint length and not be misread as nested tag structure."""
    payload = bytes(range(256)) * 2  # forces a multi-byte mb_uint length
    w = WBXMLWriter()
    w.tag("ComposeMail", "SendMail", children=[wtag("ComposeMail", "MIME", opaque=payload)])
    nodes = WBXMLReader(w.render()).parse()
    node = find(nodes, "ComposeMail.SendMail")
    assert node is not None
    mime_node = find(node[2], "ComposeMail.MIME")
    assert opaque_of(mime_node) == payload


def test_mb_uint_multibyte_length_encoding():
    assert _mb_uint_bytes(0) == bytes([0x00])
    assert _mb_uint_bytes(127) == bytes([0x7F])
    assert _mb_uint_bytes(128) == bytes([0x81, 0x00])
    assert _mb_uint_bytes(300) == bytes([0x82, 0x2C])


def test_leaves_flattens_nested_application_data():
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "ApplicationData",
        children=[
            wtag("Email", "Subject", text="hello"),
            wtag("Email", "Read", text="1"),
        ],
    )
    nodes = WBXMLReader(w.render()).parse()
    node = find(nodes, "AirSync.ApplicationData")
    assert node is not None
    flat = leaves(node[2])
    assert flat == {"Email.Subject": "hello", "Email.Read": "1"}


def test_golden_search_request_bytes():
    """Rebuild the exact request tree py_eas.client.Client.search_mailbox()
    sends and confirm it matches the byte-for-byte capture from a live,
    successful (Status=1) server exchange."""
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
                                    wtag("AirSync", "Class", text="Email"),
                                    wtag("AirSync", "CollectionId", text="9"),
                                    wtag(
                                        "Search",
                                        "GreaterThan",
                                        children=[
                                            wtag("Email", "DateReceived"),
                                            wtag("Search", "Value", text="2020-01-01T00:00:00.000Z"),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    wtag("Search", "Options", children=[wtag("Search", "Range", text="0-9")]),
                ],
            ),
        ],
    )
    assert w.render().hex() == GOLDEN_SEARCH_REQUEST_HEX


def test_str_i_and_end_bytes_present_in_rendered_output():
    w = WBXMLWriter()
    w.tag("Email", "Subject", text="x")
    rendered = w.render()
    assert STR_I in rendered
    assert rendered[-1] == 0x01  # END closes the tag with content
