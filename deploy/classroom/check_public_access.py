"""Compare anonymous public entry responses without credentials or policy changes.

Only status, infrastructure response markers and a short page title are printed.
This is not an authenticated public end-to-end acceptance test.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)
paths = ["/login", "/desk/tongjianyun-workbench", "/tongjianyun-campus", "/tongjianyun-classroom", "/assets/tongjianyun/classroom/app.js"]
for path in paths:
    request = urllib.request.Request("https://child.myyr.top" + path, headers={"User-Agent": "Tongjianyun-Classroom-ReadOnly-Check/1.0", "Accept": "text/html,application/javascript"})
    try:
        response = opener.open(request, timeout=25)
    except urllib.error.HTTPError as error:
        response = error
    except Exception as error:
        print(json.dumps({"path": path, "error_type": type(error).__name__}))
        continue
    with response:
        status = response.code
        content = response.read(24000).decode("utf-8", errors="replace")
        title = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
        result = {"path": path, "status": status, "server": response.headers.get("Server"),
                  "content_type": response.headers.get("Content-Type"),
                  "location_path": urlparse(response.headers.get("Location", "")).path or None,
                  "cf_mitigated": response.headers.get("cf-mitigated"),
                  "page_title": re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else None,
                  "cloudflare_markers": "cloudflare" in content.lower(),
                  "challenge_markers": any(x in content.lower() for x in ("cf-chl", "challenge-platform", "just a moment"))}
        print(json.dumps(result, ensure_ascii=False))
