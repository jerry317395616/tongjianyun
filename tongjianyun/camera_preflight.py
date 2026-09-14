"""Read-only Hikvision commissioning probe. No public endpoint or attendance writes."""
from urllib.parse import urlsplit
import ipaddress
import requests
from requests.auth import HTTPDigestAuth
from xml.etree.ElementTree import fromstring

MAX_XML = 256 * 1024
PATHS = {
    "device": "/ISAPI/System/deviceInfo",
    "capabilities": "/ISAPI/System/capabilities",
    "clock": "/ISAPI/System/time",
}


def validate_endpoint(endpoint):
    """Operator supplies a literal private/VPN address, never an event-provided URL."""
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Use a camera HTTPS origin without credentials or path")
    address = ipaddress.ip_address(parsed.hostname or "")
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        raise ValueError("Use the configured private/VPN camera address")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid port")
    return endpoint.rstrip("/")


def parse_xml(payload):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_XML:
        raise ValueError("Invalid XML size")
    text = payload.decode("utf-8-sig")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD and entities are not allowed")
    return fromstring(text)


def probe(endpoint, username, password, *, ca_bundle=True):
    """Credentials remain in memory. Trust a provisioned certificate; never verify=False."""
    endpoint = validate_endpoint(endpoint)
    if ca_bundle is False or not ca_bundle:
        raise ValueError("Certificate verification is required")
    result = {"mode": "read-only", "checks": {}, "attendance_enabled": False}
    with requests.Session() as session:
        session.trust_env = False
        session.auth = HTTPDigestAuth(username, password)
        for key, path in PATHS.items():
            try:
                with session.get(endpoint + path, timeout=(5, 10), stream=True,
                                 verify=ca_bundle, allow_redirects=False) as response:
                    if response.status_code != 200:
                        result["checks"][key] = {"ok": False, "http_status": response.status_code}
                        continue
                    payload = bytearray()
                    for chunk in response.iter_content(8192):
                        payload.extend(chunk)
                        if len(payload) > MAX_XML:
                            raise ValueError("Response too large")
                    root = parse_xml(bytes(payload))
                    # No serial number, credentials, faces or raw response in output.
                    values = {node.tag.split("}")[-1]: node.text for node in root.iter()}
                    allowed = {"device": ("model", "firmwareVersion"),
                               "clock": ("localTime", "timeZone"), "capabilities": ()}[key]
                    result["checks"][key] = {"ok": True, **{k: values.get(k) for k in allowed}}
            except requests.exceptions.SSLError:
                result["checks"][key] = {"ok": False, "error": "certificate_untrusted"}
            except requests.exceptions.RequestException:
                result["checks"][key] = {"ok": False, "error": "connection_failed"}
            except Exception:
                result["checks"][key] = {"ok": False, "error": "invalid_response"}
    return result
