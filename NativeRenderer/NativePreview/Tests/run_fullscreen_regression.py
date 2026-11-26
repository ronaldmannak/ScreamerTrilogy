#!/usr/bin/env python3
"""Build and run the production AppKit/Metal fullscreen probe in a fresh directory."""
import argparse,json,plistlib,subprocess,time
from pathlib import Path
from assert_fullscreen_geometry import check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source','scene','shader','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--original-aspect',action='store_true');p.add_argument('--cars',type=Path);p.add_argument('--compile-only',action='store_true');a=p.parse_args()
    source=a.source.resolve(strict=True);scene=a.scene.resolve(strict=True);shader=a.shader.resolve(strict=True);root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    app=root/'FullscreenRegression.app';binary=app/'Contents/MacOS/FullscreenRegression';binary.parent.mkdir(parents=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.screamer.fullscreen-regression','CFBundleName':'FullscreenRegression','CFBundleExecutable':'FullscreenRegression','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'14.0','NSPrincipalClass':'NSApplication'}))
    harness=Path(__file__).with_name('ProductionFullscreenRegression.mm')
    command=['xcrun','clang++','-std=c++17','-O1','-fobjc-arc','-mmacosx-version-min=14.0','-DPREVIEW_SOURCE_FILE="'+str(source)+'"','-framework','AppKit','-framework','Metal','-framework','MetalKit','-framework','QuartzCore',str(harness),'-o',str(binary)]
    (root/'compile-command.json').write_text(json.dumps(command,indent=2)+'\n');subprocess.run(command,check=True)
    if a.compile_only:print(binary);return
    args=[str(binary),'--scene',str(scene),'--shader',str(shader),'--log',str(root/'geometry.jsonl'),'--report',str(root/'performance.json')]
    if a.original_aspect:args+=['--original-aspect']
    if a.cars:args+=['--cars',str(a.cars.resolve(strict=True))]
    start=time.monotonic();result={'maximum_seconds':30}
    with(root/'stdout.log').open('wb')as out:
        try:process=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=30);result.update(exit_code=process.returncode,timeout=False)
        except subprocess.TimeoutExpired:result.update(exit_code=None,timeout=True)
    result['wall_seconds']=time.monotonic()-start;(root/'run.json').write_text(json.dumps(result,indent=2)+'\n')
    summary=check(root/'geometry.jsonl',root/'run.json',source,widescreen=not a.original_aspect);(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
