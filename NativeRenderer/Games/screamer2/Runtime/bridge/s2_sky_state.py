# SPDX-License-Identifier: GPL-3.0-only
"""Original S2 sky7CC48, a unique1024-byte relocation-aware Rally homologue."""
import struct
LINKS={'enabled':0x133730,'flat_fill':0x133734,'ground':0x8384c}
def rgb565(value):return [((value>>11)&31)<<3,((value>>5)&63)<<2,(value&31)<<3]
def state(layout,data):
 values={key:struct.unpack('<I',data[layout.link(link,4)])[0]for key,link in LINKS.items()}
 return {'kind':'rally','enabled':bool(values['enabled']),'ground_rgb':rgb565(values['ground']),'flat_rgb':rgb565(values['flat_fill']),'source':'original-S2-7CC48-sky-flags-and-colours'}
