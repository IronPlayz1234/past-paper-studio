"""Copy installed dependency license notices into a completed local app bundle."""
import argparse, importlib.metadata, json, shutil
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--app',required=True);args=parser.parse_args()
out=Path(args.app)/'Contents/Resources/ThirdPartyLicenses';out.mkdir(parents=True,exist_ok=True)
rows=[]
for distribution in importlib.metadata.distributions():
    name=distribution.metadata.get('Name','unknown')
    if name.lower() in {'pip','setuptools','wheel','pyinstaller','pyinstaller-hooks-contrib','macholib','altgraph'}:continue
    row={'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See included package notices'}
    if len(row['license'])>1000:row['license']='See included package notices'
    rows.append(row)
    for item in distribution.files or []:
        if any(part.lower() in {'licenses','license','licence','copying','notice'} for part in item.parts) or item.name.lower().startswith(('license','licence','copying','notice')):
            source=Path(distribution.locate_file(item))
            if source.is_file():
                target=out/name/item.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
(out/'packages.json').write_text(json.dumps(sorted(rows,key=lambda r:r['name'].lower()),indent=2)+'\n')
print('Dependency notices added:',len(rows),'packages')
