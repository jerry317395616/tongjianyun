"""Ordinary-business HTTP entry: native login/CSRF, independent tasks and SSE."""
import uuid

import frappe
from werkzeug.wrappers import Response

from tongjianyun.business_agent_service import application
from tongjianyun.business_agent_tasks import _uuid, _selection
from tongjianyun.business_agent_transport import strict_json
from tongjianyun.workspace_entry import require_account, mark_private_response


def _request(*, require_ready=False):
    require_account()
    mark_private_response()
    try:
        app, _ = application(require_ready=require_ready)
        return app, app.viewer()
    except Exception:
        raise frappe.PermissionError('业务对话当前不可用，请核对账号或联系管理员。') from None


def _call(action):
    try:
        return action()
    except (PermissionError, frappe.PermissionError):
        raise frappe.PermissionError('当前账号或会话无权访问这项任务。') from None
    except (ValueError, TypeError):
        raise frappe.ValidationError('请求内容或进度位置无效，请刷新页面后核对。') from None


def _context(day, meal, view_context):
    from tongjianyun.meal_scene import business_day, meal_key
    context = {'day': str(business_day(day)), 'meal': meal_key(meal)}
    if view_context is not None:
        if isinstance(view_context, str):
            if len(view_context.encode()) > 8192:
                raise ValueError('View context too large')
            view_context = strict_json(view_context)
        context['selection'] = _selection(view_context)
    return context


@frappe.whitelist(methods=['POST'])
def send_message(message='', day=None, meal='lunch', file_name=None, request_id=None, stream=0, view_context=None):
    app, viewer = _request(require_ready=True)
    if str(stream) != '1':
        raise frappe.ValidationError('请刷新页面后使用流式业务对话。')
    if file_name is not None:
        raise frappe.ValidationError('业务对话的文件处理尚未接通，本次没有接收或处理附件。')
    def submit():
        task_id = _uuid(request_id) if request_id is not None else str(uuid.uuid4())
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 8000:
            raise ValueError('Invalid message')
        return app.submit(viewer, task_id, message, _context(day, meal, view_context))
    return _call(submit)


@frappe.whitelist(methods=['POST'])
def retry_dispatch(task_id):
    app, viewer = _request(require_ready=True)
    return _call(lambda: app.retry_dispatch(viewer, _uuid(task_id)))


@frappe.whitelist(methods=['GET'])
def get_conversation(before=None):
    app, viewer = _request()
    return _call(lambda: app.conversation(viewer, before))


@frappe.whitelist(methods=['GET'])
def get_events(task_id, after='0'):
    app, viewer = _request()
    return _call(lambda: app.event_page(viewer, _uuid(task_id), after))


@frappe.whitelist(methods=['POST'])
def cancel_task(task_id):
    app, viewer = _request()
    return _call(lambda: app.cancel(viewer, _uuid(task_id)))


@frappe.whitelist(methods=['GET'])
def stream_events(task_id, after='0'):
    app, viewer = _request()
    cursor = frappe.get_request_header('Last-Event-ID') or after
    generator = _call(lambda: app.stream(viewer, _uuid(task_id), cursor))
    # Everything required by this generator was captured before Frappe ends the
    # HTTP request context. Native sessions are rechecked independently per event.
    return Response(generator, content_type='text/event-stream; charset=utf-8', headers={
        'Cache-Control': 'private, no-store, no-transform', 'X-Accel-Buffering': 'no', 'Content-Encoding': 'identity'})
