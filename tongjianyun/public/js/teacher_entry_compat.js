/* Support in-Desk navigation from an old cached icon as well as bookmarked URLs.
 * The server determines eligible profiles. No role is added or assumed here.
 */
(() => {
  const legacy = '/desk/tongjianyun-workbench';
  let pending = false, attached = false, attempts = 0;
  async function checkEntry() {
    if (pending || window.location.pathname.replace(/\/$/, '') !== legacy) return;
    const user = window.frappe?.session?.user;
    if (!user || user === 'Guest') return;
    pending = true;
    try {
      const response = await fetch('/api/method/tongjianyun.workspace_entry.get_options', {
        method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'},
      });
      if (!response.ok) return;
      const body = await response.json();
      const profiles = body.message?.profiles || [];
      const teacherOnly = profiles.some(p => p.id === 'teacher') &&
        !profiles.some(p => p.id === 'business' && p.enabled);
      // A response from an earlier route/account must not redirect the new one.
      if (teacherOnly && window.frappe?.session?.user === user &&
          window.location.pathname.replace(/\/$/, '') === legacy) {
        window.location.replace('/tongjianyun-entry');
      }
    } catch (_) {
      // Preserve the original page on network/authentication failure. No writes.
    } finally { pending = false; }
  }
  function install() {
    if (!attached && window.frappe?.router?.on) {
      attached = true;
      window.frappe.router.on('change', checkEntry);
    }
    checkEntry();
    if (!attached && ++attempts < 20) setTimeout(install, 500);
  }
  window.addEventListener('popstate', checkEntry);
  window.addEventListener('load', install, {once: true});
  if (document.readyState !== 'loading') install();
  else document.addEventListener('DOMContentLoaded', install, {once: true});
})();
