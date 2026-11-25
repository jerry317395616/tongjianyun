from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import PurePath
from typing import Any

import frappe
import requests
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from tongjianyun.mcp.video import manifest_from_video_document

ALLOWED_IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 15 * 1024 * 1024
MAX_ARTIFACT_BYTES = 150 * 1024 * 1024


def _renderer_settings() -> tuple[str, str, int]:
	url = str(frappe.conf.get("ione_video_renderer_url") or "http://10.144.133.1:8120").rstrip("/")
	token = str(frappe.conf.get("ione_video_renderer_token") or "").strip()
	wait_seconds = int(frappe.conf.get("ione_video_renderer_max_wait_seconds") or 7200)
	if not token:
		frappe.throw("视频渲染服务令牌尚未配置")
	return url, token, max(300, min(wait_seconds, 21600))


def _headers(token: str) -> dict[str, str]:
	return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _update_status(video_name: str, **values: Any) -> None:
	frappe.db.set_value("I-ONE Deal Video", video_name, values, update_modified=False)
	frappe.db.commit()


def _resolve_scene_assets(deal: str, manifest: dict[str, Any]) -> dict[str, Any]:
	total_bytes = 0
	for scene in manifest["scenes"]:
		file_reference = str(scene.get("asset_file") or "").strip()
		if not file_reference:
			continue
		filters = {
			"attached_to_doctype": "CRM Deal",
			"attached_to_name": deal,
		}
		if frappe.db.exists("File", file_reference):
			filters["name"] = file_reference
		else:
			filters["file_name"] = PurePath(file_reference).name
		rows = frappe.get_all(
			"File",
			filters=filters,
			fields=["name", "file_name", "file_url", "file_size"],
			order_by="modified desc",
			limit_page_length=1,
		)
		if not rows:
			frappe.throw(f"分镜素材不属于当前商机: {file_reference}")
		row = rows[0]
		extension = PurePath(str(row.file_name or "")).suffix.lower()
		if extension not in ALLOWED_IMAGE_EXTENSIONS:
			frappe.throw(f"视频画面素材仅支持 PNG、JPEG 或 WebP: {row.file_name}")
		if str(row.file_url or "").startswith(("http://", "https://")):
			frappe.throw(f"不允许使用远程画面素材: {row.file_name}")
		payload = frappe.get_doc("File", row.name).get_content()
		if isinstance(payload, str):
			payload = payload.encode("utf-8")
		payload = bytes(payload)
		if not payload or len(payload) > MAX_IMAGE_BYTES:
			frappe.throw(f"画面素材为空或超过 5 MB: {row.file_name}")
		total_bytes += len(payload)
		if total_bytes > MAX_TOTAL_IMAGE_BYTES:
			frappe.throw("视频画面素材总大小超过 15 MB")
		mime_type = mimetypes.guess_type(str(row.file_name))[0] or "application/octet-stream"
		scene["asset_data_uri"] = f"data:{mime_type};base64,{base64.b64encode(payload).decode('ascii')}"
		scene["asset_name"] = row.file_name
	return manifest


def _artifact(session: requests.Session, url: str, token: str) -> bytes:
	response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=300, stream=True)
	response.raise_for_status()
	payload = bytearray()
	for chunk in response.iter_content(chunk_size=1024 * 1024):
		payload.extend(chunk)
		if len(payload) > MAX_ARTIFACT_BYTES:
			raise ValueError("Rendered artifact exceeds the 150 MB limit")
	return bytes(payload)


def queue_deal_video_render(video_name: str, quality: str = "正式") -> dict[str, Any]:
	video = frappe.get_doc("I-ONE Deal Video", video_name)
	video.check_permission("write")
	deal = frappe.get_doc("CRM Deal", video.deal)
	deal.check_permission("write")
	if video.status in {"已排队", "渲染中"}:
		return {"video": video.name, "status": video.status, "queued": False}
	if not video.scenes:
		frappe.throw("视频分镜为空, 不能提交渲染")
	manifest_from_video_document(video)
	_renderer_settings()
	video.quality = "草稿" if str(quality).lower() in {"draft", "草稿"} else "正式"
	video.status = "已排队"
	video.progress = 0
	video.current_step = "等待渲染服务"
	video.approved_by = frappe.session.user
	video.approved_at = now_datetime()
	video.error_message = ""
	video.save()
	job = frappe.enqueue(
		"tongjianyun.deal_video.render_deal_video",
		queue="long",
		timeout=21600,
		enqueue_after_commit=True,
		job_name=f"deal-video-{video.name}",
		video_name=video.name,
	)
	return {
		"video": video.name,
		"status": video.status,
		"queued": True,
		"queue_job_id": getattr(job, "id", None),
	}


