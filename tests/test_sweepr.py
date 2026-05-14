from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from sweepr.core import OrganizeMode, create_plan, execute_plan, undo


def touch(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_create_type_plan_groups_known_extensions(tmp_path: Path) -> None:
    image = touch(tmp_path / "photo.JPG")
    document = touch(tmp_path / "notes.pdf")
    unknown = touch(tmp_path / "backup.xyz")

    plan = create_plan(tmp_path, mode=OrganizeMode.TYPE)

    destinations = {operation.source: operation.destination for operation in plan.operations}
    assert destinations[image] == tmp_path / "Images" / "photo.JPG"
    assert destinations[document] == tmp_path / "Documents" / "notes.pdf"
    assert destinations[unknown] == tmp_path / "Other" / "backup.xyz"


def test_dry_run_does_not_move_files(tmp_path: Path) -> None:
    source = touch(tmp_path / "photo.png")
    plan = create_plan(tmp_path, mode=OrganizeMode.TYPE)

    result = execute_plan(plan, dry_run=True)

    assert result.moved == 0
    assert result.planned == 1
    assert source.exists()
    assert not (tmp_path / "Images" / "photo.png").exists()


def test_execute_plan_moves_files_and_undo_restores_them(tmp_path: Path) -> None:
    source = touch(tmp_path / "photo.png", "image")
    plan = create_plan(tmp_path, mode=OrganizeMode.TYPE)

    result = execute_plan(plan, dry_run=False)
    destination = tmp_path / "Images" / "photo.png"

    assert result.moved == 1
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "image"

    undo_result = undo(tmp_path)

    assert undo_result.restored == 1
    assert source.read_text(encoding="utf-8") == "image"
    assert not destination.exists()


def test_create_date_plan_uses_modified_year_and_month(tmp_path: Path) -> None:
    source = touch(tmp_path / "report.txt")
    modified = datetime(2024, 7, 3, 12, 30).timestamp()
    os.utime(source, (modified, modified))

    plan = create_plan(tmp_path, mode=OrganizeMode.DATE)

    assert plan.operations[0].destination == tmp_path / "2024" / "07" / "report.txt"


def test_recursive_plan_includes_nested_files(tmp_path: Path) -> None:
    nested = touch(tmp_path / "inbox" / "clip.mp4")

    plan = create_plan(tmp_path, mode=OrganizeMode.TYPE, recursive=True)

    assert plan.operations[0].source == nested
    assert plan.operations[0].destination == tmp_path / "Videos" / "clip.mp4"


def test_undo_without_manifest_raises_user_facing_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No sweepr undo manifest"):
        undo(tmp_path)
