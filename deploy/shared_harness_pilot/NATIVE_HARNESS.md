# Native Harness entry

The public root and employee SSO redirect to `/native/`. The page uses the fork's original web build and plugin UI (including its existing `ione harness` branding), not the former custom chat page.

`native-transport.js` uses Harness's external Client transport contract. Sessions remain account-owned through the employee API. The displayed workspace is a presentation-only group, not a filesystem workspace. `/native/view` checks account ownership before and after reading a bounded snapshot; no general Host RPC or global event stream is exposed.

The base `ui-settings` service is enabled for native locale/theme dependencies. Host settings management remains disabled. Shared-entry text conversations and owned history are supported; filesystem management, attachments, arbitrary Host operations, queue/steering controls remain unavailable. Business mutations retain the independent Tongjianyun preview/confirmation flow through the “业务确认” link. The old `/employee/chat/` remains available for that confirmation flow.

Validation: `node --test deploy/shared_harness_pilot/test_native_ui.mjs`; run `accept_native_ui.py` with Bench Python for a signed, credential-redacted Chromium check; run `accept_entry_redirect.py` for public redirects. Browser acceptance creates a Harness conversation and asks for a fixed text response without querying or changing business data.

Deployment: the service loads `administrator-runtime.yml`; copy the checked `live-nginx.conf` to `/home/zyd/frappe/config/harness/nginx.conf`, then reload that nginx instance. To roll back the entry only, change the root and both SSO redirects to `/employee/chat/`; leave account authorization in place. No DocType or database schema change is required.
