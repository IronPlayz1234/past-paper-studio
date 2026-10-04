"""Reproduce packaged icon assets from the same vector used by the live app."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys, json, subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from UI.app_icon import icon_pixmap
app=QApplication([])
out=Path(__file__).resolve().parents[1]/'UI/assets/app_icons'
out.mkdir(parents=True,exist_ok=True)
palettes={
    'Light':('#F5EFE5','#181817','#181817'),
    'Dark':('#080A0D','#F8F4ED','#F8F4ED'),
    'Coffee':('#62402A','#FFF0D8','#F4AE70'),
    'Library':('#2B2119','#F3E4C7','#CE9B64'),
    'Blue':('#133777','#F3F6FF','#8FB5FF'),
    'Matcha':('#173B2B','#F1F3DF','#80C483'),
    'Violet':('#351568','#F8F0FF','#B899F4'),
    'Crimson':('#551527','#FFEAF0','#EF729C'),
}
for name,(bg,fg,accent) in palettes.items():
    icon_pixmap(1024,background=bg,foreground=fg,accent=accent).save(str(out/f'{name}.png'))
iconset=out/'PastPaperStudio.iconset';iconset.mkdir(exist_ok=True)
for size in (16,32,128,256,512):
    for multiplier in (1,2):
        suffix='@2x' if multiplier==2 else ''
        icon_pixmap(size*multiplier,background=palettes['Light'][0],foreground=palettes['Light'][1],accent=palettes['Light'][2]).save(str(iconset/f'icon_{size}x{size}{suffix}.png'))
subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(out/'PastPaperStudio.icns')],check=True)
# Keep appearance artwork ready for Xcode compilation; PNGs/ICNS alone aren't native variants.
(out/'appearances.json').write_text(json.dumps({'default':'Light.png','dark':'Dark.png','native_compilation':'Requires full Xcode / Icon Composer'},indent=2)+'\n')
print('Created light/dark designs, six themed previews and fallback ICNS:',out)