def render_deal_video(video_name: str) -> None:
	video = frappe.get_doc("I-ONE Deal Video", video_name)
	base_url, token, max_wait_seconds = _renderer_settings()
	try:
		manifest = _resolve_scene_assets(video.deal, manifest_from_video_document(video))
		quality = "draft" if video.quality == "草稿" else "final"
		payload = {
			"reference": video.name,
			"quality": quality,
			"manifest": manifest,
		}
		_update_status(
			video.name,
			status="渲染中",
			progress=1,
			current_step="准备视频素材",
			render_started_at=now_datetime(),
			error_message="",
		)
		session = requests.Session()
		# The renderer is an internal service. Bench-wide HTTP proxy settings must not
		# route its large request and artifacts through the outbound GitHub relay.
		session.trust_env = False
		response = session.post(
			f"{base_url}/v1/jobs", json=payload, headers=_headers(token), timeout=60
		)
		response.raise_for_status()
		job_id = str(response.json().get("job_id") or "")
		if not job_id:
			raise RuntimeError("Renderer did not return a job id")
		_update_status(video.name, renderer_job_id=job_id, current_step="正在渲染")

		started = time.monotonic()
		result = None
		while time.monotonic() - started < max_wait_seconds:
			response = session.get(
				f"{base_url}/v1/jobs/{job_id}",
				headers={"Authorization": f"Bearer {token}"},
				timeout=30,
			)
			response.raise_for_status()
			result = response.json()
			status = str(result.get("status") or "")
			progress = max(1, min(float(result.get("progress") or 0), 99))
			_update_status(
				video.name,
				progress=progress,
				current_step=str(result.get("step") or "正在渲染")[:140],
			)
			if status == "completed":
				break
			if status == "failed":
				raise RuntimeError(str(result.get("error") or "视频渲染失败"))
			time.sleep(5)
		else:
			raise TimeoutError("视频渲染超过允许的最长等待时间")

		artifacts = (result or {}).get("artifacts") or {}
		version = int(video.render_version or 0) + 1
		file_urls: dict[str, str] = {}
		artifact_specs = {
			"video": (f"promo_{video.name}_v{version}.mp4", "output_video"),
			"cover": (f"promo_{video.name}_v{version}_cover.png", "output_cover"),
			"subtitles": (f"promo_{video.name}_v{version}.srt", "output_subtitles"),
		}
		for key, (file_name, fieldname) in artifact_specs.items():
			artifact_url = str((artifacts.get(key) or {}).get("url") or "")
			if not artifact_url:
				raise RuntimeError(f"Renderer did not return the {key} artifact")
			if artifact_url.startswith("/"):
				artifact_url = f"{base_url}{artifact_url}"
			content = _artifact(session, artifact_url, token)
			file_doc = save_file(file_name, content, "CRM Deal", video.deal, is_private=1)
			file_urls[fieldname] = file_doc.file_url

		video.reload()
		video.status = "已完成"
		video.progress = 100
		video.current_step = "渲染完成"
		video.render_completed_at = now_datetime()
		video.render_version = version
		video.error_message = ""
		for fieldname, file_url in file_urls.items():
			video.set(fieldname, file_url)
		video.save(ignore_permissions=True)
		frappe.get_doc("CRM Deal", video.deal).add_comment(
			"Info", text=f"客户宣传视频 {video.name} 第 {version} 版已生成并附加到商机。"
		)
		frappe.db.commit()
	except Exception as exc:
		frappe.log_error(title=f"Deal video render failed: {video_name}", message=frappe.get_traceback())
		_update_status(
			video_name,
			status="失败",
			current_step="渲染失败",
			error_message=str(exc)[:2000],
		)
		raise
