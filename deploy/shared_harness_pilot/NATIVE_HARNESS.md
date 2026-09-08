# Native Harness entry

The public root and employee SSO redirect to `/native/`. The page uses the fork's original web build and plugin UI (including its existing `ione harness` branding), not the former custom chat page.

`native-transport.js` uses Harness's external Client transport contract. Sessions remain account-owned through the employee API. The displayed workspace is a presentation-only group, not a filesystem workspace. `/native/view` checks account ownership before and after reading a bounded snapshot; no general Host RPC or global event stream is exposed.

The base `ui-settings` service is enabled for native locale/theme dependencies. Host settings management remains disabled. Shared-entry text conversations and owned history are supported; filesystem management, attachments, arbitrary Host operations, queue/steering controls remain unavailable. Business mutations retain the independent Tongjianyun preview/confirmation flow through the “业务确认” link. The old `/employee/chat/` remains available for that confirmation flow.

Session rename and cancellation use `/native/command`. It accepts only those two commands, validates their exact fields and checks current account ownership before calling the native Session Controller. It rechecks access before returning a result; a revoked-login error after a command does not imply rollback. No generic service or method forwarding is available.

Validation: `node --test deploy/shared_harness_pilot/test_native_ui.mjs deploy/shared_harness_pilot/test_native_commands.mjs`; run `accept_native_ui.py` with Bench Python for a signed, credential-redacted Chromium check; run `accept_entry_redirect.py` for public redirects. Browser acceptance creates a Harness conversation, asks for a fixed text response, renames the conversation and checks cancellation acknowledgement without querying or changing business data.

Full-role rollout is incomplete: server-global settings, arbitrary plugins, filesystem and shell require separately enforced isolation before enabling them in the shared entry. These session commands do not grant Administrator Host access or enable ordinary-user business writes.

`accept_native_commands.py` checks both Administrator and the admitted ordinary account, rejects commands on each other's sessions, and cancels a live ordinary-account model response. It creates only Harness test sessions and logs no credentials or business values.

Deployment: the service loads `administrator-runtime.yml`; copy the checked `live-nginx.conf` to `/home/zyd/frappe/config/harness/nginx.conf`, then reload that nginx instance. To roll back the entry only, change the root and both SSO redirects to `/employee/chat/`; leave account authorization in place. No DocType or database schema change is required.
