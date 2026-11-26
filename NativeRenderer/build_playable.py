#!/usr/bin/env python3
"""Assemble the separate live Rally .app from local sources and owned game data."""
import argparse,json,plistlib,shutil,subprocess
from pathlib import Path

def run(*args):subprocess.run(list(map(str,args)),check=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--version',default='0.3.7')
    p.add_argument('--build-number',type=int,default=12)
    p.add_argument('--engine',type=Path,required=True)
    p.add_argument('--classic-app',type=Path,required=True,help='Owned stable Classic app to embed')
    p.add_argument('--game-root',type=Path,required=True)
    p.add_argument('--python-prefix',type=Path,default=Path('/opt/homebrew/opt/python@3.14'))
    p.add_argument('--initial-scene',type=Path,required=True)
    p.add_argument('--initial-cars',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parent
    if a.build_number<1:p.error('Build number must be positive')
    run('python3',root/'NativePreview/build-native.py','--app-name','Screamer Rally','--bundle-id','local.screamer-rally.metal-player','--scene-dir',a.initial_scene,'--cars-dir',a.initial_cars,'--output',a.output)
    app=a.output/'Screamer Rally.app';resources=app/'Contents/Resources'
    live=resources/'Live';live.mkdir()
    shutil.copy2(root/'Session.py',live/'Session.py')
    for folder,source_folder in [('Execution','Tools/Execution'),('bridge','bridge'),('extractor','extractor')]:
        target=live/folder;target.mkdir()
        for source in (root/source_folder).iterdir():
            if source.is_file() and source.suffix in ('.py','.md'):
                shutil.copy2(source,target/source.name)
    shutil.copy2(root/'hud-profile.json',live/'hud-profile.json')
    shutil.copytree(a.game_root,resources/'game')
    notices=resources/'Licenses';notices.mkdir()
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(root/name,notices/name)
    shutil.copy2(root/'Tools/Engine/LICENSE-DOSBOX',notices/'LICENSE-DOSBOX')
    icon=a.game_root.parent/'GameIcon.icns'
    if icon.is_file():shutil.copy2(icon,resources/'GameIcon.icns')
    (resources/'LiveConfig.json').write_text(json.dumps({'enabled':True,'physics_wait_ticks':3,'render_fps':60,'render_4k':False})+'\n')
    info=app/'Contents/Info.plist';j=plistlib.loads(info.read_bytes())
    j.update(CFBundleName='Screamer Rally',CFBundleDisplayName='Screamer Rally',
             CFBundleIdentifier='local.screamer-rally.metal-player',CFBundleShortVersionString=a.version,CFBundleVersion=str(a.build_number))
    if icon.is_file():j['CFBundleIconFile']='GameIcon.icns'
    info.write_bytes(plistlib.dumps(j))
    run('python3',root/'Tools/Packaging/bundle_runtime.py','--app',app,'--engine',a.engine,'--python-prefix',a.python_prefix)
    run('python3',root/'Tools/Packaging/bundle_selection.py','--app',app,'--classic-app',a.classic_app,'--game','screamerrally','--version',a.version,'--build-number',a.build_number)
    run('codesign','--force','--sign','-','--timestamp=none',app)
    run('codesign','--verify','--deep','--strict',app)
    print(app)

if __name__=='__main__':main()
