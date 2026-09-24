"""The meal chat only launches Codex after access and input validation."""
import json
import subprocess
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tongjianyun import meal_chat


class MealChatTests(unittest.TestCase):
    def test_only_completed_agent_answer_is_returned(self):
        output = '\n'.join(json.dumps(row) for row in (
            {'type': 'thread.started', 'thread_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'aggregated_output': 'private tool output'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '已处理食谱。'}},
            {'type': 'turn.completed'},
        ))
        self.assertEqual(meal_chat._answer_from_events(output),
                         ('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', '已处理食谱。'))

    def test_new_message_uses_stdin_and_retains_thread(self):
        output = '\n'.join(json.dumps(row) for row in (
            {'type': 'thread.started', 'thread_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '收到。'}},
            {'type': 'turn.completed'},
        ))
        cache = MagicMock()
        cache.get_value.return_value = None
        process = subprocess.CompletedProcess([], 0, output, '')
        with patch.object(meal_chat, 'require_chat_access'), \
             patch.object(meal_chat, 'business_day', return_value=date(2026, 9, 24)), \
             patch.object(meal_chat, 'meal_key', return_value='lunch'), \
             patch.object(meal_chat, '_cache_key', return_value='session-key'), \
             patch.object(meal_chat.frappe, 'cache', return_value=cache), \
             patch.object(meal_chat.subprocess, 'run', return_value=process) as run:
            answer = meal_chat.send_message('请看本周食谱', '2026-09-24', 'lunch')
        self.assertEqual(answer, {'reply': '收到。'})
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [meal_chat.CODEX, '-C', meal_chat.PROJECT])
        self.assertEqual(command[-1], '-')
        self.assertNotIn('请看本周食谱', command)
        self.assertIn('请看本周食谱', run.call_args.kwargs['input'])
        cache.set_value.assert_called_once_with('session-key',
            'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', expires_in_sec=14 * 24 * 3600)

    def test_rejects_oversized_message_before_running_codex(self):
        with patch.object(meal_chat, 'require_chat_access'), \
             patch.object(meal_chat.frappe, 'throw', side_effect=ValueError), \
             patch.object(meal_chat.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                meal_chat.send_message('x' * 2001, '2026-09-24', 'lunch')
            run.assert_not_called()
