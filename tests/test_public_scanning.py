import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.public_scan import PublicScanError, scan_history, scan_tree

PROJECT_ROOT = Path(__file__).parents[1]


@pytest.fixture
def anchors(tmp_path):
    def create(*values: str) -> Path:
        path = tmp_path / "anchors.txt"
        path.write_text("\n".join(values) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    return create


class GitRepo:
    def __init__(self, path: Path):
        self.path = path

    def commit_file(self, name: str, content: str) -> None:
        (self.path / name).write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=self.path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "fixture",
            ],
            cwd=self.path,
            check=True,
            capture_output=True,
        )


@pytest.fixture
def git_repo(tmp_path) -> GitRepo:
    path = tmp_path / "repository"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return GitRepo(path)


def assert_redacted(error: BaseException, anchor: str, scanned_path: Path) -> None:
    message = str(error)
    assert anchor not in message
    assert str(scanned_path) not in message


def test_scan_tree_rejects_case_variant_in_nested_filename(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "PRIVATE-COMPANY.txt").write_text("safe", encoding="utf-8")

    with pytest.raises(ValueError) as error:
        scan_tree(root, anchors("private-company"))

    assert_redacted(error.value, "private-company", root)


def test_scan_tree_rejects_case_variant_in_utf8_content(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "record.txt").write_text("PRIVATE-COMPANY", encoding="utf-8")

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_scan_tree_rejects_case_variant_in_utf16_content(tmp_path, anchors, encoding):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "record.txt").write_bytes("PRIVATE-COMPANY".encode(encoding))

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))


def test_scan_tree_rejects_zip_member_name_and_content(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    archive = root / "records.zip"
    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr("nested/PRIVATE-COMPANY.txt", "safe")

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))

    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr("nested/record.txt", "PRIVATE-COMPANY")

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))


def test_scan_tree_rejects_symlink_and_forbidden_suffix(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("safe", encoding="utf-8")
    (root / "link.txt").symlink_to(target)

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))

    (root / "link.txt").unlink()
    (root / "credential.pem").write_text("safe", encoding="utf-8")

    with pytest.raises(ValueError):
        scan_tree(root, anchors("private-company"))


@pytest.mark.parametrize(
    "label",
    ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY"],
)
def test_scan_tree_rejects_complete_private_key_without_disclosing_file(
    tmp_path, anchors, label
):
    root = tmp_path / "tree"
    root.mkdir()
    secret_path = root / "hidden.txt"
    private_key_block = (
        f"-----BEGIN {label}-----\n"
        "QUJDREVGR0g=\n"
        f"-----END {label}-----\n"
    )
    secret_path.write_text(private_key_block, encoding="utf-8")

    with pytest.raises(ValueError) as error:
        scan_tree(root, anchors("private-company"))

    assert_redacted(error.value, "private-company", secret_path)


@pytest.mark.parametrize(
    ("label", "line_ending", "dek_info"),
    [
        (
            "RSA PRIVATE KEY",
            "\n",
            "AES-256-CBC,00112233445566778899AABBCCDDEEFF",
        ),
        ("EC PRIVATE KEY", "\r\n", "DES-EDE3-CBC,0011223344556677"),
    ],
)
def test_scan_tree_rejects_encrypted_traditional_private_key_without_disclosure(
    tmp_path, anchors, label, line_ending, dek_info
):
    root = tmp_path / "tree"
    root.mkdir()
    secret_path = root / "hidden.txt"
    private_key_block = line_ending.join(
        (
            f"-----BEGIN {label}-----",
            "Proc-Type: 4,ENCRYPTED",
            f"DEK-Info: {dek_info}",
            "",
            "QUJDREVGR0g=",
            f"-----END {label}-----",
            "",
        )
    )
    secret_path.write_bytes(private_key_block.encode("ascii"))

    with pytest.raises(ValueError) as error:
        scan_tree(root, anchors("private-company"))

    assert str(error.value) == ""
    assert_redacted(error.value, private_key_block, secret_path)
    assert "private-company" not in str(error.value)


