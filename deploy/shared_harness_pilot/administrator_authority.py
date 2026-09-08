"""Tongjianyun Administrator read adapter for the existing shared Harness.

Ordinary accounts retain the upstream pinned-identity executor and read scope.
Administrator shares the signed login, cookie lifecycle and peer-UID checks,
but uses a fixed Tongjianyun worker. Confirmation is a separate browser action.
"""
import argparse
import asyncio
from dataclasses import replace
import json
import hashlib
import re
from pathlib import Path
import signal
import sys

BENCH = Path("/home/zyd/frappe/native-bench")
HELPERS = Path("/home/zyd/frappe/deepseek-harness/packages/extensions/tool-native-bench-frappe/python")
sys.path.insert(0, str(HELPERS))
from employee_read_broker import bounded_process, strict_json
from shared_identity import Configuration, SharedIdentity, IdentityServer, NativeEnabledCheck, NativeRead, READ_FIELDS


async def administrator_worker(operation, arguments, timeout):
    payload = json.dumps({"operation": operation, "arguments": arguments}, allow_nan=False).encode()
    if len(payload) > 8192:
        raise ValueError("request exceeds limit")
    result = await bounded_process(
        [str(BENCH / "env/bin/python"), "-s", "-B", str(Path(__file__).with_name("administrator_worker.py"))],
        payload, cwd=BENCH, timeout=timeout, output_limit=262144,
    )
    return strict_json(result)


class AdministratorAuthority(SharedIdentity):
    """Extend verified logins, never infer Administrator from request arguments."""

    def __init__(self, config, *, worker=administrator_worker, enabled=None, read=None, **kwargs):
        if config.issuer != "child.myyr.top" or "Administrator" in config.identities:
            raise ValueError("invalid administrator authority deployment")
        self.worker = worker
        ordinary_enabled = enabled or NativeEnabledCheck(config)
        ordinary_read = read or NativeRead(config)

        async def check(user):
            if user == "Administrator":
                return await worker("check", {}, config.timeout_seconds) == {"enabled": True}
            return await ordinary_enabled(user)

        # This marker admits signed Administrator tickets only; it is never
        # passed into the employee assertion loader or employee query executor.
        extended = replace(config, identities={**config.identities, "Administrator": None})
        super().__init__(extended, check, read=ordinary_read, **kwargs)

    async def execute(self, request):
        if (not isinstance(request, dict) or set(request) != {"version", "operation", "value"}
                or type(request["version"]) is not int or request["version"] != 1):
            raise ValueError("invalid request")
        if request["operation"] == "application":
            return await self.application(request["value"])
        if request["operation"] != "read":
            return await super().execute(request)
        value = request["value"]
        if (not isinstance(value, dict) or set(value) != {"credential", "operation", "arguments"}
                or not isinstance(value["operation"], str) or value["operation"] not in READ_FIELDS
                or not isinstance(value["arguments"], dict)
                or set(value["arguments"]) - READ_FIELDS[value["operation"]]):
            raise ValueError("invalid read")
        principal = await self.resolve(value["credential"])
        if principal is None:
            raise PermissionError("login unavailable")
        if principal["user"] != "Administrator":
            return await super().execute(request)
        if "Administrator" in self.readers:
            raise ValueError("read already running")
        self.readers.add("Administrator")
        try:
            result = await self.worker(value["operation"], value["arguments"], self.config.timeout_seconds)
            if await self.resolve(value["credential"]) != principal:
                raise PermissionError("login revoked during read")
            return result
        finally:
            self.readers.remove("Administrator")

    async def application(self, value):
        """Admit only authenticated Administrator actions; bind plans to this login and chat."""
        if (not isinstance(value, dict)
                or set(value) != {"credential", "sessionId", "action", "arguments"}
                or not isinstance(value["sessionId"], str)
                or not re.fullmatch(r"session-[0-9a-f-]{36}", value["sessionId"])
                or value["action"] not in {"capabilities", "preview", "review", "confirm"}
                or not isinstance(value["arguments"], dict)):
            raise ValueError("invalid application request")
        principal = await self.resolve(value["credential"])
        if principal is None:
            raise PermissionError("login unavailable")
        if principal["user"] != "Administrator":
            if value["action"] == "capabilities" and value["arguments"] == {}:
                return {"previews": False}
            raise PermissionError("application action unavailable")
        binding = hashlib.sha256(json.dumps([value["credential"], value["sessionId"]]).encode()).hexdigest()
        result = await self.worker("application", {"session_hash": binding,
            "action": value["action"], "arguments": value["arguments"]}, self.config.timeout_seconds)
        if await self.resolve(value["credential"]) != principal:
            raise PermissionError("login revoked during application action")
        return result


async def serve(authority):
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    try:
        async with IdentityServer(authority).listening():
            print("shared authority with administrator reads ready", flush=True)
            await stopped.wait()
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        authority = AdministratorAuthority(Configuration.load(args.config))
        if not args.check:
            asyncio.run(serve(authority))
        return 0
    except Exception:
        print("shared authority unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
