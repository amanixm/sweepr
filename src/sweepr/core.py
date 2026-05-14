"""Core planning, move, and undo logic for sweepr."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

MANIFEST_DIR_NAME = ".sweepr"
LATEST_MANIFEST_NAME = "latest.json"
MANIFEST_PREFIX = "undo-"

FILE_TYPES: dict[str, set[str]] = {
    "Images": {
        ".avif",
        ".bmp",
        ".cr2",
        ".gif",
        ".heic",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".raw",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    },
    "Documents": {
        ".csv",
        ".doc",
        ".docx",
        ".epub",
        ".md",
        ".ods",
        ".odt",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rtf",
        ".txt",
        ".xls",
        ".xlsx",
    },
    "Videos": {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
    },
    "Audio": {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".opus",
        ".wav",
        ".wma",
    },
    "Archives": {
        ".7z",
        ".bz2",
        ".gz",
        ".rar",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
        ".zst",
    },
    "Code": {
        ".c",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".php",
        ".ps1",
        ".py",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".xml",
        ".yaml",
        ".yml",
    },
    "Design": {
        ".ai",
        ".fig",
        ".indd",
        ".psd",
        ".sketch",
        ".xd",
    },
    "Fonts": {
        ".eot",
        ".otf",
        ".ttf",
        ".woff",
        ".woff2",
    },
    "Installers": {
        ".apk",
        ".appimage",
        ".deb",
        ".dmg",
        ".exe",
        ".msi",
        ".pkg",
        ".rpm",
    },
    "Others": {
        ".bak",
        ".crdownload",
        ".log",
        ".old",
        ".part",
        ".tmp",
    },
}

CATEGORY_EXTENSIONS = FILE_TYPES


class SweeprError(Exception):
    """Base exception for user-facing sweepr failures."""


class InvalidPathError(SweeprError):
    """Raised when the requested root path cannot be organized."""


class UndoManifestNotFoundError(FileNotFoundError, SweeprError):
    """Raised when undo is requested but no pending undo manifest exists."""


class OrganizeMode(str, Enum):
    """Supported organization strategies."""

    TYPE = "type"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class MoveOperation:
    """A planned single-file move."""

    source: Path
    destination: Path
    category: str
    size: int


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    """A file that was deliberately skipped while planning."""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """A complete organization plan."""

    root: Path
    mode: OrganizeMode
    recursive: bool
    operations: tuple[MoveOperation, ...]
    skipped: tuple[SkippedEntry, ...]

    @property
    def total_size(self) -> int:
        """Total number of bytes planned to move."""

        return sum(operation.size for operation in self.operations)


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Result of executing a sweep plan."""

    root: Path
    dry_run: bool
    planned: int
    moved: int
    skipped: int
    manifest_path: Path | None
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UndoResult:
    """Result of restoring files from an undo manifest."""

    root: Path
    restored: int
    skipped: int
    manifest_path: Path
    errors: tuple[str, ...]


ProgressCallback = Callable[[MoveOperation, Path | None, str | None], None]
UndoCallback = Callable[[Path, Path, str | None], None]
ExcludeInput = str | list[str] | tuple[str, ...]


def categorize_file(path: Path) -> str:
    """Return the destination category for a file path."""

    suffix = path.suffix.lower()
    for category, extensions in FILE_TYPES.items():
        if suffix in extensions:
            return category
    return "Other"


def create_plan(
    path: str | Path,
    mode: OrganizeMode,
    recursive: bool = False,
    exclude: ExcludeInput | None = None,
) -> SweepPlan:
    """Create a deterministic move plan without touching the filesystem."""

    root = _normalize_root(path)
    organization_mode = OrganizeMode(mode)
    exclude_patterns = _normalize_exclude_patterns(exclude)
    metadata_dir = root / MANIFEST_DIR_NAME
    reserved_destinations: set[Path] = set()
    operations: list[MoveOperation] = []
    skipped: list[SkippedEntry] = []

    for source in _iter_candidate_files(root, recursive=recursive):
        if _is_under(source, metadata_dir):
            continue

        if matched_pattern := _matching_exclude_pattern(
            source,
            root=root,
            patterns=exclude_patterns,
        ):
            skipped.append(
                SkippedEntry(
                    path=source,
                    reason=f"excluded by pattern: {matched_pattern}",
                )
            )
            continue

        if source.is_symlink():
            skipped.append(SkippedEntry(path=source, reason="symlink skipped for safety"))
            continue

        try:
            stat = source.stat()
        except OSError as exc:
            skipped.append(SkippedEntry(path=source, reason=f"could not read file metadata: {exc}"))
            continue

        destination, category = _destination_for(
            source,
            root=root,
            mode=organization_mode,
            size=stat.st_size,
        )

        if _same_path(source, destination):
            skipped.append(SkippedEntry(path=source, reason="already organized"))
            continue

        destination = _dedupe_destination(destination, reserved=reserved_destinations)
        reserved_destinations.add(destination)

        operations.append(
            MoveOperation(
                source=source,
                destination=destination,
                category=category,
                size=stat.st_size,
            )
        )

    return SweepPlan(
        root=root,
        mode=organization_mode,
        recursive=recursive,
        operations=tuple(operations),
        skipped=tuple(skipped),
    )


