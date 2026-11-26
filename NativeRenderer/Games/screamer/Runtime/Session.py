#!/usr/bin/env python3
"""Bundled native frontend entry point for the private S1 engine and bridge."""
import argparse
import os
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('resources','session-dir','data-dir'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--parent-pid',required=True,type=int)
    p.add_argument('--diagnostic-read-only',action='store_true')
    a=p.parse_args();resources=a.resources.resolve(strict=True)
    content=Path(os.environ.get('SCREAMER_CONTENT_ROOT', str(resources))).resolve(strict=True)
    tools=resources/'Live/Tools';sys.path.insert(0,str(tools))
    from session_s1 import main as session_main
    sys.argv=[str(tools/'session_s1.py'),'--engine',str(resources.parent/'MacOS/dosbox'),
        '--game-root',str(content/'game'),'--scenes-root',str(content/'S1Scenes'),
        '--session-dir',str(a.session_dir),'--data-dir',str(a.data_dir),'--parent-pid',str(a.parent_pid)]
    if a.diagnostic_read_only:sys.argv+=['--diagnostic-read-only']
    return session_main()


if __name__=='__main__':raise SystemExit(main())
