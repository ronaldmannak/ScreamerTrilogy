# Original loading-screen artwork

These are lossless decodes of loading backgrounds from the user's own original
game data. No screenshots, downloaded cover art, recoloring, raster compositing,
cropping, generative images, or new illustration were used. The AppKit view draws
the native-size PNG with cover scaling and a dark overlay at runtime.

Selected backgrounds:

| Profile key | Archive | Original member | Resolution |
|---|---|---|---|
| `screamer` | `GFX/GRAF.DAT` | `LOAD1H.PCX` | 640×400 |
| `screamer2` | `GFX/GRAF2.DAT` | `LOAD_1H.BKK` | 640×400 |
| `screamerrally` | `GFX/GRAF2.DAT` | `LOAD_1H.BKK` (Wales loading screen) | 640×400 |

The extraction script reads the archive directory (32-byte records, names XOR
0x3a) and decodes the game's LSB-first 9–12-bit LZW entries. PCX uses its original
8-bit palette and RLE data. BKK (`VK56`) uses its original RGB565 palette and
indexed pixels. Each BKK has a 24-byte header, 512-byte palette and 256,000 pixels.
The archive and LZW format agree with the inspected `sr-disc` parser in
Rick-Barber/ScreamerRally-Recomp; extraction executes no DOS programs.

`provenance.json` records archive, member and output SHA-256 hashes. Other decoded
loading images are retained as visual references; builders need only copy the
chosen `<profile-key>/SelectionBackground.png` into that game's options helper's
`Contents/Resources/SelectionBackground.png`.

To regenerate with other source locations:

```sh
python3 extract-original-artwork.py \
  --screamer-game '/path/to/Screamer game' \
  --screamer2-game '/path/to/Screamer 2 game' \
  --rally-game '/path/to/SR'
```

The new UI function is `chooseOptions(settings, profile)`. Pass the parent game
profile to the helper explicitly; its `title`, `key`, `distance_options` and
optional `distance_help` drive the UI. Play writes `distance_level` plus the
backward-compatible `extended_distance` boolean. Quit, window close and Escape
leave the settings dictionary unchanged.

Original artwork remains the property of the games' respective rights holders.
