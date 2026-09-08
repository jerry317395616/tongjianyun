"""Local Harness classification transport. No model credentials or agent tools."""
import json
import socket
import time

SOCKET = "/home/zyd/frappe/state/ingredient-model/bridge.sock"
LIMIT = 128 * 1024


class HarnessIngredientClient:
    def classify_ingredients(self, ingredients, groups):
        if len(ingredients) > 20:
            rows = []
            for offset in range(0, len(ingredients), 20):
                result = self._request(ingredients[offset:offset + 20], groups)
                if not isinstance(result, dict) or set(result) != {"rows"} or not isinstance(result["rows"], list):
                    from tongjianyun.ingredient_classification import ClassificationUnavailable
                    raise ClassificationUnavailable("Harness 分类结果格式无效。")
                rows.extend(result["rows"])
            return {"rows": rows}
        return self._request(ingredients, groups)

    def _request(self, ingredients, groups):
        from tongjianyun.ingredient_classification import ClassificationUnavailable

        payload = json.dumps({"version": 1, "ingredients": ingredients, "groups": groups},
                             ensure_ascii=False).encode() + b"\n"
        if len(payload) > LIMIT:
            raise ClassificationUnavailable("食材分类请求过大，请缩小范围。")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                deadline = time.monotonic() + 65
                connection.settimeout(65)
                connection.connect(SOCKET)
                connection.sendall(payload)
                raw = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    connection.settimeout(remaining)
                    chunk = connection.recv(min(65536, LIMIT + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > LIMIT:
                        raise ValueError()
                answer = json.loads(raw)
                if not isinstance(answer, dict) or answer.get("ok") is not True:
                    if isinstance(answer, dict) and answer.get("error") in {
                        "timeout", "error", "aborted", "max-tokens", "tool-calls", "invalid_request", "model_unavailable"
                    }:
                        raise ClassificationUnavailable("Harness 分类未完成：" + answer["error"])
                    raise ValueError()
                return answer["result"]
        except (OSError, ValueError, KeyError, TypeError):
            raise ClassificationUnavailable("Harness 模型分类服务暂不可用，未创建物料或物料组。") from None
