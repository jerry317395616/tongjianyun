"""Actual unauthenticated entry/asset probes, no credentials or business writes."""
import os
import urllib.request
import urllib.error
from urllib.parse import urlparse, parse_qs


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)
base = os.environ.get("CLASSROOM_TEST_BASE", "http://127.0.0.1:17081")
paths = {
    "/tongjianyun-entry": {303},
    "/tongjianyun-entry?profile=teacher&class=FORGED": {303},
    "/assets/tongjianyun/entry/entry.css": {200},
    "/assets/tongjianyun/classroom/app.js": {200},
    "/api/method/tongjianyun.workspace_entry.get_options": {401,403},
    "/api/method/tongjianyun.classroom.get_overview?workspace=teacher": {401,403},
    "/api/method/tongjianyun.classroom.get_meals?workspace=teacher&student_group=FORGED&day=2026-09-23": {401,403},
}
for path, expected in paths.items():
    request = urllib.request.Request(base+path, headers={"Host":"child.myyr.top","User-Agent":"Tongjianyun-Teacher-Entry-ReadOnly-Check/1.0"})
    try:
        response = opener.open(request, timeout=35)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        code = response.code
        assert code in expected, (path, code)
        if path.startswith("/tongjianyun-entry"):
            location = urlparse(response.headers.get("Location", ""))
            assert location.path == "/login"
            assert parse_qs(location.query).get("redirect-to") == ["/tongjianyun-entry"]
            assert "no-store" in response.headers.get("Cache-Control", ""), "Personal entry must not be cached"
        if path.endswith(".js"):
            assert "javascript" in response.headers.get("Content-Type", "")
        print(code, path)
print("PASS: temporary private login return, entry CSS/JS served, anonymous teacher data denied")
