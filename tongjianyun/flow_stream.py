from __future__ import annotations

import contextvars
import queue
import threading
from typing import Any

FLOW_HEARTBEAT_INTERVAL = 5.0


def install_flow_stream_heartbeat() -> bool:
	"""Keep Flow SSE connections active while tool-call arguments are streaming."""
	try:
		import flow.lib.model as flow_model
	except ImportError:
		return False

	current = flow_model._consume_stream
	if getattr(current, "_ione_heartbeat", False):
		return False

	_consume_stream_with_heartbeat._ione_heartbeat = True
	flow_model._consume_stream = _consume_stream_with_heartbeat
	return True


def _consume_stream_with_heartbeat(chunks: Any, model_module: Any | None = None):
	if model_module is None:
		import flow.lib.model as model
	else:
		model = model_module

	content_parts: list[str] = []
	tool_calls_acc: dict[int, dict[str, str]] = {}
	announced: set[int] = set()
	usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
	finish_reason: str | None = None

	for chunk in chunks:
		choices = getattr(chunk, "choices", None) or []
		if choices:
			choice = choices[0]
			delta = getattr(choice, "delta", None)
			if delta is not None:
				emitted = False
				text = model._attr(delta, "content")
				if text:
					content_parts.append(text)
					emitted = True
					yield text

				tool_deltas = model._attr(delta, "tool_calls") or []
				for tool_delta in tool_deltas:
					index = model._accumulate_tool_call(tool_calls_acc, tool_delta)
					slot = tool_calls_acc[index]
					if index not in announced and slot["id"] and slot["name"]:
						announced.add(index)
						emitted = True
						yield model.ToolCallBegin(id=slot["id"], name=slot["name"])

				# Flow normally stays silent while arguments stream. An empty text frame keeps
				# Cloudflare and nginx from closing an otherwise healthy SSE connection.
				if tool_deltas and not emitted:
					yield ""

			reason = model._attr(choice, "finish_reason")
			if reason:
				finish_reason = reason

		usage_obj = getattr(chunk, "usage", None)
		if usage_obj is not None:
			usage = {
				"prompt_tokens": model._attr(usage_obj, "prompt_tokens", 0) or 0,
				"completion_tokens": model._attr(usage_obj, "completion_tokens", 0) or 0,
				"total_tokens": model._attr(usage_obj, "total_tokens", 0) or 0,
			}

	return model.ChatResponse(
		content="".join(content_parts) or None,
		tool_calls=model._finalize_tool_calls(tool_calls_acc),
		finish_reason=finish_reason,
		usage=usage,
	)


def keepalive_events(
	events: Any,
	*,
	interval: float = FLOW_HEARTBEAT_INTERVAL,
	heartbeat_factory: Any | None = None,
):
	"""Consume a Flow run off-thread and keep its SSE response active.

	The producer is allowed to finish when the HTTP consumer disconnects. The
	request thread waits for it during generator close so Flow can persist the
	final run state before Frappe tears down the request context.
	"""
	if heartbeat_factory is None:
		from flow.lib.agent import TextChunk

		heartbeat_factory = lambda: TextChunk("")

	items: queue.Queue[tuple[str, Any]] = queue.Queue()
	context = contextvars.copy_context()

	def consume() -> None:
		try:
			for event in events:
				items.put(("event", event))
		except BaseException as error:
			items.put(("error", error))
		finally:
			items.put(("done", None))

	producer = threading.Thread(
		target=context.run,
		args=(consume,),
		name="ione-flow-stream",
		daemon=True,
	)
	producer.start()

	try:
		while True:
			try:
				kind, payload = items.get(timeout=interval)
			except queue.Empty:
				yield heartbeat_factory()
				continue

			if kind == "event":
				yield payload
			elif kind == "error":
				raise payload
			else:
				return
	finally:
		# If the browser closes the SSE connection, finish the active Flow turn
		# before request-local database resources are released.
		while producer.is_alive():
			producer.join(timeout=0.5)
