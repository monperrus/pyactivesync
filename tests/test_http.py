from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from pyactivesync._http import Transport


def _response(status_code: int) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = b"body"
    return resp


@pytest.fixture
def transport() -> Transport:
    return Transport("eas.example.com", "user", "pass", device_id="dev1")


def test_idempotent_retries_on_5xx_then_succeeds(transport: Transport) -> None:
    responses = [_response(503), _response(503), _response(200)]
    with patch.object(transport.session, "post", side_effect=responses) as post, patch("time.sleep"):
        body = transport.post("Sync", "user@example.com", b"<wbxml>", idempotent=True)
    assert body == b"body"
    assert post.call_count == 3


def test_idempotent_gives_up_after_retry_total(transport: Transport) -> None:
    responses = [_response(503)] * 5
    with patch.object(transport.session, "post", side_effect=responses) as post, patch("time.sleep"):
        with pytest.raises(requests.HTTPError):
            transport.post("Sync", "user@example.com", b"<wbxml>", idempotent=True)
    assert post.call_count == 4  # initial attempt + 3 retries


def test_non_idempotent_does_not_retry_on_5xx(transport: Transport) -> None:
    with patch.object(transport.session, "post", return_value=_response(503)) as post:
        with pytest.raises(requests.HTTPError):
            transport.post("SendMail", "user@example.com", b"<wbxml>", idempotent=False)
    assert post.call_count == 1


def test_non_idempotent_is_the_default(transport: Transport) -> None:
    with patch.object(transport.session, "post", return_value=_response(503)) as post:
        with pytest.raises(requests.HTTPError):
            transport.post("SendMail", "user@example.com", b"<wbxml>")
    assert post.call_count == 1
