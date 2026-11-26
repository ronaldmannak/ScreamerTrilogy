"""Shared read-only DOS/4GW LE metadata parser, copied without runtime/patch logic."""

import struct

def require(condition, message):
    if not condition:
        raise ValueError(message)

def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def parse_le(data):
    le = u32(data, 0x3c)
    require(data[le:le + 4] == b'LE\0\0', 'Expected a DOS/4GW LE executable')
    page_size = u32(data, le + 0x28)
    data_start = u32(data, le + 0x80)
    object_table = le + u32(data, le + 0x40)
    page_map = le + u32(data, le + 0x48)
    objects = []
    physical_pages = {}
    for index in range(u32(data, le + 0x44)):
        size, base, flags, first, count, _ = struct.unpack_from('<6I', data, object_table + index * 24)
        obj = {'index': index + 1, 'link_base': base, 'virtual_size': size, 'flags': flags, 'pages': []}
        for p in range(count):
            entry = page_map + (first - 1 + p) * 4
            physical = int.from_bytes(data[entry:entry + 3], 'big')
            page_flags = data[entry + 3]
            obj['pages'].append((physical, page_flags))
            if physical and page_flags == 0:
                physical_pages[physical - 1] = (index + 1, p * page_size)
        objects.append(obj)
    records = []
    fp = le + u32(data, le + 0x68)
    fr = le + u32(data, le + 0x6c)
    for page in range(u32(data, le + 0x14)):
        pos, end = fr + u32(data, fp + page * 4), fr + u32(data, fp + (page + 1) * 4)
        while pos < end:
            src, flags = data[pos:pos + 2]
            pos += 2
            if src & 0x20:
                count = data[pos]
                pos += 1
                single = None
            else:
                count = None
                single = struct.unpack_from('<h', data, pos)[0]
                pos += 2
            width = 2 if flags & 0x40 else 1
            target_obj = int.from_bytes(data[pos:pos + width], 'little')
            pos += width
            target_offset = None
            if flags & 3 == 0 and src & 15 != 2:
                width = 4 if flags & 0x10 else 2
                target_offset = int.from_bytes(data[pos:pos + width], 'little')
                pos += width
            if flags & 4:
                pos += 4 if flags & 0x20 else 2
            if count is not None:
                offsets = [struct.unpack_from('<h', data, pos + i * 2)[0] for i in range(count)]
                pos += count * 2
            else:
                offsets = [single]
            if page not in physical_pages:
                continue
            source_obj, object_page_offset = physical_pages[page]
            if src & 15 == 7 and flags & 7 == 0 and target_offset is not None:
                for offset in offsets:
                    records.append({'source_object': source_obj, 'source_offset': object_page_offset + offset,
                                    'target_object': target_obj, 'target_offset': target_offset})
    return objects, records, page_size, data_start

def map_file(objects, page_size, data_start, va):
    obj = next(o for o in objects if o['link_base'] <= va < o['link_base'] + o['virtual_size'])
    relative = va - obj['link_base']
    physical, flags = obj['pages'][relative // page_size]
    require(physical and flags == 0, 'Patch target is not backed by a legal file page')
    return data_start + (physical - 1) * page_size + relative % page_size
