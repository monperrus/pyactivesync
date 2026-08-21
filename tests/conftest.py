from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from pyactivesync import Client

_ENV_VARS = ("PYACTIVESYNC_TEST_SERVER", "PYACTIVESYNC_TEST_USER", "PYACTIVESYNC_TEST_PASSWORD")


def _missing_env_vars() -> list[str]:
    return [v for v in _ENV_VARS if not os.environ.get(v)]


@pytest.fixture(scope="session")
def live_client() -> Iterator[Client]:
    missing = _missing_env_vars()
    if missing:
        pytest.skip(f"live server not configured: {', '.join(missing)} not set")
    with Client(
        server=os.environ["PYACTIVESYNC_TEST_SERVER"],
        username=os.environ["PYACTIVESYNC_TEST_USER"],
        password=os.environ["PYACTIVESYNC_TEST_PASSWORD"],
        device_id=os.environ.get("PYACTIVESYNC_TEST_DEVICE_ID", "pyactivesync-pytest"),
        user=os.environ.get("PYACTIVESYNC_TEST_SMTP_USER"),
    ) as client:
        yield client


@pytest.fixture(scope="session")
def preexisting_folder_ids(live_client: Client) -> set[str]:
    """The folder ids that existed before this test session -- asserted
    unchanged at session end so live tests never leak state into a real
    mailbox."""
    return {f.id for f in live_client.list_folders()}
