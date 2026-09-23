"""Deploy this UI release without migrations or overwriting concurrent changes.

Run from the bench with --source pointing to the verified isolated staging tree
and --baseline pointing to the pre-change source archive. Does not restart any
service; refresh_runtime.py is a separate, explicit step after verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

FILES = (
    "tongjianyun/www/tongjianyun-classroom.html",
    "tongjianyun/public/classroom/app.js",
    "tongjianyun/public/classroom/scene.js",
    "tongjianyun/public/classroom/visual-kit.js",
    "tongjianyun/public/classroom/visual-layout.js",
    "tongjianyun/public/classroom/characters.js",
    "tongjianyun/public/classroom/room.js",
    "tongjianyun/public/classroom/refined.css",
    "tongjianyun/public/classroom/objects.js",
    "tongjianyun/public/classroom/scene-workbench.css",
    "tongjianyun/tests/test_classroom_objects.mjs",
    "tongjianyun/tests/test_classroom_visuals.mjs",
    "deploy/classroom/check_browser.cjs",
    "deploy/classroom/check_http.py",
    "deploy/classroom/deploy_scene_release.py",
    "docs/CLASSROOM_WORKBENCH.md",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    target = Path.cwd() / "apps/tongjianyun"
    if not (Path.cwd() / "sites").is_dir() or not target.is_dir():
        parser.error("Run from the existing native bench")
    source, target = args.source.resolve(), target.resolve()
    git_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=target, text=True).strip()
    if Path(git_root).resolve() != target or source == target:
        parser.error("Expected isolated source and the Tongjianyun Git root")
    with tarfile.open(args.baseline, "r:gz") as archive:
        baseline = {m.name.removeprefix("./"): archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
    previous, wanted = {}, {}
    for relative in FILES:
        src, dst = source / relative, target / relative
        if not src.is_file() or not dst.resolve().is_relative_to(target):
            raise RuntimeError("Invalid release path: " + relative)
        wanted[relative] = src.read_bytes()
        previous[relative] = dst.read_bytes() if dst.exists() else None
        if previous[relative] not in (baseline.get(relative), wanted[relative]):
            raise RuntimeError("Concurrent change detected; stop without overwriting: " + relative)
    written = []
    try:
        for relative in FILES:
            dst = target / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            temporary = dst.with_name(dst.name + ".scene-release.tmp")
            temporary.write_bytes(wanted[relative])
            os.replace(temporary, dst)
            written.append(relative)
    except Exception:
        for relative in reversed(written):
            dst = target / relative
            if previous[relative] is None:
                dst.unlink(missing_ok=True)
            else:
                dst.write_bytes(previous[relative])
        raise
    print(json.dumps({"deployed": len(written), "schema_changes": False,
        "files": {name: hashlib.sha256(wanted[name]).hexdigest() for name in FILES}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
