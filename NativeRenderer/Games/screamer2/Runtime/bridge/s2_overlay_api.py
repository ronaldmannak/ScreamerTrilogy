"""Read one coherent cached original frame + exact LFB overlay snapshot."""


def paired_display(api):
    data,headers=api.request('GET','/api/v1/rally/frame?include_overlay=1',
        headers={'Accept':'application/octet-stream'},limit=4*1024*1024)
    headers={str(k).lower():v for k,v in headers.items()}
    width,height,stride=(int(headers[k]) for k in ('x-rally-width','x-rally-height','x-rally-pitch'))
    sequence=int(headers['x-rally-sequence'])
    offset,size=(int(headers[k]) for k in ('x-rally-overlay-offset','x-rally-overlay-size'))
    if (width,height)!=(640,480) or not width*4<=stride<=65536 or offset!=stride*height or size!=offset or len(data)!=offset+size:
        raise ValueError('Incomplete or mismatched original framebuffer/overlay pair')
    if headers['x-rally-overlay-format']!='bgra8-premultiplied':
        raise ValueError('Overlay is not original premultiplied BGRA8')
    frame=dict(width=width,height=height,stride=stride,format='bgra8',sequence=sequence,
        capture_ns=int(headers.get('x-rally-capture-ns',0)))
    overlay=dict(frame,format='bgra8-premultiplied',swap_sequence=int(headers.get('x-rally-swap-sequence',0)),
        coverage_pixels=int(headers.get('x-rally-coverage-pixels',0)),
        complete=headers.get('x-rally-hud-complete')=='1',
        coverage_profile=headers.get('x-rally-coverage-profile','none'),
        needle_primitives=int(headers.get('x-rally-needle-primitives',0)))
    return data[:offset],frame,data[offset:],overlay
