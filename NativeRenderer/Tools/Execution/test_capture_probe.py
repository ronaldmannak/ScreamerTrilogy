#!/usr/bin/env python3
"""Offline guard tests. No game payload, network, emulator or input automation."""

from pathlib import Path
import argparse
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
import capture_probe as probe


class ProbeGuards(unittest.TestCase):
    def test_capture_file_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture'
            probe.write_new(path, b'first')
            with self.assertRaises(FileExistsError):
                probe.write_new(path, b'second')
            self.assertEqual(path.read_bytes(), b'first')

    def test_unknown_game_hash_fails_before_output_or_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'SR').mkdir()
            (root / 'cd').mkdir()
            (root / 'SR/STRT3FX.EXE').write_bytes(b'unsupported test input')
            (root / 'SR/GLIDE2X.OVL').write_bytes(b'not a driver')
            (root / 'cd/srally.cue').write_text('not a disc fixture')
            output = root / 'new-capture'
            args = argparse.Namespace(engine=Path(sys.executable), game_root=root,
                                      disc_cue=None, output=output)
            with mock.patch.object(probe.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(ValueError, 'Unsupported STRT3FX.EXE'):
                    probe.preflight(args)
                start.assert_not_called()
            self.assertFalse(output.exists())

    def test_unrelocated_file_image_is_not_running_guest_code(self):
        memory = bytearray(0x2000)
        helper = 0x1000
        memory[helper:helper + 13] = (
            b'\x50\xa1' + struct.pack('<I', 0x30512) + bytes.fromhex('83f8037cf658c3'))
        with self.assertRaisesRegex(ValueError, 'Expected one loaded relocated'):
            probe.resolve(memory, [], [])

    def test_config_path_quote_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad"name'
            path.touch()
            with self.assertRaisesRegex(ValueError, 'unsupported quote or newline'):
                probe.checked_path(path, 'Fixture')


if __name__ == '__main__':
    unittest.main()
