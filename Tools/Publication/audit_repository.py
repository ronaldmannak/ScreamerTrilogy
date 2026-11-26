#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Check source publication inputs without executing games or printing secrets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

MAX_SOURCE_BYTES = 2 * 1024 * 1024
ALLOWED_ROOTS = {"NativeRenderer", "Tools", "wrappers", "checkpoints", ".github", "docs"}
ALLOWED_ROOT_FILES = {"README.md", "LICENSE", "LICENSING.md", ".gitignore", "SOURCE-MANIFEST.json"}
TEXT_SUFFIXES = {".py", ".m", ".mm", ".metal", ".md", ".json", ".plist", ".patch",
                 ".txt", ".rs", ".conf", ".inc", ".glsl", ".yml", ".yaml"}
BLOCKED_COMPONENTS = {"Archives", "Captures", "Extracted", "EngineBuild", "__pycache__",
                      "dist", "rebuild", "backups", "recovery", ".git"}
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "openai-token": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b"),
}
PERSONAL_PATH = re.compile(r"/(?:Users|home)/[^/\s\"'<>]+/")
EMBEDDED_IMAGE = re.compile(r"data:(?:image|audio|application/octet-stream)/?[^\s\"']*;base64,", re.I)
# A long uninterrupted base64 literal is an asset/capture candidate, regardless of extension.
LONG_BASE64 = re.compile(r"[\"'][A-Za-z0-9+/]{2048,}={0,2}[\"']")


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def source_paths(root: Path) -> list[str]:
    """Include tracked edits and new nonignored files, never ignored app/build data."""
    return sorted(set(filter(None, git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0"))))


def path_issues(name: str) -> list[str]:
    path = PurePosixPath(name)
    parts = path.parts
    if path.is_absolute() or not parts or any(p in {"..", "."} for p in parts) or "\\" in name or any(ord(c) < 32 for c in name):
        return ["unsafe-path"]
    issues = []
    if (parts[0] not in ALLOWED_ROOTS and name not in ALLOWED_ROOT_FILES):
        issues.append("outside-source-allowlist")
    if any(p in BLOCKED_COMPONENTS or p.endswith(".app") or p.startswith("build-") for p in parts[:-1]):
        issues.append("generated-or-game-directory")
    if path.suffix.lower() not in TEXT_SUFFIXES and not path.name.startswith(("LICENSE", "NOTICE")) and path.name not in {".gitignore"}:
        issues.append("not-allowlisted-source-type")
    return issues


def content_issues(data: bytes) -> list[str]:
    issues = []
    if len(data) > MAX_SOURCE_BYTES:
        issues.append("oversized-source-review-required")
    if b"\0" in data:
        issues.append("binary-content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return issues + ["non-utf8-content"]
    for key, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            issues.append(key)
    if PERSONAL_PATH.search(text):
        issues.append("personal-absolute-path")
    if EMBEDDED_IMAGE.search(text) or LONG_BASE64.search(text):
        issues.append("embedded-payload-review-required")
    return issues


def current_report(root: Path) -> dict:
    paths = source_paths(root)
    findings = []
    for name in paths:
        path = root / name
        issues = path_issues(name)
        if path.is_symlink():
            issues.append("symlink-not-allowed")
        elif not path.is_file():
            issues.append("missing-or-nonregular-file")
        else:
            issues.extend(content_issues(path.read_bytes()))
        if issues:
            findings.append({"path": name, "issues": sorted(set(issues))})
    return {"files": len(paths), "findings": findings, "passed": not findings}


def history_report(root: Path) -> dict:
    """Inspect every reachable blob once; do not expose matching secret values."""
    objects = git(root, "rev-list", "--objects", "--all").decode().splitlines()
    if not objects:
        return {"blobs": 0, "findings": [], "warnings": [], "passed": True}
    metadata = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)"],
                              input="\n".join(objects) + "\n", text=True, capture_output=True, check=True).stdout
    findings, warnings = [], []
    count = 0
    content_by_object = {}
    for line in metadata.splitlines():
        fields = line.split(" ", 3)
        if len(fields) != 4 or fields[1] != "blob":
            continue
        object_id, _, size, _ = fields
        count += 1
        content_by_object[object_id] = (int(size), content_issues(git(root, "cat-file", "blob", object_id)))
    # The same blob can appear under several names. rev-list's one name per object
    # is insufficient to catch a later rename into a game/archive path.
    versions = set()
    for commit in git(root, "rev-list", "--all").decode().splitlines():
        for entry in git(root, "ls-tree", "-rz", commit).split(b"\0"):
            if not entry:
                continue
            header, raw_name = entry.split(b"\t", 1)
            mode, kind, object_id = header.decode().split(" ")
            name = raw_name.decode()
            if kind == "blob":
                versions.add((name, object_id, mode))
    for name, object_id, mode in sorted(versions):
        size, content = content_by_object[object_id]
        issues = path_issues(name) + content
        if mode == "120000":
            issues.append("symlink-not-allowed")
        # Old machine paths do not require rewriting private checkpoint history.
        if "personal-absolute-path" in issues:
            warnings.append({"object": object_id, "path": name, "issue": "historical-personal-path"})
            issues = [issue for issue in issues if issue != "personal-absolute-path"]
        if issues:
            findings.append({"object": object_id, "path": name, "bytes": size, "issues": sorted(set(issues))})
    return {"blobs": count, "findings": findings, "warnings": warnings, "passed": not findings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--history", action="store_true", help="Inspect every reachable Git blob, in addition to current source")
    parser.add_argument("--report", type=Path, help="Write JSON report; matches never include secret contents")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    report = {"schema": 1, "current": current_report(root)}
    if args.history:
        report["history"] = history_report(root)
    report["passed"] = all(section["passed"] for section in report.values() if isinstance(section, dict))
    encoded = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(encoded)
        print(json.dumps({"passed": report["passed"], "current_files": report["current"]["files"],
                          "current_findings": len(report["current"]["findings"]),
                          "history_findings": len(report.get("history", {}).get("findings", [])),
                          "history_path_warnings": len(report.get("history", {}).get("warnings", []))}))
    else:
        print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
