from __future__ import annotations

import dataclasses

import pytest

from py_eas.models import BodyType, Folder, FolderType, SyncItem, SyncResult


def test_folder_type_values_match_spec():
    assert FolderType.INBOX == 2
    assert FolderType.CALENDAR == 8
    assert FolderType.CONTACTS == 9


def test_body_type_values_match_spec():
    assert BodyType.PLAIN_TEXT == 1
    assert BodyType.HTML == 2
    assert BodyType.RTF == 3
    assert BodyType.MIME == 4


def test_folder_is_frozen():
    folder = Folder(id="9", parent_id="0", type=FolderType.INBOX, name="Inbox")
    with pytest.raises(dataclasses.FrozenInstanceError):
        folder.name = "Renamed"  # type: ignore[misc]


def test_sync_result_defaults_are_empty_and_independent():
    a = SyncResult(sync_key="1")
    b = SyncResult(sync_key="2")
    a.added.append(SyncItem(server_id="1:1"))
    assert b.added == []  # default_factory, not a shared mutable default


def test_sync_item_fields_default_empty_dict():
    item = SyncItem(server_id="1:1")
    assert item.fields == {}
