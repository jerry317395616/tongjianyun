import unittest
from tongjianyun.camera_preflight import validate_endpoint, parse_xml, probe, MAX_XML


class CameraPreflightTests(unittest.TestCase):
    def test_private_vpn_origin(self):
        self.assertEqual(validate_endpoint('https://192.168.20.10/'), 'https://192.168.20.10')

    def test_unsafe_origins(self):
        for value in ['http://192.168.1.10', 'https://127.0.0.1', 'https://169.254.169.254',
                      'https://8.8.8.8', 'https://example.com', 'https://u:p@192.168.1.10',
                      'https://192.168.1.10/path', 'https://192.168.1.10?secret=x']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_endpoint(value)

    def test_bounded_xml(self):
        self.assertEqual(parse_xml(b'<DeviceInfo><model>sample</model></DeviceInfo>').tag, 'DeviceInfo')
        for value in [b'', b'x' * (MAX_XML + 1), b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>']:
            with self.assertRaises(Exception):
                parse_xml(value)

    def test_no_tls_bypass(self):
        with self.assertRaises(ValueError):
            probe('https://192.168.1.10', 'test', 'synthetic', ca_bundle=False)
