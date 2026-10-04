"""Compile native Icon Composer appearances and merge Apple's generated icon metadata."""
import argparse, plistlib, shutil, subprocess
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--app',required=True);parser.add_argument('--developer-dir')
args=parser.parse_args();root=Path(__file__).resolve().parents[1];app=Path(args.app).resolve()
env=__import__('os').environ.copy()
if args.developer_dir:env['DEVELOPER_DIR']=args.developer_dir
compiler=subprocess.check_output(['xcrun','--find','actool'],env=env,text=True).strip()
out=root/'build/native_icon';out.mkdir(parents=True,exist_ok=True)
subprocess.run([compiler,str(root/'packaging/PastPaperStudio.icon'),'--compile',str(out),
    '--output-format','human-readable-text','--notices','--warnings','--errors',
    '--output-partial-info-plist',str(out/'partial-Info.plist'),'--app-icon','PastPaperStudio',
    '--include-all-app-icons','--platform','macosx','--target-device','mac','--minimum-deployment-target','26.0'],env=env,check=True)
resources=app/'Contents/Resources'
for name in ('Assets.car','PastPaperStudio.icns'):
    if (out/name).exists():shutil.copy2(out/name,resources/name)
plist=app/'Contents/Info.plist'
with plist.open('rb') as f:info=plistlib.load(f)
with (out/'partial-Info.plist').open('rb') as f:info.update(plistlib.load(f))
with plist.open('wb') as f:plistlib.dump(info,f)
# Updating resources invalidates the previous signature; resign before distributing.
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
print('Native light/dark icon compiled into',app)
