#!/usr/bin/env python3
"""Read-only clock reconstruction from S1's atomic published state samples."""
import argparse,collections,json,math,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--seconds',type=float,default=8);a=p.parse_args()
    if not 0<a.seconds<=15 or a.output.exists():raise ValueError('Use bounded duration and fresh output')
    started=time.monotonic();samples=[];last=None
    while time.monotonic()-started<a.seconds:
        try:
            value=json.loads(a.state.read_text())
            key=(value['epoch'],value['sample_monotonic_ns'])
            if key!=last and value.get('mode') in {'race','attract'}:
                clock=value.get('real_clock')
                if clock is not None and math.isfinite(clock):
                    samples.append({'time_ns':value['sample_monotonic_ns'],'clock':clock,'raw_dt':value['original_raw_dt'],
                        'smoothed_dt':value['original_smoothed_dt'],'phase':value['mode'],'instances':value.get('instances',[])})
                    last=key
        except (OSError,ValueError,KeyError):pass
        time.sleep(.002)
    if len(samples)<3:raise ValueError('Too few genuine original clock states')
    histogram=collections.Counter();residuals=[];updates=0
    for before,after in zip(samples,samples[1:]):
        delta=after['clock']-before['clock'];n=round(delta/.02)
        residual=abs(delta-n*.02);residuals.append(residual)
        if n<1 or n>10 or residual>.0001:raise ValueError(f'Clock jump is not an original20ms multiple:{delta}')
        histogram[str(n)]+=1;updates+=n
    span=(samples[-1]['time_ns']-samples[0]['time_ns'])/1e9
    first={v['id']:v for v in samples[0]['instances']};last={v['id']:v for v in samples[-1]['instances']}
    changed=[key for key in first.keys()&last.keys() if first[key]['position']!=last[key]['position'] or first[key]['rotation']!=last[key]['rotation']]
    result={'scope':'Input-free automatic original S1 intro/attract; published atomic wait samples. No game timing patches.',
        'observed_clock_states':len(samples),'observed_transitions':len(samples)-1,'elapsed_seconds':span,
        'delta_20ms_multiple_histogram':dict(histogram),'reconstructed_original_timer_updates':updates,
        'reconstructed_updates_hz':updates/span,'observed_distinct_transitions_hz':(len(samples)-1)/span,
        'max_rounding_residual_seconds':max(residuals),'raw_dt_values':sorted({s['raw_dt'] for s in samples}),
        'smoothed_dt_min':min(s['smoothed_dt'] for s in samples),'smoothed_dt_max':max(s['smoothed_dt'] for s in samples),
        'moving_actor_part_ids':changed,'input_api_used':False,
        'limitation':'Clock reconstruction establishes timer-update pacing for this automatic sequence, not player-race physics outcomes or displayed FPS.'}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
