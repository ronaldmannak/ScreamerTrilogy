#!/usr/bin/env python3
"""Read-only bounded game-clock/player telemetry observation; sends no keys."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.dont_write_bytecode=True
from live_api import LiveAPI,NotReady
from live_bridge import Layout,PoseFeed,atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--layout',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=5)
    parser.add_argument('--rate-hz',type=float,default=200)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 0<args.seconds<=30 or not 1<=args.rate_hz<=500:parser.error('Observation is limited to30s and500Hz')
    layout=Layout(json.loads(args.layout.read_text()));feed=PoseFeed(LiveAPI(args.base_url),layout)
    start=time.monotonic();due=start;last=None;samples=[];errors=[]
    while time.monotonic()-start<args.seconds:
        try:
            value=feed.read();key=(value['status'],value['flags'],value['frame_clock_bits'])
            if key!=last:
                samples.append({key:value[key] for key in ['sample_monotonic_ns','status','flags','race_state','track_id',
                    'real_clock','simulation_clock','frame_clock_bits','player_telemetry','acquisition_ms','consistency']})
                last=key
        except NotReady:pass
        except (OSError,ValueError,KeyError) as error:
            if len(errors)<20:errors.append(str(error))
        due+=1/args.rate_hz
        delay=due-time.monotonic()
        if delay>0:time.sleep(delay)
        elif delay<-.1:due=time.monotonic()
    elapsed=time.monotonic()-start
    report={'schema':'screamer-live-observation/v1','scope':'Read-only atomicwait snapshots; no key/frame/physics writes or input automation',
            'elapsed_seconds':elapsed,'requested_poll_hz':args.rate_hz,'attempts':feed.attempts,'not_ready':feed.not_ready,
            'distinct_real_race_clock_states':feed.unique_clocks,'observed_active_race_seconds':feed.active_race_ns/1e9,
            'observed_clock_transitions':feed.clock_transitions,
            'observed_clock_transitions_hz':feed.clock_transitions/(feed.active_race_ns/1e9) if feed.active_race_ns else None,
            'errors':errors,'samples':samples,'layout_session':layout.metadata.get('session_id',layout.metadata.get('epoch')),
            'limits':['Clock transitions are an observation lowerbound ifwaitwindows are missed','Speed is gameunits,not inventedkm/h; gear is rawgameindex','Smoothedsimulationdt contains original1.1factor; configuredminimumwait is3/100s']}
    atomic_json(args.output,report)
    print(json.dumps({key:report[key] for key in report if key!='samples'},indent=2))


if __name__=='__main__':main()
