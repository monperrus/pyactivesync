"""Thin HTTP transport for EAS: one ``requests.Session``, auth + headers + retries."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_RETRYABLE_STATUS = (500, 502, 503, 504)


class Transport:
    """POSTs WBXML bodies to ``/Microsoft-Server-ActiveSync`` and returns raw response bytes."""

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        *,
        device_id: str,
        device_type: str = "pyactivesync",
        protocol_version: str = "14.1",
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = f"https://{server}/Microsoft-Server-ActiveSync"
        self.device_id = device_id
        self.device_type = device_type
        self.protocol_version = protocol_version
        self.timeout = timeout
        self.policy_key: str | None = None

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_ssl
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=_RETRYABLE_STATUS,
            allowed_methods=frozenset({"POST"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def post(
        self,
        cmd: str,
        user: str,
        wbxml: bytes,
        *,
        extra_params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        params = {
            "Cmd": cmd,
            "User": user,
            "DeviceId": self.device_id,
            "DeviceType": self.device_type,
        }
        if extra_params:
            params.update(extra_params)
        headers = {
            "Content-Type": "application/vnd.ms-sync.wbxml",
            "MS-ASProtocolVersion": self.protocol_version,
        }
        if self.policy_key:
            headers["X-MS-PolicyKey"] = self.policy_key
        resp = self.session.post(
            self.base_url,
            params=params,
            data=wbxml,
            headers=headers,
            timeout=timeout if timeout is not None else self.timeout,
        )
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self.session.close()