def execute_plan(
    plan: SweepPlan,
    *,
    dry_run: bool = True,
    on_operation: ProgressCallback | None = None,
) -> SweepResult:
    """Execute a sweep plan, or return a preview result when ``dry_run`` is true."""

    if dry_run:
        return SweepResult(
            root=plan.root,
            dry_run=True,
            planned=len(plan.operations),
            moved=0,
            skipped=len(plan.skipped),
            manifest_path=None,
            errors=(),
        )

    if not plan.operations:
        return SweepResult(
            root=plan.root,
            dry_run=False,
            planned=0,
            moved=0,
            skipped=len(plan.skipped),
            manifest_path=None,
            errors=(),
        )

    manifest_path = _new_manifest_path(plan.root)
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    manifest: dict[str, Any] = {
        "version": 1,
        "created_at": _utc_now(),
        "undone_at": None,
        "root": str(plan.root),
        "mode": plan.mode.value,
        "recursive": plan.recursive,
        "moves": records,
    }
    _write_json(manifest_path, manifest)

    for operation in plan.operations:
        actual_destination: Path | None = None
        error: str | None = None

        try:
            if not operation.source.exists():
                raise FileNotFoundError(f"source no longer exists: {operation.source}")

            actual_destination = _dedupe_destination(operation.destination, reserved=set())
            actual_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(operation.source), str(actual_destination))

            records.append(
                {
                    "source": str(operation.source),
                    "destination": str(actual_destination),
                    "category": operation.category,
                    "size": operation.size,
                }
            )
            _write_json(manifest_path, manifest)
        except OSError as exc:
            error = f"{operation.source} -> {operation.destination}: {exc}"
            errors.append(error)
        finally:
            if on_operation is not None:
                on_operation(operation, actual_destination, error)

    if records:
        _write_latest_pointer(plan.root, manifest_path)
    else:
        manifest_path.unlink(missing_ok=True)
        manifest_path = None

    return SweepResult(
        root=plan.root,
        dry_run=False,
        planned=len(plan.operations),
        moved=len(records),
        skipped=len(plan.skipped),
        manifest_path=manifest_path,
        errors=tuple(errors),
    )


def undo(path: str | Path, on_restore: UndoCallback | None = None) -> UndoResult:
    """Restore files from the latest pending undo manifest."""

    root = _normalize_root(path)
    manifest_path = _latest_manifest_path(root)
    manifest = _read_json(manifest_path)
    moves = list(manifest.get("moves", []))
    restored = 0
    errors: list[str] = []

    for record in reversed(moves):
        destination = Path(str(record["destination"]))
        source = Path(str(record["source"]))
        error: str | None = None

        try:
            if not destination.exists():
                raise FileNotFoundError(f"moved file no longer exists: {destination}")
            if source.exists():
                raise FileExistsError(f"refusing to overwrite existing file: {source}")

            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
            _prune_empty_parents(destination.parent, root)
            restored += 1
        except OSError as exc:
            error = f"{destination} -> {source}: {exc}"
            errors.append(error)
        finally:
            if on_restore is not None:
                on_restore(destination, source, error)

    if not errors:
        manifest["undone_at"] = _utc_now()
        _write_json(manifest_path, manifest)
        _refresh_latest_pointer(root)

    return UndoResult(
        root=root,
        restored=restored,
        skipped=len(errors),
        manifest_path=manifest_path,
        errors=tuple(errors),
    )


def format_size(num_bytes: int) -> str:
    """Return a compact human-readable size string."""

    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{num_bytes} B"


def _normalize_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise InvalidPathError(f"Path does not exist: {root}")
    if not root.is_dir():
        raise InvalidPathError(f"Path is not a directory: {root}")
    return root


def _iter_candidate_files(root: Path, *, recursive: bool) -> tuple[Path, ...]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    return tuple(path for path in iterator if path.is_file() or path.is_symlink())


