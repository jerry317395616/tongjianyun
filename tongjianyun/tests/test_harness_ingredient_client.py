import json
import unittest
from unittest.mock import MagicMock, patch
from tongjianyun.harness_ingredient_client import HarnessIngredientClient, LIMIT, SOCKET
from tongjianyun.ingredient_classification import ClassificationUnavailable


class TestHarnessIngredientClient(unittest.TestCase):
    def test_batches_without_changing_groups(self):
        client = HarnessIngredientClient()
        with patch.object(client, "_request", return_value={"rows": []}) as request:
            self.assertEqual(client.classify_ingredients(list(range(41)), ["group"]), {"rows": []})
        self.assertEqual([len(call.args[0]) for call in request.call_args_list], [20, 20, 1])
        self.assertTrue(all(call.args[1] == ["group"] for call in request.call_args_list))

    def call(self, chunks):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.side_effect = chunks
        with patch("tongjianyun.harness_ingredient_client.socket.socket", return_value=sock):
            result = HarnessIngredientClient().classify_ingredients([], [])
        sock.connect.assert_called_once_with(SOCKET)
        request = json.loads(sock.sendall.call_args.args[0])
        self.assertEqual(set(request), {"version", "ingredients", "groups"})
        return result

    def test_chunked_response(self):
        self.assertEqual(self.call([b'{"ok":true,', b'"result":{"rows":[]}}\n', b'']), {"rows": []})

    def test_bad_responses(self):
        for raw in (b'{"ok":false}', b'[]', b'bad', b'{"ok":true}', b'x' * (LIMIT+1)):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ClassificationUnavailable):
                self.call([raw, b''])

    def test_socket_failure_sanitized(self):
        with patch("tongjianyun.harness_ingredient_client.socket.socket", side_effect=OSError("private")):
            with self.assertRaises(ClassificationUnavailable) as result:
                HarnessIngredientClient().classify_ingredients([], [])
        self.assertNotIn("private", str(result.exception))

    def test_oversized_input_does_not_connect(self):
        with patch("tongjianyun.harness_ingredient_client.socket.socket") as sock:
            with self.assertRaises(ClassificationUnavailable):
                HarnessIngredientClient().classify_ingredients(["x" * LIMIT], [])
            sock.assert_not_called()
