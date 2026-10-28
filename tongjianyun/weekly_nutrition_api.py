"""Authorized transient analysis; no File, cache, nutrient or report records are written."""

import http.client
import json
import re
import socket
from datetime import date
from urllib.parse import urlencode

import frappe
from frappe.desk.query_report import get_report_doc
from werkzeug.wrappers import Response

from tongjianyun.ai_nutrition import canonical, source_data, source_hash
from tongjianyun.report_sources import load_source


def _authorize():
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.AuthenticationError)
    get_report_doc("Weekly Recipe Nutrition Analysis")


def _source(week_start=None, week_name=None, plan_batch=None):
    _authorize()
    if week_start:
        try:
            start = date.fromisoformat(week_start)
            if start.isoformat() != week_start or start.weekday() != 0:
                raise ValueError
        except (ValueError, TypeError):
            frappe.throw("请选择有效的星期一作为周开始日期。")
    if week_name and plan_batch:
        frappe.throw("请选择周食谱或生产计划批次中的一种。")
    for value in (week_name, plan_batch):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 140 or any(ord(c) < 32 for c in value)):
            frappe.throw("食谱选择无效。")
    source = load_source({"week_start": week_start, "week_name": week_name, "plan_batch": plan_batch})
    if week_start and source["dates"][0] != week_start:
        frappe.throw("食谱与所选周开始日期不一致。")
    try:
        return source_data(source["details"], source["dates"], source["source"])
    except (ValueError, TypeError, KeyError):
        frappe.throw("食谱带量为空或无效，请先核对原始食谱。")


class _SocketConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.host)


def _rpc(path, **payload):
    address = frappe.conf.get("tongjianyun_ephemeral_socket")
    if not address:
        frappe.throw("临时营养分析尚未启用。")
    connection = _SocketConnection(address, timeout=8)
    failed, raw, result = False, None, None
    try:
        connection.request("POST", path, body=canonical({"owner": frappe.session.user, **payload}).encode(), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(524289)
        if response.status != 200 or len(raw) > 524288:
            raise ValueError
        result = json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException):
        failed, raw, result = True, None, None
    finally:
        connection.close()
    # Raise outside the original exception context, with no partial result in locals:
    # framework error snapshots must not capture nutritional response bodies.
    if failed:
        frappe.throw("临时营养分析服务暂时不可用，请稍后重试。")
    if not result.get("ok"):
        frappe.throw("分析正在繁忙，请稍后重试。" if result.get("code") == "BUSY" else "临时结果已过期、已清除或当前账号无权访问，请重新生成。")
    return result


def _url(method, report_id):
    return "/api/method/tongjianyun.weekly_nutrition_api." + method + "?" + urlencode({"report_id": report_id})


def report_data(week_start=None, week_name=None, plan_batch=None):
    data = _source(week_start, week_name, plan_batch)
    result = _rpc("/create", data=data)
    return {"source": data["source"], "dates": data["dates"], "line_count": len(data["lines"]),
            "food_count": len({row["code"] for row in data["foods"]}),
            "report_id": result["report_id"], "expires_at": result["expires_at"], "status": "pending",
            "preview_url": _url("preview", result["report_id"]), "download_url": _url("download", result["report_id"])}


@frappe.whitelist(methods=["POST"])
def generate(week_start=None, week_name=None, plan_batch=None):
    return report_data(week_start, week_name, plan_batch)


def _access(report_id):
    _authorize()
    if not isinstance(report_id, str) or not re.fullmatch(r"[a-f0-9]{64}", report_id):
        frappe.throw("临时报告地址无效。")
    metadata = _rpc("/meta", report_id=report_id)
    current = _source(**metadata["source"])
    if source_hash(current) != metadata["fingerprint"]:
        frappe.throw("原食谱已变化，请重新生成分析。")
    return metadata


_HEADERS = {"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


@frappe.whitelist(methods=["GET"])
def result(report_id):
    _access(report_id)
    from tongjianyun.ai_nutrition import NUTRIENTS
    failed, payload, body = False, None, None
    try:
        payload = _rpc("/read", report_id=report_id)
        payload["nutrient_labels"] = NUTRIENTS
        if payload.get("status") == "ready":
            from tongjianyun.nutrition_layout import render_sheet
            payload["sheet_html"] = render_sheet(payload["data"], payload["result"])
        body = canonical({"message": payload})
    except Exception:
        failed, payload, body = True, None, None
    if failed:
        frappe.throw("暂时无法读取临时结果，请刷新预览或重新生成。")
    return Response(body, content_type="application/json; charset=utf-8", headers=_HEADERS)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def preview(report_id):
    if frappe.session.user == "Guest":
        return _preview_error("请先使用生成报告的同一业务账号登录，再打开临时预览。", 401)
    try:
        _access(report_id)
    except frappe.PermissionError:
        return _preview_error("当前账号无权访问这份临时报告，请使用生成报告的同一业务账号。", 403)
    except frappe.ValidationError:
        return _preview_error("临时结果已过期、已清除，或原食谱已经变化。请重新选择食谱并生成分析。", 410)
    from tongjianyun.nutrition_page import render
    from frappe.sessions import get_csrf_token
    html, csp = render(report_id, get_csrf_token())
    return Response(html, content_type="text/html; charset=utf-8", headers={**_HEADERS, "Content-Security-Policy": csp})


def _preview_error(message, status):
    from frappe.utils import escape_html
    html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>临时食谱分析</title><main><h1>临时食谱分析</h1><p>' + escape_html(message) + '</p><p><a href="/login">登录业务账号</a> · <a href="/desk/tongjianyun/query-report/Weekly%20Recipe%20Nutrition%20Analysis">重新选择食谱</a></p></main></html>'
    return Response(html, status=status, content_type="text/html; charset=utf-8", headers={**_HEADERS, "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


@frappe.whitelist(methods=["GET"])
def download(report_id=None, week_start=None, week_name=None, plan_batch=None):
    if not report_id:
        _authorize()
        frappe.throw("原固定代表值下载已停用，请通过膳食助手或食谱分析页重新生成临时AI报告。")
    _access(report_id)
    from tongjianyun.weekly_nutrition_sheet import workbook_bytes
    failed, payload, content, start = False, None, None, None
    try:
        payload = _rpc("/read", report_id=report_id)
        if payload["status"] != "ready":
            raise ValueError("NOT_READY")
        start = payload["data"]["dates"][0]
        content = workbook_bytes(payload["data"], payload["result"])
    except Exception:
        failed, payload, content = True, None, None
    if failed:
        frappe.throw("分析未完成、未成功或下载暂时不可用，请返回临时预览页查看。")
    return Response(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={**_HEADERS, "Content-Disposition": 'attachment; filename="meal-ai-analysis-' + start + '.xlsx"'})


@frappe.whitelist(methods=["POST"])
def discard(report_id):
    _access(report_id)
    return _rpc("/discard", report_id=report_id)
