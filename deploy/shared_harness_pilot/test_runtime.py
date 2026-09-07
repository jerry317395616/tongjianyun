"""Static deployment checks, not a replacement for a live Loader/browser test."""
from pathlib import Path
import unittest
import yaml

ROOT = Path('/home/zyd/frappe/deepseek-harness/apps/cli/config/examples')
LOCAL = Path(__file__).parent

class SharedRuntimeTests(unittest.TestCase):
    def test_only_scoped_layers_and_new_state_directory(self):
        unit = (LOCAL / 'runtime.conf').read_text()
        self.assertIn('DSH_HOME=/home/zyd/frappe/harness-shared-state', unit)
        self.assertIn('--port 13090', unit)
        self.assertNotIn('native-bench-business/cordis.yml', unit)
        self.assertIn('StandardOutput=null', unit)

    def test_composed_flags_keep_dangerous_tools_and_settings_shell_off(self):
        entries = {}
        for path in [ROOT/'employee-readonly/cordis.yml', ROOT/'employee-shared/cordis.yml', LOCAL/'runtime.yml']:
            for row in yaml.load(path.read_text(), Loader=yaml.BaseLoader):
                if 'id' in row: entries.setdefault(row['id'], {}).update(row)
                for insert in row.get('insert', []): entries[insert['id']] = insert
        for name in ['tool-bash','tool-fs','tool-str-replace-editor','code-runtime','tool-subagent',
                     'ui-settings-general','ui-settings-models','ui-settings-plugins']:
            self.assertEqual(entries[name]['disabled'], 'true', name)
        self.assertEqual(entries['ui-settings']['disabled'], 'false')
        self.assertEqual(entries['employee-session-access']['config']['promptPreset'], 'employee-shared-readonly')
        self.assertNotIn('native-bench-business-policy', entries)
        self.assertNotIn('settings/update', entries['typert-gateway']['config']['allowedEndpoints'])

    def test_model_uses_environment_reference_not_embedded_key(self):
        rows = yaml.safe_load((LOCAL/'runtime.yml').read_text())
        provider = next(row for row in rows if row['id']=='llm-pi-ai')['config']['providers']['qwen']
        self.assertEqual(provider['apiKeyEnv'], 'QWEN_API_KEY')
        self.assertNotIn('apiKey', provider)
        self.assertEqual(provider['models'][0]['maxTokens'], 1024)

if __name__ == '__main__': unittest.main()
