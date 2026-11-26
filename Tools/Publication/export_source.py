#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Export a validated current source snapshot without Git history or game assets."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from audit_repository import current_report, git, source_paths


def export_source(root: Path, output: Path) -> dict:
    report = current_report(root)
    if not report["passed"]:
        raise ValueError("Source publication audit failed: " + json.dumps(report["findings"]))
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace an existing export")
    # An exported snapshot can become a new repository. Replace its provenance
    # record instead of archiving two entries with the same manifest path.
    paths = [name for name in source_paths(root) if name != "SOURCE-MANIFEST.json"]
    files = [(name, (root / name).read_bytes()) for name in paths]
    # Revalidate the bytes copied, rather than trusting an earlier mutable-tree scan.
    from audit_repository import content_issues
    for name, data in files:
        if (root / name).is_symlink() or content_issues(data):
            raise ValueError("Source changed while preparing export: " + name)
    manifest = {"schema": 1, "kind": "game-data-free-source-snapshot",
                "source_commit": git(root, "rev-parse", "HEAD").decode().strip(),
                "working_tree_changes": bool(git(root, "status", "--porcelain")),
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files},
                "note": "Contains current source only; original games, generated assets and Git history are excluded."}
    files.append(("SOURCE-MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode()))
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = output.open("xb")
    try:
        with raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as bundle:
            for name, data in files:
                member = tarfile.TarInfo("ScreamerTrilogy/" + name)
                member.size, member.mode, member.mtime = len(data), 0o644, 0
                bundle.addfile(member, io.BytesIO(data))
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {"source_files": len(paths), "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "source_commit": manifest["source_commit"], "working_tree_changes": manifest["working_tree_changes"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True, help="Fresh .tar.gz path outside the source tree")
    args = parser.parse_args()
    root, output = args.root.expanduser().resolve(), args.output.expanduser().absolute()
    if output.is_relative_to(root):
        parser.error("Write exports outside the repository")
    try:
        result = export_source(root, output)
    except (ValueError, FileExistsError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
