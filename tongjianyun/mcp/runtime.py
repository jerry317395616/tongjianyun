from __future__ import annotations

import inspect
import json
import types
from collections.abc import Callable
from functools import wraps
from typing import Any, ClassVar, Literal, Union, get_args, get_origin, get_type_hints


class ToolAnnotations(dict):
	"""MCP tool behavior hints without an external runtime dependency."""

	def __init__(
		self,
		*,
		readOnlyHint: bool | None = None,
		destructiveHint: bool | None = None,
		idempotentHint: bool | None = None,
		openWorldHint: bool | None = None,
	):
		super().__init__(
			(key, value)
			for key, value in {
				"readOnlyHint": readOnlyHint,
				"destructiveHint": destructiveHint,
				"idempotentHint": idempotentHint,
				"openWorldHint": openWorldHint,
			}.items()
			if value is not None
		)


def _json_schema(annotation: Any) -> dict[str, Any]:
	if annotation in {inspect.Parameter.empty, Any}:
		return {}
	if annotation is None or annotation is type(None):
		return {"type": "null"}

	origin = get_origin(annotation)
	args = get_args(annotation)
	if origin in {Union, types.UnionType}:
		non_null = [item for item in args if item is not type(None)]
		if len(non_null) == 1 and len(non_null) != len(args):
			schema = _json_schema(non_null[0])
			if "type" in schema and isinstance(schema["type"], str):
				schema["type"] = [schema["type"], "null"]
			else:
				schema = {"anyOf": [schema, {"type": "null"}]}
			return schema
		return {"anyOf": [_json_schema(item) for item in args]}
	if origin is Literal:
		values = list(args)
		return {"type": _primitive_type(type(values[0])) if values else "string", "enum": values}
	if origin in {list, tuple, set}:
		return {"type": "array", "items": _json_schema(args[0] if args else Any)}
	if origin is dict:
		return {"type": "object", "additionalProperties": _json_schema(args[1] if len(args) > 1 else Any)}
	if annotation is bool:
		return {"type": "boolean"}
	if annotation is int:
		return {"type": "integer"}
	if annotation is float:
		return {"type": "number"}
	if annotation is str:
		return {"type": "string"}
	return {"type": "object"}


def _primitive_type(annotation: type) -> str:
	return {bool: "boolean", int: "integer", float: "number", str: "string"}.get(annotation, "string")


def _doc_details(fn: Callable) -> tuple[str, dict[str, str]]:
	doc = inspect.getdoc(fn) or ""
	description = []
	arguments: dict[str, str] = {}
	in_args = False
	for raw_line in doc.splitlines():
		line = raw_line.strip()
		if line == "Args:":
			in_args = True
			continue
		if in_args and ":" in line:
			name, text = line.split(":", 1)
			arguments[name.strip()] = text.strip()
		elif not in_args and line:
			description.append(line)
	return " ".join(description), arguments


def _tool_schema(fn: Callable) -> dict[str, Any]:
	signature = inspect.signature(fn)
	try:
		hints = get_type_hints(fn)
	except NameError, TypeError:
		hints = {}
	_, argument_docs = _doc_details(fn)
	properties = {}
	required = []
	for name, parameter in signature.parameters.items():
		annotation = hints.get(name, parameter.annotation)
		schema = _json_schema(annotation)
		if name in argument_docs:
			schema["description"] = argument_docs[name]
		properties[name] = schema
		if parameter.default is inspect.Parameter.empty:
			required.append(name)
	result: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
	if required:
		result["required"] = required
	return result


class MCP:
	SUPPORTED_PROTOCOL_VERSIONS: ClassVar[set[str]] = {"2024-11-05", "2025-03-26", "2025-06-18"}

	def __init__(self, name: str, version: str = "0.1.0"):
		self.name = name
		self.version = version
		self._tools: dict[str, dict[str, Any]] = {}

	def tool(self, *, annotations: ToolAnnotations | None = None):
		def decorator(fn: Callable):
			description, _ = _doc_details(fn)
			self._tools[fn.__name__] = {
				"function": fn,
				"definition": {
					"name": fn.__name__,
					"description": description,
					"inputSchema": _tool_schema(fn),
					"annotations": dict(annotations or {}),
				},
			}
			return fn

		return decorator

	def register(self, *, allow_guest: bool = False):
		def decorator(setup: Callable):
			import frappe

			@frappe.whitelist(allow_guest=allow_guest, methods=["POST"])
			@wraps(setup)
			def endpoint(*args, **kwargs):
				setup()
				payload = frappe.request.get_json(silent=True)
				if payload is None:
					return self._response(self._error(None, -32700, "Invalid JSON"), status=400)
				response = self.process(payload)
				if response is None:
					return self._response("", status=202)
				return self._response(response)

			return endpoint

		return decorator

	def process(self, payload: Any) -> Any:
		if isinstance(payload, list):
			if not payload:
				return self._error(None, -32600, "Invalid Request")
			responses = [
				response for item in payload if (response := self._process_message(item)) is not None
			]
			return responses or None
		return self._process_message(payload)

	def _process_message(self, message: Any) -> dict[str, Any] | None:
		if (
			not isinstance(message, dict)
			or message.get("jsonrpc") != "2.0"
			or not isinstance(message.get("method"), str)
		):
			return self._error(
				message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request"
			)

		request_id = message.get("id")
		is_notification = "id" not in message
		method = message["method"]
		params = message.get("params") or {}
		try:
			if method == "initialize":
				result = self._initialize(params)
			elif method == "ping":
				result = {}
			elif method == "tools/list":
				result = {"tools": [entry["definition"] for entry in self._tools.values()]}
			elif method == "tools/call":
				result = self._call_tool(params)
			elif method.startswith("notifications/"):
				return None
			else:
				return None if is_notification else self._error(request_id, -32601, "Method not found")
		except (TypeError, ValueError) as exc:
			return None if is_notification else self._error(request_id, -32602, str(exc))

		if is_notification:
			return None
		return {"jsonrpc": "2.0", "id": request_id, "result": result}

	def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
		requested = params.get("protocolVersion")
		protocol = requested if requested in self.SUPPORTED_PROTOCOL_VERSIONS else "2025-03-26"
		return {
			"protocolVersion": protocol,
			"capabilities": {"tools": {"listChanged": False}},
			"serverInfo": {"name": self.name, "version": self.version},
		}

	def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
		if not isinstance(params, dict):
			raise ValueError("Tool parameters must be an object")
		name = params.get("name")
		if not isinstance(name, str) or name not in self._tools:
			raise ValueError(f"Unknown tool: {name or '<empty>'}")
		arguments = params.get("arguments") or {}
		if not isinstance(arguments, dict):
			raise ValueError("Tool arguments must be an object")
		fn = self._tools[name]["function"]
		try:
			inspect.signature(fn).bind(**arguments)
		except TypeError as exc:
			raise ValueError(str(exc)) from exc
		try:
			result = fn(**arguments)
		except Exception as exc:
			return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
		text = json.dumps(result, ensure_ascii=False, default=str)
		response: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
		if isinstance(result, dict):
			response["structuredContent"] = result
		return response

	@staticmethod
	def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
		return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

	@staticmethod
	def _response(payload: Any, *, status: int = 200):
		from werkzeug.wrappers import Response

		if payload == "":
			return Response(status=status)
		return Response(
			json.dumps(payload, ensure_ascii=False, default=str),
			status=status,
			content_type="application/json; charset=utf-8",
		)
