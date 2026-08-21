"""Integration tests against a real EAS server.

Skipped (not failed) unless PY_EAS_TEST_SERVER / PY_EAS_TEST_USER /
PY_EAS_TEST_PASSWORD are set, so `pytest` stays green on a plain checkout
and in default CI. Run manually against a real account before a release:

    PY_EAS_TEST_SERVER=mail.example.com \\
    PY_EAS_TEST_USER='CORP\\jdoe' \\
    PY_EAS_TEST_PASSWORD=... \\
    pytest tests/test_client_live.py

Mutating tests only ever create/rename/delete objects prefixed
`py-eas-test-` that they create themselves; a session-scoped fixture
(`preexisting_folder_ids`) asserts the pre-existing folder set is
unchanged at the end of the run.
"""
from __future__ import annotations

import time
import uuid
from email.message import EmailMessage

import pytest

from py_eas import FolderType
from py_eas.exceptions import StatusError


def test_provision_returns_policy_key(live_client):
    key = live_client.provision()
    assert key


def test_list_folders_includes_inbox(live_client):
    folders = live_client.list_folders()
    assert any(f.type == FolderType.INBOX for f in folders)


def test_sync_folder_bootstrap_then_delta(live_client):
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    bootstrap = live_client.sync_folder(inbox.id)
    assert bootstrap.sync_key != "0"
    delta = live_client.sync_folder(inbox.id, sync_key=bootstrap.sync_key)
    assert delta.sync_key


def test_get_item_estimate(live_client):
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    bootstrap = live_client.sync_folder(inbox.id)
    estimate = live_client.get_item_estimate(inbox.id, bootstrap.sync_key)
    assert estimate >= 0


def test_resolve_recipients_self(live_client):
    recipients = live_client.resolve_recipients(live_client.user)
    assert isinstance(recipients, list)


def test_folder_lifecycle_only_touches_its_own_folder(live_client, preexisting_folder_ids):
    """FolderCreate -> FolderUpdate -> FolderDelete against a throwaway
    folder only; asserts the pre-existing folder set is untouched."""
    name = f"py-eas-test-{uuid.uuid4().hex[:8]}"
    folder = live_client.create_folder(name, parent_id="0", type=FolderType.USER_GENERIC)
    assert folder.id not in preexisting_folder_ids

    renamed = f"{name}-renamed"
    live_client.update_folder(folder.id, renamed, parent_id="0")

    live_client.delete_folder(folder.id)

    folders_after = {f.id for f in live_client.list_folders()}
    assert preexisting_folder_ids <= folders_after
    assert folder.id not in folders_after


def test_send_mail_move_and_fetch_attachment(live_client, preexisting_folder_ids):
    """SendMail -> locate via Sync -> Fetch body -> FolderCreate -> MoveItems
    -> Fetch attachment -> FolderDelete (cascades, cleans up the message
    too). Only ever touches the throwaway folder/message this test creates."""
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    marker = f"py-eas-test-{uuid.uuid4().hex[:8]}"

    msg = EmailMessage()
    msg["To"] = live_client.user
    msg["Subject"] = marker
    msg.set_content("throwaway message for py-eas integration tests")
    msg.add_attachment(b"hello from py-eas", maintype="application", subtype="octet-stream", filename="test.txt")
    live_client.send_mail(msg)

    item_id = None
    sync_key = "0"
    for _ in range(10):
        result = live_client.sync_folder(inbox.id, sync_key=sync_key, window_size=25)
        sync_key = result.sync_key
        match = next((i for i in result.added if i.fields.get("Email.Subject") == marker), None)
        if match:
            item_id = match.server_id
            break
        time.sleep(3)
    assert item_id, f"message {marker!r} never showed up via Sync"

    body = live_client.fetch_item(inbox.id, item_id)
    assert body

    folder_name = f"py-eas-test-{uuid.uuid4().hex[:8]}"
    test_folder = live_client.create_folder(folder_name, parent_id="0", type=FolderType.USER_GENERIC)
    assert test_folder.id not in preexisting_folder_ids

    new_id = live_client.move_item(item_id, inbox.id, test_folder.id)
    assert new_id

    props = live_client.fetch_item(test_folder.id, new_id)
    file_ref = props.get("AirSyncBase.FileReference")
    if file_ref:
        data = live_client.fetch_attachment(file_ref)
        assert data == b"hello from py-eas"

    live_client.delete_folder(test_folder.id)
    folders_after = {f.id for f in live_client.list_folders()}
    assert preexisting_folder_ids <= folders_after


def test_search_gal_for_self(live_client):
    try:
        results = live_client.search_gal(live_client.user)
    except StatusError:
        pytest.skip("GAL search not supported/enabled on this server")
    assert isinstance(results, list)


def test_ping_returns_a_status(live_client):
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    result = live_client.ping(inbox.id, timeout=10)
    assert result.status
