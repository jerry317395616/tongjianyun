# Native Harness entry

The public root and employee SSO redirect to `/native/`. The page uses the fork's original web build and plugin UI (including its existing `ione harness` branding), not the former custom chat page.

`native-transport.js` uses Harness's external Client transport contract. Sessions remain account-owned through the employee API. The displayed workspace is a presentation-only group, not a filesystem workspace. `/native/view` checks account ownership before and after reading a bounded snapshot; no general Host RPC or global event stream is exposed.

The base `ui-settings` service is enabled for native locale/theme dependencies. Host settings management remains disabled. Shared-entry text conversations and owned history are supported; filesystem management, attachments, arbitrary Host operations, queue/steering controls remain unavailable. Business mutations retain the independent Tongjianyun preview/confirmation flow through the “业务确认” link. The old `/employee/chat/` remains available for that confirmation flow.

The native model selector and its command-UI dependency are enabled. Authenticated users can read `/native/models`; upstream diagnostic messages are redacted. `/native/model-selection` resolves the existing signed cookie through the private identity authority and requires the exact child-site Administrator principal plus owned-session access. Only catalog-listed models are accepted. It calls the native Session Controller, which also saves the global default model; ordinary users therefore cannot invoke this operation. General settings, provider credentials and plugin management are not exposed. `commands/list` intentionally returns no Host commands; the local model-selector contribution is available without granting command execution.

`accept_native_models.py` checks administrator selection of the existing model, ordinary-user denial and cross-account denial without changing the configured provider/model. `test_native_models.mjs` covers parser, identity, revocation and configured-model checks. These checks do not claim support for arbitrary providers or missing provider credentials.

Session rename and cancellation use `/native/command`. It accepts only those two commands, validates their exact fields and checks current account ownership before calling the native Session Controller. It rechecks access before returning a result; a revoked-login error after a command does not imply rollback. No generic service or method forwarding is available.

Validation: `node --test deploy/shared_harness_pilot/test_native_ui.mjs deploy/shared_harness_pilot/test_native_commands.mjs`; run `accept_native_ui.py` with Bench Python for a signed, credential-redacted Chromium check; run `accept_entry_redirect.py` for public redirects. Browser acceptance creates a Harness conversation, asks for a fixed text response, renames the conversation and checks cancellation acknowledgement without querying or changing business data.

Full-role rollout is incomplete: server-global settings, arbitrary plugins, filesystem and shell require separately enforced isolation before enabling them in the shared entry. These session commands do not grant Administrator Host access or enable ordinary-user business writes.

Image preparation: `/native/attachment` now bridges `session/attachment` reads only. Exact session/digest inputs, same-origin POST, current account ownership before and after the read, and the native controller's session-reference check are all required. Responses over 1 MB are rejected; shared attachment-store paths are never accepted. This is backend preparation, not an enabled upload feature: the attachment UI and image prompts remain disabled until bounded upload admission and model compatibility are verified. Run `node --test deploy/shared_harness_pilot/test_native_attachments.mjs` for ownership, revocation, malformed requests, cancellation and size-limit checks.

`accept_native_commands.py` checks both Administrator and the admitted ordinary account, rejects commands on each other's sessions, and cancels a live ordinary-account model response. It creates only Harness test sessions and logs no credentials or business values.

Deployment: the service loads `administrator-runtime.yml`; copy the checked `live-nginx.conf` to `/home/zyd/frappe/config/harness/nginx.conf`, then reload that nginx instance. To roll back the entry only, change the root and both SSO redirects to `/employee/chat/`; leave account authorization in place. No DocType or database schema change is required.
