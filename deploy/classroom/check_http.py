"""Unauthenticated route and public-asset probes; no credentials or business writes."""
import urllib.request
import urllib.error
import os
from urllib.parse import urlparse


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)
paths = {
    "/tongjianyun-classroom": {301, 302, 303},
    "/assets/tongjianyun/classroom/app.js": {200},
    "/assets/tongjianyun/classroom/scene.js": {200},
    "/assets/tongjianyun/classroom/state.js": {200},
    "/assets/tongjianyun/classroom/objects.js": {200},
    "/assets/tongjianyun/classroom/scene-workbench.css": {200},
    "/assets/tongjianyun/classroom/classroom.css": {200},
    "/api/method/tongjianyun.classroom.get_overview": {401, 403},
}
for path, expected in paths.items():
    request = urllib.request.Request(os.environ.get("CLASSROOM_TEST_BASE", "http://127.0.0.1:17081") + path,
        headers={"Host": "child.myyr.top", "User-Agent": "Tongjianyun-Classroom-ReadOnly-Check/1.0"})
    try:
        response = opener.open(request, timeout=35)
        status = response.status
        content_type = response.headers.get("Content-Type", "")
        response.close()
        if path.endswith((".js", ".mjs")):
            assert "javascript" in content_type, (path, "Module MIME mismatch", content_type)
    except urllib.error.HTTPError as exc:
        status = exc.code
        if path == "/tongjianyun-classroom":
            assert urlparse(exc.headers.get("Location", "")).path == "/login", "Guest page must redirect to login"
    print(status, path)
    assert status in expected, (path, status)
print("PASS: guest redirected, public assets served, unauthenticated data API denied")
