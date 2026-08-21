from __future__ import annotations

import os

import pytest

from py_eas import Client

_ENV_VARS = ("PY_EAS_TEST_SERVER", "PY_EAS_TEST_USER", "PY_EAS_TEST_PASSWORD")


def _missing_env_vars() -> list[str]:
    return [v for v in _ENV_VARS if not os.environ.get(v)]


@pytest.fixture(scope="session")
def live_client():
    missing = _missing_env_vars()
    if missing:
        pytest.skip(f"live server not configured: {', '.join(missing)} not set")
    with Client(
        server=os.environ["PY_EAS_TEST_SERVER"],
        username=os.environ["PY_EAS_TEST_USER"],
        password=os.environ["PY_EAS_TEST_PASSWORD"],
        device_id=os.environ.get("PY_EAS_TEST_DEVICE_ID", "py-eas-pytest"),
        user=os.environ.get("PY_EAS_TEST_SMTP_USER"),
    ) as client:
        yield client


@pytest.fixture(scope="session")
def preexisting_folder_ids(live_client):
    """The folder ids that existed before this test session -- asserted
    unchanged at session end so live tests never leak state into a real
    mailbox."""
    return {f.id for f in live_client.list_folders()}
