#!/usr/bin/env python3
"""Build an ARM64 Metal track preview without an Xcode project."""
import argparse,json,plistlib,shutil,subprocess
from pathlib import Path

def run(*args):
 return subprocess.run([str(x) for x in args],check=True)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent.parent/'build')
 p.add_argument('--app-name',default='Screamer Rally Metal Preview',help='Bundle filename without .app')
 p.add_argument('--bundle-id',default='local.screamer-rally.metal-preview')
 p.add_argument('--scene-dir',type=Path)
 p.add_argument('--cars-dir',type=Path,help='Optional original-car local meshes and captured root transforms')
 p.add_argument('--replay',type=Path,help='Optional captured camera replay to bundle (game data; keep local)')
 a=p.parse_args();root=Path(__file__).resolve().parent
 a.output.mkdir(parents=True,exist_ok=True)
 if '/' in a.app_name or a.app_name in ('','.', '..'):raise SystemExit('Invalid app bundle name')
 app=a.output/f'{a.app_name}.app'
 if app.exists():raise SystemExit('Use a fresh output folder; refusing to replace an existing app')
 content=app/'Contents';(content/'MacOS').mkdir(parents=True);(content/'Resources').mkdir()
 run('xcrun','clang++','-std=c++17','-arch','arm64','-mmacosx-version-min=12.0','-fobjc-arc','-O2','-g','-Wall','-Wextra','-Werror','-framework','AppKit','-framework','Metal','-framework','MetalKit','-framework','QuartzCore',root/'Sources/NativePreview.mm','-o',content/'MacOS/RallyMetalPreview')
 shutil.copyfile(root/'Sources/World.metal',content/'Resources/World.metal')
 if a.scene_dir:
  if not (a.scene_dir/'scene.json').is_file():raise SystemExit('Scene directory has no scene.json')
  shutil.copytree(a.scene_dir,content/'Resources/Scene')
 if a.replay:
  (content/'Resources/Replay').mkdir()
  shutil.copyfile(a.replay,content/'Resources/Replay/replay.json')
 if a.cars_dir:
  if not (a.cars_dir/'scene.json').is_file():raise SystemExit('Car scene directory has no scene.json')
  shutil.copytree(a.cars_dir,content/'Resources/Cars')
 info={'CFBundleDevelopmentRegion':'en','CFBundleName':'Rally Metal Preview','CFBundleDisplayName':a.app_name,'CFBundleExecutable':'RallyMetalPreview','CFBundleIdentifier':a.bundle_id,'CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1','LSMinimumSystemVersion':'12.0','LSRequiresNativeExecution':True,'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','NSHumanReadableCopyright':'Experimental renderer. Original game data belongs to its rights holders.'}
 with (content/'Info.plist').open('wb') as f:plistlib.dump(info,f)
 run('codesign','--force','--sign','-','--timestamp=none',app)
 run('codesign','--verify','--deep','--strict',app)
 print(app)
if __name__=='__main__':main()
