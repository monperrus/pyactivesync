from __future__ import annotations

import uuid
from email.message import EmailMessage
from unittest.mock import patch

import pytest

from pyactivesync import Client
from pyactivesync._wbxml import WBXMLReader, find, opaque_of, text_of


def _client(*, provisioned: bool = True) -> Client:
    client = Client("example.invalid", "user", "password", device_id="SendMailTest")
    client._provisioned = provisioned
    return client


def _message() -> EmailMessage:
    message = EmailMessage()
    message["To"] = "recipient@example.com"
    message["Subject"] = "test"
    message.set_content("body")
    return message


def test_send_mail_uses_supplied_client_id_unchanged() -> None:
    client = _client()
    with patch("pyactivesync.client.uuid.uuid4") as uuid4, patch.object(client, "_post", return_value=b"") as post:
        client.send_mail(_message(), client_id="submission-42")

    uuid4.assert_not_called()
    assert post.call_args.args[0] == "SendMail"
    assert post.call_args.kwargs == {}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    assert text_of(find(nodes, "ComposeMail.ClientId")) == "submission-42"
    assert find(nodes, "ComposeMail.SaveInSentItems") is not None
    mime = opaque_of(find(nodes, "ComposeMail.MIME"))
    assert mime is not None and b"Subject: test\r\n" in mime


def test_send_mail_generates_uuid_hex_client_id() -> None:
    client = _client()
    generated = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("pyactivesync.client.uuid.uuid4", return_value=generated) as uuid4, patch.object(
        client, "_post", return_value=b""
    ) as post:
        client.send_mail(_message(), save_in_sent_items=False)

    uuid4.assert_called_once_with()
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    assert text_of(find(nodes, "ComposeMail.ClientId")) == generated.hex
    assert find(nodes, "ComposeMail.SaveInSentItems") is None


@pytest.mark.parametrize(
    ("client_id", "error", "message"),
    [
        ("", ValueError, "between 1 and 40"),
        ("x" * 41, ValueError, "between 1 and 40"),
        ("contains\x00null", ValueError, "not valid in XML"),
        (123, TypeError, "must be a string"),
    ],
)
def test_send_mail_rejects_invalid_client_id_before_provisioning_or_http(
    client_id: object, error: type[Exception], message: str
) -> None:
    client = _client(provisioned=False)
    with (
        patch.object(client, "_ensure_provisioned") as provision,
        patch.object(client, "_post") as post,
        pytest.raises(error, match=message),
    ):
        client.send_mail(_message(), client_id=client_id)  # type: ignore[arg-type]
    provision.assert_not_called()
    post.assert_not_called()


def test_send_mail_accepts_40_character_client_id() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=b"") as post:
        client.send_mail(_message(), client_id="x" * 40)
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    assert text_of(find(nodes, "ComposeMail.ClientId")) == "x" * 40
