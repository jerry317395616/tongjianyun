"""Native authenticated proposal handoff endpoints, never agent tools.

Frappe authenticates and validates session POST CSRF before invoking whitelisted
methods. This module does not bypass/replace that middleware, accept credentials,
choose an actor/site, or run a model. GET is read-only; all named-recipient and
acceptance actions use POST. The captured live Viewer is the only browser actor.

Accepting copies the fixed proposal into the recipient's original private File.
It never calls blueprint.activate, creates a DocType, changes roles or retries
an uncertain copy. Original activation remains a separate authorized action.
"""
import frappe

from tongjianyun.business_agent_service import application
from tongjianyun.business_agent_proposals import BusinessProposals, ProposalConflict, _id, _owner, _revision
from tongjianyun.workspace_entry import require_account, mark_private_response

PERMISSION_MESSAGE = '当前账号或会话无权访问这项方案交接。'
INPUT_MESSAGE = '交接参数或版本无效，请重新读取方案后核对。'
UNAVAILABLE_MESSAGE = '交接结果暂无法确认，请重新查询记录；不要自动重复提交或接受。'


def _page_size(value):
    # Native GET form values are strings; reject booleans, fractions and signs.
    if type(value) is str and 1 <= len(value) <= 2 and value.isascii() and value.isdecimal() and str(int(value)) == value:
        value = int(value)
    if type(value) is not int or not 1 <= value <= 20:
        raise ValueError('Invalid page size')
    return value


def _invoke(method, fields, action, *, mutation=False):
    try:
        mark_private_response()
        require_account()
        # Native whitelist already restricts the method. This second finite
        # check also rejects internal dispatcher/HTTP argument filtering tricks.
        request = getattr(frappe.local, 'request', None)
        if request is None or request.method != method:
            raise PermissionError('Wrong native HTTP method')
        payload = getattr(frappe, 'form_dict', {})
        if set(payload) - (set(fields) | {'cmd', 'csrf_token', '_'}):
            raise ValueError('Unexpected proposal request fields')
        if method == 'POST':
            session_data = getattr(getattr(frappe, 'session', None), 'data', None)
            saved_csrf = session_data.get('csrf_token') if isinstance(session_data, dict) else None
            # Native Frappe may skip CSRF comparison for a session that has no
            # saved token. Do not admit this privileged transfer in that case;
            # reload the authenticated page to obtain a normal native session.
            # The actual incoming-token comparison remains native middleware.
            if (getattr(frappe.conf, 'ignore_csrf', False)
                    or not isinstance(saved_csrf, str) or not 1 <= len(saved_csrf) <= 256):
                raise PermissionError('Proposal actions require native CSRF protection')
        app, _ = application(require_ready=False)
        if not isinstance(app.proposals, BusinessProposals):
            raise PermissionError('The private proposal adapter is unavailable')
        viewer = app.viewer()  # Native authenticated session, not JSON identity.
        return action(app.proposals, viewer)
    except (PermissionError, frappe.PermissionError):
        if mutation:
            frappe.local.response['proposal_retry_allowed'] = False
        raise frappe.PermissionError(PERMISSION_MESSAGE) from None
    except (ProposalConflict, ValueError, TypeError):
        if mutation:
            frappe.local.response['proposal_retry_allowed'] = False
        raise frappe.ValidationError(INPUT_MESSAGE) from None
    except Exception:
        if mutation:
            frappe.local.response['proposal_retry_allowed'] = False
            frappe.local.response['proposal_result_unconfirmed'] = True
        # No raw SQL, File paths, account lookup details, stacks or credentials.
        raise frappe.ValidationError(UNAVAILABLE_MESSAGE) from None


@frappe.whitelist(methods=['POST'])
def check_recipient(proposal_id, revision, recipient):
    return _invoke('POST', {'proposal_id', 'revision', 'recipient'},
        lambda proposals, viewer: proposals.check_recipient(viewer, _id(proposal_id), _revision(revision), _owner(recipient)))


@frappe.whitelist(methods=['POST'])
def handoff(proposal_id, revision, recipient):
    return _invoke('POST', {'proposal_id', 'revision', 'recipient'},
        lambda proposals, viewer: proposals.handoff(viewer, _id(proposal_id), _revision(revision), _owner(recipient)), mutation=True)


@frappe.whitelist(methods=['GET'])
def list_sent(cursor=None, page_size=10):
    return _invoke('GET', {'cursor', 'page_size'}, lambda proposals, viewer:
        proposals.list_sent(viewer, cursor=_id(cursor) if cursor is not None else None, size=_page_size(page_size)))


@frappe.whitelist(methods=['GET'])
def list_received(cursor=None, page_size=10, state='pending'):
    return _invoke('GET', {'cursor', 'page_size', 'state'}, lambda proposals, viewer:
        proposals.list_received(viewer, cursor=_id(cursor) if cursor is not None else None,
                                size=_page_size(page_size), state=state))


@frappe.whitelist(methods=['GET'])
def preview_handoff(handoff_id):
    return _invoke('GET', {'handoff_id'}, lambda proposals, viewer: proposals.preview_handoff(viewer, _id(handoff_id)))


@frappe.whitelist(methods=['POST'])
def accept_handoff(handoff_id):
    return _invoke('POST', {'handoff_id'}, lambda proposals, viewer: proposals.accept_handoff(viewer, _id(handoff_id)), mutation=True)
