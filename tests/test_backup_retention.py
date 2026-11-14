from datetime import datetime

import pytest

from scripts.backup_db import (
    BackupError,
    build_backup_name,
    normalize_tag,
    parse_backup_name,
    select_backups_to_delete,
)


def test_build_and_parse_backup_names() -> None:
    created_at = datetime(2026, 11, 12, 18, 30, 5)
    assert build_backup_name(created_at) == "planati-20261112-1830.dump"
    assert build_backup_name(created_at, "Pre 0010") == "planati-20261112-1830-pre-0010.dump"
    assert build_backup_name(created_at, "pre-0010", with_seconds=True) == "planati-20261112-183005-pre-0010.dump"

    parsed = parse_backup_name("planati-20261112-1830-pre-0010.dump")
    assert parsed is not None
    assert parsed.created_at == datetime(2026, 11, 12, 18, 30)
    assert parsed.tag == "pre-0010"

    with_seconds = parse_backup_name("planati-20261112-183005.dump")
    assert with_seconds is not None and with_seconds.tag is None
    assert with_seconds.created_at == datetime(2026, 11, 12, 18, 30, 5)


@pytest.mark.parametrize(
    "name",
    ["otro-archivo.dump", "planati-20261112-1830.dump.partial", "planati-2026111-1830.dump", "planati-20261340-1830.dump", "notas.txt"],
)
def test_foreign_files_are_not_backups(name: str) -> None:
    assert parse_backup_name(name) is None


def test_normalize_tag() -> None:
    assert normalize_tag("  Pre Pruebas!! ") == "pre-pruebas"
    with pytest.raises(BackupError):
        normalize_tag("***")


def test_keeps_newest_untagged_and_every_tagged_backup() -> None:
    names = [
        "planati-20261101-0900.dump",
        "planati-20261102-0900.dump",
        "planati-20261103-0900-pre-0008.dump",
        "planati-20261104-0900.dump",
        "planati-20261105-0900.dump",
        "planati-20250101-0000-pre-docker.dump",
        "otro-archivo.dump",
    ]
    assert select_backups_to_delete(names, keep=2) == ["planati-20261101-0900.dump", "planati-20261102-0900.dump"]


def test_orders_by_timestamp_in_name_not_by_list_order() -> None:
    names = ["planati-20261105-0900.dump", "planati-20261101-0900.dump", "planati-20261103-120000.dump"]
    assert select_backups_to_delete(names, keep=1) == ["planati-20261101-0900.dump", "planati-20261103-120000.dump"]


def test_nothing_to_delete_when_under_the_limit() -> None:
    names = ["planati-20261101-0900.dump", "planati-20261102-0900-pre-0010.dump"]
    assert select_backups_to_delete(names, keep=10) == []
    assert select_backups_to_delete([], keep=0) == []


def test_keep_zero_deletes_all_untagged() -> None:
    names = ["planati-20261101-0900.dump", "planati-20261102-0900-pre-0010.dump"]
    assert select_backups_to_delete(names, keep=0) == ["planati-20261101-0900.dump"]
