"""Frozen entry point: dispatch multiprocessing before importing the desktop UI."""
def launch():
    from multiprocessing import freeze_support
    freeze_support()
    import sys
    if not getattr(sys,'frozen',False):
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    if '--bundle-self-test' in sys.argv:
        from tools.bundle_smoke import run
        return run()
    from Core.gui_main import main
    return main()

if __name__=='__main__':
    raise SystemExit(launch())
