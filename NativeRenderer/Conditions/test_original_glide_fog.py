"""Original executable/table observations, without bundling game files."""
import hashlib
import math
import unittest

from original_glide_fog import original_glide_fog


class OriginalFogTableTests(unittest.TestCase):
    def test_original_rally_saved_ram_matches_all_64_bytes(self):
        # Independently read from the original game's table at link173F3C in
        # immutable RAM SHA34b05fdfc4a658e4cdd4af07cf1f01f69da6185dd892a108afb7c03fd7b772b6.
        # Original cached inputs174000: far-45000, near-4000, color0. A digest
        # preserves that64-byte proof without putting original data in the repo.
        table = original_glide_fog(far=45000, color_rgb=(0, 0, 0))['table']
        self.assertEqual(hashlib.sha256(bytes(table)).hexdigest(),
                         '29e5150a6d57fe6ec94b942d075ffdb38de367c857aa983d646c7af456ff2d13')

    def test_colored_fog_uses_original_sine_table_and_byte_truncation(self):
        fog = original_glide_fog()
        self.assertEqual(fog['table'], [0] * 36 + [12,25,38,50,63,75,87,99,111,122,133,144,
                                                   155,164,174,183,192,200,208,215,221,227,233,
                                                   238,242,246,249,251])
        self.assertEqual(fog['color_rgb'], [184,184,184])
        self.assertEqual((fog['w_scale'], fog['far_distance']), (1, 25000))

    def test_black_haze_retains_original_far_extension_and_final_clamp(self):
        black = original_glide_fog(far=6000, color_rgb=(0, 0, 0))['table']
        grey = original_glide_fog(far=6000)['table']
        self.assertLess(black[40], grey[40])
        # The original clamps to negative-end-minus1 before sin, then truncates;
        # this deliberately gives254 rather than silently forcing opaque255.
        self.assertEqual(black[-1], 254)
        self.assertEqual(grey[-1], 254)

    def test_nonfinite_distance_and_nonbyte_colors_are_rejected(self):
        for far in (math.nan, math.inf, True, 0, -25000, 10000001):
            with self.assertRaises(ValueError):
                original_glide_fog(far=far)
        for color in ((184,184), (184,184,256), (184,184,True), (184.,184,184)):
            with self.assertRaises(ValueError):
                original_glide_fog(color_rgb=color)


if __name__ == '__main__':
    unittest.main()