@pytest.mark.parametrize(
    "content",
    [
        b"\x00parser constant: -----BEGIN RSA PRIVATE KEY-----\x00",
        (
            b"-----BEGIN RSA PRIVATE KEY-----\n"
            b"QUJDREVGR0g=\n"
            b"-----END EC PRIVATE KEY-----\n"
        ),
    ],
)
def test_scan_tree_allows_private_key_marker_without_matching_complete_block(
    tmp_path, anchors, content
):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "library.so").write_bytes(content)

    scan_tree(root, anchors("private-company"))


def test_scan_tree_rejects_insecure_anchor_file(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    anchor_path = anchors("private-company")
    anchor_path.chmod(0o644)

    with pytest.raises(ValueError):
        scan_tree(root, anchor_path)


def test_tree_cli_rejects_anchor_within_scanned_tree(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    anchor_path = root / "anchors.txt"
    anchor_path.write_text("private-company\n", encoding="utf-8")
    anchor_path.chmod(0o600)

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "scan-public-tree.py"),
            str(root),
            str(anchor_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_tree_cli_redacts_unsupported_zip_member_read_failure(tmp_path, anchors):
    root = tmp_path / "tree"
    root.mkdir()
    archive_path = root / "sensitive.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("private-member.txt", "public")
    archive_bytes = bytearray(archive_path.read_bytes())
    local_header = archive_bytes.index(b"PK\x03\x04")
    central_header = archive_bytes.index(b"PK\x01\x02")
    for offset in (local_header + 6, central_header + 8):
        archive_bytes[offset] |= 0x01
    archive_path.write_bytes(archive_bytes)

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "scan-public-tree.py"),
            str(root),
            str(anchors("private-company")),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_scan_history_rejects_anchor_in_older_reachable_commit(git_repo, anchors):
    git_repo.commit_file("record.txt", "PRIVATE-COMPANY")
    git_repo.commit_file("record.txt", "public")

    with pytest.raises(PublicScanError, match="public_history_scan_failed") as error:
        scan_history(git_repo.path, anchors("private-company"))

    assert_redacted(error.value, "private-company", git_repo.path)


def test_history_cli_rejects_anchor_within_repository(git_repo):
    git_repo.commit_file("record.txt", "public")
    anchor_path = git_repo.path / "anchors.txt"
    anchor_path.write_text("private-company\n", encoding="utf-8")
    anchor_path.chmod(0o600)

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "scan-public-history.py"),
            str(git_repo.path),
            str(anchor_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_scan_history_rejects_malformed_git_output(git_repo, anchors, monkeypatch):
    def malformed_rev_list(argv, **kwargs):
        assert argv == ("git", "rev-list", "--all")
        return subprocess.CompletedProcess(argv, 0, stdout=b"not-a-sha\n", stderr=b"")

    monkeypatch.setattr("scripts.public_scan.subprocess.run", malformed_rev_list)

    with pytest.raises(PublicScanError, match="^public_history_scan_failed$") as error:
        scan_history(git_repo.path, anchors("private-company"))

    assert_redacted(error.value, "private-company", git_repo.path)


def test_scan_history_rejects_failed_git_archive(git_repo, anchors, monkeypatch):
    git_repo.commit_file("record.txt", "public")
    original_run = subprocess.run

    def failed_archive(argv, **kwargs):
        if argv[:3] == ("git", "archive", "--format=tar"):
            raise subprocess.CalledProcessError(1, argv, stderr=b"PRIVATE-COMPANY")
        return original_run(argv, **kwargs)

    monkeypatch.setattr("scripts.public_scan.subprocess.run", failed_archive)

    with pytest.raises(PublicScanError, match="^public_history_scan_failed$") as error:
        scan_history(git_repo.path, anchors("private-company"))

    assert_redacted(error.value, "private-company", git_repo.path)


def test_history_cli_prints_only_fixed_success_message(git_repo, anchors):
    git_repo.commit_file("record.txt", "public")

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "scan-public-history.py"),
            str(git_repo.path),
            str(anchors("private-company")),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "public history scan passed\n"
    assert result.stderr == ""
