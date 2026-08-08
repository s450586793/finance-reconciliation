from __future__ import annotations

import re
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = {
    ".env",
    ".git",
    ".superpowers",
    ".venv",
    ".workflow",
    "__pycache__",
    "db.sqlite3",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"}
PRIVATE_KEY_BLOCK_PATTERN = re.compile(
    br"-----BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY)-----\r?\n"
    br"(?:(?:[A-Za-z0-9-]+:[ \t]*[ -~]+\r?\n)+\r?\n)?"
    br"(?:[A-Za-z0-9+/]{4,}={0,2}\r?\n)+"
    br"-----END (?P=label)-----"
)
COMMIT_PATTERN = re.compile(br"[0-9a-f]{40}")


class PublicScanError(ValueError):
    pass


def _load_anchor_variants(anchor_path: Path) -> list[tuple[bytes, bytes, bytes]]:
    if anchor_path.is_symlink() or not anchor_path.is_file():
        raise ValueError
    if stat.S_IMODE(anchor_path.stat().st_mode) != 0o600:
        raise ValueError
    anchors = [
        line.strip()
        for line in anchor_path.read_bytes().splitlines()
        if line.strip() and not line.lstrip().startswith(b"#")
    ]
    if not anchors:
        raise ValueError
    variants = []
    for anchor in anchors:
        text = anchor.decode("utf-8", errors="strict")
        variants.append((anchor, text.encode("utf-16-le"), text.encode("utf-16-be")))
    return variants


def _scan_bytes(data: bytes, anchors: list[tuple[bytes, bytes, bytes]]) -> None:
    folded = data.lower()
    if PRIVATE_KEY_BLOCK_PATTERN.search(data):
        raise ValueError
    if any(candidate.lower() in folded for variants in anchors for candidate in variants):
        raise ValueError


def _reject_contained_path(root: Path, candidate: Path) -> None:
    if candidate == root or root in candidate.parents:
        raise ValueError


def scan_tree(root: Path, anchor_path: Path) -> None:
    try:
        if root.is_symlink() or not root.is_dir():
            raise ValueError
        if anchor_path.is_symlink():
            raise ValueError
        root = root.resolve(strict=True)
        anchor_path = anchor_path.resolve(strict=True)
        _reject_contained_path(root, anchor_path)
        anchors = _load_anchor_variants(anchor_path)
        archive_total = 0
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in FORBIDDEN_NAMES for part in relative.parts):
                raise ValueError
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError
            if path.is_symlink():
                raise ValueError
            if path.is_dir():
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError
            _scan_bytes(str(relative).encode("utf-8"), anchors)
            data = path.read_bytes()
            _scan_bytes(data, anchors)
            if not zipfile.is_zipfile(path):
                continue
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.file_size > 64 * 1024 * 1024:
                        raise ValueError
                    archive_total += member.file_size
                    if archive_total > 256 * 1024 * 1024:
                        raise ValueError
                    _scan_bytes(member.filename.encode("utf-8"), anchors)
                    _scan_bytes(archive.read(member), anchors)
    except (OSError, RuntimeError, UnicodeError, zipfile.BadZipFile) as error:
        raise ValueError from error


def scan_history(repository: Path, anchor_path: Path) -> None:
    try:
        if anchor_path.is_symlink():
            raise ValueError
        repository = repository.resolve(strict=True)
        anchor_path = anchor_path.resolve(strict=True)
        _reject_contained_path(repository, anchor_path)
        _load_anchor_variants(anchor_path)
        commits = subprocess.run(
            ("git", "rev-list", "--all"),
            cwd=repository,
            check=True,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout.splitlines()
        if any(COMMIT_PATTERN.fullmatch(commit) is None for commit in commits):
            raise ValueError
        for commit in commits:
            with tempfile.TemporaryDirectory(prefix="public-history-") as tempdir:
                temporary_root = Path(tempdir)
                archive_path = temporary_root / "commit.tar"
                with archive_path.open("xb") as archive_file:
                    subprocess.run(
                        ("git", "archive", "--format=tar", commit.decode("ascii")),
                        cwd=repository,
                        check=True,
                        shell=False,
                        stdout=archive_file,
                        stderr=subprocess.DEVNULL,
                    )
                tree_root = temporary_root / "tree"
                tree_root.mkdir()
                with tarfile.open(archive_path) as archive:
                    archive.extractall(tree_root, filter="data")
                scan_tree(tree_root, anchor_path)
    except Exception as error:
        raise PublicScanError("public_history_scan_failed") from error
