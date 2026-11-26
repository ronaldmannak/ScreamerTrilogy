#!/usr/bin/env python3
"""Restore a verified checkpoint app into a new directory, preserving installed apps."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--game',required=True,choices=['screamer','screamer2','screamerrally'])
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parent.parent
record=next(x for x in json.loads((root/'checkpoints/working-2026-11-24.json').read_text())['games'] if x['game']==a.game)
archive=root/record['archive']
h=hashlib.sha256()
with archive.open('rb') as f:
 for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
if h.hexdigest()!=record['archive_sha256']:raise SystemExit('Archive hash does not match checkpoint')
with zipfile.ZipFile(archive) as z:
 if z.testzip():raise SystemExit('Archive CRC check failed')
 for name in z.namelist():
  path=Path(name)
  if path.is_absolute() or '..' in path.parts:raise SystemExit('Unsafe archive path')
a.output.mkdir(parents=True,exist_ok=False)
subprocess.run(['ditto','-x','-k',str(archive),str(a.output)],check=True)
app=a.output/(record['title']+'.app')
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
print(app)
