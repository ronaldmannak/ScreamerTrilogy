# SPDX-License-Identifier: GPL-3.0-only
"""Pure, fail-closed policy for original S1 graphics replacement.

The frontend loads immutable scene assets while original drawing is active.
One bounded bootstrap lease can then bypass a bad original world raster span
long enough for the original HUD to complete. Continuing requires a fresh exact
HUD and a frontend that confirms the native renderer is actually active.
"""
import json
from pathlib import Path

FRONTEND_MAX_AGE_NS=300_000_000
HUD_MAX_AGE_NS=250_000_000
POSE_MAX_AGE_NS=150_000_000
BOOTSTRAP_NS=600_000_000
SUPPORTED_HUD_MODES={2}


def frontend_heartbeat(path,epoch,assets_epoch,now):
    """Read bounded atomic frontend state; focus is independent of rendering."""
    try:
        path=Path(path)
        if path.stat().st_size>65536:return None
        value=json.loads(path.read_bytes())
        if not isinstance(value,dict) or value.get('schema')!='screamer-input/v1' or value.get('epoch')!=epoch:return None
        stamp=value.get('published_monotonic_ns');seq=value.get('seq',value.get('sequence'))
        if not isinstance(stamp,int) or isinstance(stamp,bool) or not -50_000_000<=now-stamp<=FRONTEND_MAX_AGE_NS:return None
        if not isinstance(seq,int) or isinstance(seq,bool) or seq<0:return None
        fields=('native_render_requested','native_assets_ready','native_renderer_ready')
        if not all(isinstance(value.get(k),bool) for k in fields):return None
        if not assets_epoch or value.get('native_assets_epoch')!=assets_epoch:return None
        return {k:value[k] for k in fields}
    except (OSError,ValueError,TypeError):return None


def exact_hud_ready(hud,mode,assets_epoch,assets_since,now):
    if not isinstance(hud,dict):return False
    captured=hud.get('capture_ns')
    return (isinstance(captured,int) and not isinstance(captured,bool)
            and 0<=now-captured<=HUD_MAX_AGE_NS and captured>=assets_since
            and hud.get('assets_epoch')==assets_epoch and hud.get('original_hud_mode')==mode
            and hud.get('coverage')=='original-ram-byte-writes'
            and hud.get('width')==640 and hud.get('height')==480 and hud.get('stride')==2560
            and bool(hud.get('path')))


class GraphicsPolicy:
    def __init__(self):
        self.attempted=set()
        self.bootstrap_key=None
        self.bootstrap_until=0

    def decide(self,*,now,pose,assets,assets_since,hud,frontend,stopped=False):
        def off(reason):
            self.bootstrap_key=None;self.bootstrap_until=0
            return {'ready':False,'phase':'fallback','reason':reason,'renew':True}
        if stopped:return off('Bridge stopped')
        if not assets or not assets.get('epoch'):return off('Original scene assets are not ready')
        if not pose or pose.get('status')!='race' or not pose.get('camera'):return off('Original main race is not active')
        stamp=pose.get('sample_monotonic_ns',0)
        if not isinstance(stamp,int) or not 0<=now-stamp<=POSE_MAX_AGE_NS:return off('Original race pose is stale')
        mode=pose.get('original_hud_mode')
        if mode not in SUPPORTED_HUD_MODES:return off('Original view requires framebuffer fallback')
        if not frontend or not frontend['native_render_requested'] or not frontend['native_assets_ready']:
            return off('Native frontend is unavailable or original view was requested')
        key=(assets['epoch'],mode)
        exact=exact_hud_ready(hud,mode,assets['epoch'],assets_since,now)
        if exact and frontend['native_renderer_ready']:
            self.attempted.add(key);self.bootstrap_key=None;self.bootstrap_until=0
            return {'ready':True,'phase':'native','reason':None,'renew':True}
        if key==self.bootstrap_key and now<self.bootstrap_until:
            return {'ready':True,'phase':'bootstrap','reason':'Waiting for the first exact original HUD and native frame','renew':False,'bootstrap_id':key}
        if key not in self.attempted:
            self.attempted.add(key);self.bootstrap_key=key;self.bootstrap_until=now+BOOTSTRAP_NS
            return {'ready':True,'phase':'bootstrap','reason':'Capturing the first exact original HUD','renew':False,'bootstrap_id':key}
        return off('Exact original HUD or native renderer readiness did not arrive before bootstrap expired')
