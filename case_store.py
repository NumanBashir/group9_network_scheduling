"""Manage locally stored TSN test cases for the project deliverable."""

from __future__ import annotations

import shutil
from pathlib import Path


LOCAL_TEST_CASES_ROOT = Path(__file__).resolve().parent / "test_cases"
REQUIRED_CASE_FILES = ("topology.json", "streams.json", "routes.json")


def import_case(source_case_directory: str | Path, destination_root: str | Path | None = None, case_name: str | None = None) -> Path:
    source_dir = Path(source_case_directory)
    _validate_case_directory(source_dir)

    destination_base = Path(destination_root) if destination_root is not None else LOCAL_TEST_CASES_ROOT
    destination_base.mkdir(parents=True, exist_ok=True)

    target_dir = destination_base / (case_name or source_dir.name)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def import_cases(
    source_root: str | Path,
    destination_root: str | Path | None = None,
    pattern: str = "test_case_*",
) -> list[Path]:
    source_root_path = Path(source_root)
    destination_base = Path(destination_root) if destination_root is not None else LOCAL_TEST_CASES_ROOT
    destination_base.mkdir(parents=True, exist_ok=True)

    imported = []
    for candidate in sorted(source_root_path.glob(pattern)):
        if not candidate.is_dir():
            continue
        if _is_case_directory(candidate):
            imported.append(import_case(candidate, destination_root=destination_base))
    return imported


def list_local_cases(root: str | Path | None = None) -> list[Path]:
    case_root = Path(root) if root is not None else LOCAL_TEST_CASES_ROOT
    if not case_root.exists():
        return []
    return sorted(path for path in case_root.iterdir() if path.is_dir() and _is_case_directory(path))


def _validate_case_directory(path: Path) -> None:
    if not _is_case_directory(path):
        raise FileNotFoundError(
            f"{path} is not a valid TSN case directory. Expected files: {', '.join(REQUIRED_CASE_FILES)}"
        )


def _is_case_directory(path: Path) -> bool:
    return path.is_dir() and all((path / file_name).exists() for file_name in REQUIRED_CASE_FILES)

