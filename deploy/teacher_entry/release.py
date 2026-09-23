"""Release only listed teacher-entry files after detecting concurrent changes.

No schemas, role grants, user assignments or database migrations. Run from
native-bench with an isolated --source and a code-only --baseline archive.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

FILES = (
    "tongjianyun/workspace_entry.py", "tongjianyun/classroom.py", "tongjianyun/hooks.py",
    "tongjianyun/www/tongjianyun_entry.py", "tongjianyun/www/tongjianyun-entry.html",
    "tongjianyun/www/tongjianyun_classroom.py", "tongjianyun/www/tongjianyun-classroom.html",
    "tongjianyun/public/entry/entry.css", "tongjianyun/public/classroom/app.js",
    "tongjianyun/public/classroom/refined.css", "tongjianyun/public/js/page_cache_buster.js",
    "tongjianyun/tests/test_workspace_entry.py", "deploy/classroom/check_browser.cjs",
    "deploy/teacher_entry/check_accounts.py", "deploy/teacher_entry/check_regression.py",
    "deploy/teacher_entry/make_browser_fixtures.py", "deploy/teacher_entry/check_browser.cjs",
    "deploy/teacher_entry/check_http.py", "deploy/teacher_entry/check_live.py",
    "deploy/teacher_entry/release.py", "docs/CLASSROOM_WORKBENCH.md",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,required=True)
    args=parser.parse_args()
    source=args.source.resolve()
    target=(Path.cwd()/"apps/tongjianyun").resolve()
    assert Path.cwd().name=="native-bench" and (Path.cwd()/"sites").is_dir()
    assert source!=target and Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],cwd=target,text=True).strip()).resolve()==target
    with tarfile.open(args.baseline,"r:gz") as archive:
        baseline={m.name.removeprefix("./"):archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
    old,new={},{}
    for relative in FILES:
        src,dst=source/relative,target/relative
        assert src.is_file() and src.resolve().is_relative_to(source) and dst.resolve().is_relative_to(target)
        old[relative]=dst.read_bytes() if dst.exists() else None
        new[relative]=src.read_bytes()
        if old[relative] not in (baseline.get(relative),new[relative]):
            raise RuntimeError("Concurrent change detected: "+relative)
    written=[]
    try:
        for relative in FILES:
            dst=target/relative
            dst.parent.mkdir(parents=True,exist_ok=True)
            temp=dst.with_name(dst.name+".teacher-release.tmp")
            temp.write_bytes(new[relative]);os.replace(temp,dst);written.append(relative)
    except Exception:
        for relative in reversed(written):
            dst=target/relative
            if old[relative] is None: dst.unlink(missing_ok=True)
            else: dst.write_bytes(old[relative])
        raise
    print(json.dumps({"deployed":len(written),"schema_changes":False,"role_changes":False,
        "sha256":{r:hashlib.sha256(new[r]).hexdigest() for r in FILES}},ensure_ascii=False))


if __name__=="__main__": main()
