"""Check public entry redirects without credentials or business-data access."""
import json
import subprocess
from urllib.parse import urljoin, urlsplit


ORIGIN = "https://harness.myyr.top"


def valid_redirect(location):
    target = urlsplit(urljoin(ORIGIN + "/", location))
    return (target.scheme, target.netloc, target.path) == (
        "https", "harness.myyr.top", "/native/"
    ) and not target.query and not target.fragment


def main():
    assert valid_redirect("/native/")
    assert not valid_redirect("http://harness.myyr.top:13091/employee/chat/")
    checks = []
    for path, expected in [("/", 302), ("/employee/chat/", 200),
                           ("/employee/chat/chat.mjs", 200),
                           ("/employee/chat/client.mjs", 200),
                           ("/employee/chat/chat.css", 200)]:
        raw = subprocess.check_output([
            "curl", "--silent", "--show-error", "--max-time", "30",
            "--dump-header", "-", "--output", "/dev/null",
            "--write-out", "%{http_code}", ORIGIN + path,
        ], text=True, timeout=35)
        status = int(raw.splitlines()[-1])
        assert status == expected, (path, status)
        if expected == 302:
            locations = [line.split(":", 1)[1].strip() for line in raw.splitlines()
                         if line.lower().startswith("location:")]
            assert len(locations) == 1 and valid_redirect(locations[0]), "unsafe entry redirect"
        checks.append({"path": path, "status": status})
    print(json.dumps({"passed": True, "checks": checks}))


if __name__ == "__main__":
    main()
