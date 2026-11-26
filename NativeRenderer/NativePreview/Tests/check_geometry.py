#!/usr/bin/env python3
"""Check the real projection without starting AppKit, a game, or game inputs."""
from pathlib import Path
import subprocess,tempfile

def main():
    root=Path(__file__).resolve().parent
    source=root.parent/'Sources/NativePreview.mm'
    with tempfile.TemporaryDirectory(prefix='screamer-geometry-') as folder:
        binary=Path(folder)/'geometry-check'
        subprocess.run(['xcrun','clang++','-std=c++17','-fobjc-arc','-mmacosx-version-min=12.0',
            '-DPREVIEW_SOURCE_FILE="'+str(source)+'"',str(root/'geometry_sanity.mm'),'-o',str(binary),
            '-framework','AppKit','-framework','Metal','-framework','MetalKit','-framework','QuartzCore'],check=True)
        subprocess.run([str(binary)],check=True)

if __name__=='__main__':main()
