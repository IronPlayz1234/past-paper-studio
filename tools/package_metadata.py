"""Keep runtime package version/entrypoint metadata available in a frozen app."""
import argparse, importlib.metadata, shutil
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata
parser=argparse.ArgumentParser();parser.add_argument('--app',required=True);args=parser.parse_args()
app=Path(args.app).resolve();resources=app/'Contents/Resources';frameworks=app/'Contents/Frameworks'
count=0
for distribution in importlib.metadata.distributions():
    for source,dest in copy_metadata(distribution.metadata['Name']):
        target=resources/dest
        if Path(source).is_dir():shutil.copytree(source,target,dirs_exist_ok=True)
        else:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        link=frameworks/dest
        if not link.exists():link.symlink_to(Path('../Resources')/dest,target_is_directory=True)
        count+=1
print('Runtime metadata included:',count,'distributions')
