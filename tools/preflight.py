#!/usr/bin/env python3
"""Non-destructive macOS dependency hints; never installs, changes settings or connects to a device."""
import ctypes.util
import os
import platform
import shutil
import sys
from pathlib import Path


def main():
    print('System:', platform.platform())
    print('Python:', sys.version.split()[0], 'at', sys.executable)
    print('macOS:', 'yes' if sys.platform == 'darwin' else 'NO (plugin targets macOS)')
    for tool in ('brew', 'code', 'node', 'shortcuts'):
        print('%s:' % tool, shutil.which(tool) or 'not found (may be optional)')
    paths = [os.getenv('SDL2_LIBRARY'), ctypes.util.find_library('SDL2'),
             '/opt/homebrew/lib/libSDL2.dylib',
             '/opt/homebrew/lib/libSDL2-2.0.0.dylib',
             '/usr/local/lib/libSDL2.dylib']
    matches = [x for x in paths if x and (os.path.exists(x) or x == ctypes.util.find_library('SDL2'))]
    print('SDL2 candidates:', ', '.join(matches) if matches else 'not found; on macOS consider brew install sdl2')
    if sys.platform == 'darwin':
        apps = [str(p) for root in ('/Applications', str(Path.home() / 'Applications'))
                for p in Path(root).glob('*Rhino*.app') if p.is_dir()]
        print('Rhino apps (heuristic):', ', '.join(apps) if apps else 'not found in common application folders')
    print('This check made no changes. Review AGENTS.md before installation.')

if __name__ == '__main__':
    main()