def _normalize_exclude_patterns(exclude: ExcludeInput | None) -> tuple[str, ...]:
    if exclude is None:
        return ()

    raw_patterns = [exclude] if isinstance(exclude, str) else list(exclude)
    patterns: list[str] = []

    for raw_pattern in raw_patterns:
        for pattern in raw_pattern.split(","):
            normalized = pattern.strip().rstrip("/\\")
            if normalized.startswith(("./", ".\\")):
                normalized = normalized[2:]
            if normalized:
                patterns.append(normalized)

    return tuple(patterns)


def _matching_exclude_pattern(path: Path, *, root: Path, patterns: tuple[str, ...]) -> str | None:
    if not patterns:
        return None

    relative = path.relative_to(root)
    relative_posix = relative.as_posix()
    absolute_posix = path.as_posix()

    for pattern in patterns:
        pattern_path = Path(pattern).expanduser()
        pattern_posix = pattern.replace("\\", "/")

        if pattern_path.is_absolute():
            resolved_pattern = pattern_path.resolve(strict=False)
            if _has_glob(pattern) and fnmatch(absolute_posix, resolved_pattern.as_posix()):
                return pattern
            if not _has_glob(pattern) and (
                path == resolved_pattern or _is_under(path, resolved_pattern)
            ):
                return pattern
            continue

        if "/" not in pattern_posix:
            if any(fnmatch(part, pattern_posix) for part in relative.parts):
                return pattern
            if fnmatch(relative_posix, pattern_posix):
                return pattern
            continue

        relative_pattern = pattern_posix.strip("/")
        if not _has_glob(relative_pattern) and (
            relative_posix == relative_pattern or relative_posix.startswith(f"{relative_pattern}/")
        ):
            return pattern
        if fnmatch(relative_posix, relative_pattern):
            return pattern

    return None


def _has_glob(pattern: str) -> bool:
    return any(character in pattern for character in "*?[")


def _destination_for(
    source: Path,
    *,
    root: Path,
    mode: OrganizeMode,
    size: int,
) -> tuple[Path, str]:
    del size

    if mode is OrganizeMode.TYPE:
        category = categorize_file(source)
        return root / category / source.name, category

    modified = datetime.fromtimestamp(source.stat().st_mtime)
    category = f"{modified:%Y}/{modified:%m}"
    return root / f"{modified:%Y}" / f"{modified:%m}" / source.name, category


def _dedupe_destination(destination: Path, *, reserved: set[Path]) -> Path:
    if destination not in reserved and not destination.exists():
        return destination

    counter = 1
    while True:
        candidate = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
        if candidate not in reserved and not candidate.exists():
            return candidate
        counter += 1


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _manifest_dir(root: Path) -> Path:
    return root / MANIFEST_DIR_NAME


def _new_manifest_path(root: Path) -> Path:
    manifest_dir = _manifest_dir(root)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidate = manifest_dir / f"{MANIFEST_PREFIX}{timestamp}.json"

    counter = 1
    while candidate.exists():
        candidate = manifest_dir / f"{MANIFEST_PREFIX}{timestamp}-{counter}.json"
        counter += 1

    return candidate


def _latest_manifest_path(root: Path) -> Path:
    manifest_dir = _manifest_dir(root)
    latest_file = manifest_dir / LATEST_MANIFEST_NAME

    if latest_file.exists():
        try:
            latest = _read_json(latest_file)
            candidate = manifest_dir / str(latest["manifest"])
            if candidate.exists() and _is_pending_manifest(candidate):
                return candidate
        except (KeyError, OSError, json.JSONDecodeError):
            pass

    pending = _pending_manifests(root)
    if not pending:
        raise UndoManifestNotFoundError(f"No sweepr undo manifest found in {root}")
    return pending[-1]


def _pending_manifests(root: Path) -> list[Path]:
    manifest_dir = _manifest_dir(root)
    if not manifest_dir.exists():
        return []
    return [
        manifest
        for manifest in sorted(manifest_dir.glob(f"{MANIFEST_PREFIX}*.json"))
        if _is_pending_manifest(manifest)
    ]


def _is_pending_manifest(path: Path) -> bool:
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return not manifest.get("undone_at")


def _write_latest_pointer(root: Path, manifest_path: Path) -> None:
    latest_file = _manifest_dir(root) / LATEST_MANIFEST_NAME
    _write_json(latest_file, {"manifest": manifest_path.name})


def _refresh_latest_pointer(root: Path) -> None:
    latest_file = _manifest_dir(root) / LATEST_MANIFEST_NAME
    pending = _pending_manifests(root)

    if pending:
        _write_latest_pointer(root, pending[-1])
    else:
        latest_file.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _prune_empty_parents(start: Path, stop: Path) -> None:
    current = start
    while current != stop and _is_under(current, stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
