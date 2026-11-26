"""Regression: normal startup must not disable future Voodoo HUD coverage."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from live_bridge import Session

class FrameTransitionTests(unittest.TestCase):
    def test_intro_without_overlay_then_race_recovers_exact_hud(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            args=SimpleNamespace(base_url='http://127.0.0.1:1',input=root/'input.json',state=root/'state.json',
                cache_root=root/'cache',extractor_dir=root/'extractor',allow_isr_input=False,hud_profile=None,frame_hz=30)
            session=Session(args)
            session.api.frame=Mock(return_value=(b'intro',{'sequence':1,'width':640,'height':400}))
            pair=(b'race',{'sequence':2,'width':640,'height':480},b'exact-alpha',{'sequence':2,'complete':True})
            with patch('live_bridge.paired_display',side_effect=[KeyError('x-rally-overlay-offset'),pair]) as read:
                session.poll_frame(1.)
                self.assertIsNot(session.overlay_supported,False)
                self.assertEqual(session.frame['sequence'],1)
                self.assertIsNone(session.overlay_metadata)
                session.poll_frame(2.)
                self.assertEqual(read.call_count,2)
                self.assertTrue(session.overlay_supported)
                self.assertEqual(session.frame['sequence'],2)
                self.assertEqual(session.overlay_raw,b'exact-alpha')
                self.assertTrue(session.overlay_metadata['complete'])
