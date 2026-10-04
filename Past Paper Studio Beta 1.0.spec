# Standalone arm64 macOS bundle; never copy personal state, credentials or test fixtures.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata
ROOT=Path(SPECPATH).resolve()
if ROOT.name=='Core': ROOT=ROOT.parent
icon=str(ROOT/'UI/assets/app_icons/PastPaperStudio.icns')
datas=[(str(ROOT/'UI/assets'),'UI/assets'),(str(ROOT/'Data/igcse_components_master.json'),'Data')]
hiddenimports=[]
binaries=[]
for package in ('Core','UI','Data','Utils','Grading'):
    hiddenimports+=collect_submodules(package)
for package in ('paddleocr','paddle'):
    datas+=collect_data_files(package,include_py_files=(package=='paddleocr'))
    binaries+=collect_dynamic_libs(package)
    hiddenimports+=collect_submodules(package)
# OCR/image libraries read installed distribution metadata at runtime.
import importlib.metadata
for distribution in importlib.metadata.distributions():
    datas+=copy_metadata(distribution.metadata['Name'])
a=Analysis([str(ROOT/'packaging/macos_launcher.py')],pathex=[str(ROOT)],
           datas=datas,binaries=binaries,hiddenimports=hiddenimports,
           excludes=['tkinter','pytest','IPython','notebook','torch','tensorflow'],
           hooksconfig={},noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Past Paper Studio',
        console=False,argv_emulation=False,upx=False,target_arch='arm64',
        codesign_identity=None,icon=icon)
coll=COLLECT(exe,a.binaries,a.datas,name='Past Paper Studio',upx=False)
app=BUNDLE(coll,name='Past Paper Studio.app',icon=icon,
           bundle_identifier='org.pastpaperstudio.desktop',
           info_plist={'CFBundleDisplayName':'Past Paper Studio','CFBundleShortVersionString':'1.0.0',
                       'CFBundleVersion':'100','NSHighResolutionCapable':True,
                       'LSMinimumSystemVersion':'26.0','NSPrincipalClass':'NSApplication'})
