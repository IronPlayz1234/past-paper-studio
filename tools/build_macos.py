"""Rebuild the local macOS app and optional native icon using the pinned environment."""
import argparse, subprocess, sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--native-icons',action='store_true');parser.add_argument('--developer-dir')
args=parser.parse_args();root=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,str(root/'tools/generate_app_icons.py')],cwd=root,check=True)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath','dist/beta1','--workpath','build/beta1',str(root/'Past Paper Studio Beta 1.0.spec')],cwd=root,check=True)
app=root/'dist/beta1/Past Paper Studio.app'
subprocess.run([sys.executable,str(root/'tools/package_notices.py'),'--app',str(app)],cwd=root,check=True)
if args.native_icons:
    command=[sys.executable,str(root/'tools/compile_macos_icon.py'),'--app',str(app)]
    if args.developer_dir:command+=['--developer-dir',args.developer_dir]
    subprocess.run(command,cwd=root,check=True)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
print(app)
