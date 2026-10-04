# Past Paper Studio Beta 1.0 — macOS build

The standalone application is `dist/beta1/Past Paper Studio.app`. The drag-to-install disk image is `dist/Past Paper Studio Beta 1.0-arm64.dmg`; its SHA-256 checksum is stored alongside it. Drag the application into Applications. Python does not need to be installed on the destination Mac.

## Compatibility and distribution

This build requires Apple Silicon and **macOS 26 or later**. It was tested on this Mac running macOS 27. Scanning 741 native binaries confirmed that the bundled Homebrew Python runtime and some libraries require macOS 26; this is reflected in the application metadata. The bundle is approximately 1.2 GiB, and the compressed installer approximately 490 MiB. Most of the footprint is the included OCR and scientific runtime.

The beta is locally ad-hoc signed, with its sealed resources verified. It is not a Developer ID signed or notarized public release. Public distribution still requires those steps and an Apple developer signing identity.

## Icons and startup

The paper monogram is drawn as vector geometry, inspired by the supplied references. Xcode's asset compiler compiled native light, dark and automatic tinted appearances, with lighting and translucent/glass layers, into Assets.car. The fallback ICNS is also included. The actual appearance selected by macOS follows the operating system's icon presentation settings. While PPS runs, the Dock icon is updated from the active PPS theme using Qt.

OCR initialization is deferred until scanned papers need it. Startup no longer imports the OCR runtime as a warm-up step. The existing startup animation and full-screen preferences remain available. In isolated smoke checks, the usable main window took roughly 0.9–2.4 seconds after the Python launch entry point; these measurements exclude bootloader overhead and the normal splash sequence and are not a guarantee of cold-start time.

## Data and checks

Personal settings, API keys, profile pictures, saved attempts and caches are not packaged. They remain in existing external user data locations; the legacy data directory name is retained for compatibility. Keep the source project as the editable development copy.

Validation included 81 focused source tests, separate source/frozen/native-window smoke runs, and a smoke run from the mounted installer. Checks exercised the main window, Settings, profile persistence, five languages, theme switching, Dashboard/results navigation and a synthetic PDF rendered through the actual separate PDF worker. PaddleOCR/Paddle and the AI SDK imported successfully in the frozen app. Native asset metadata, code signatures and installer integrity were inspected.

Live archive searches, AI grading requests and recognition using downloaded OCR models were not exercised. AI features require configured credentials and connectivity. OCR models may download on first use.

## Rebuild

The canonical specification is `Past Paper Studio Beta 1.0.spec`; the Core specification delegates to it. Build with Python 3.11 in a dedicated virtual environment. The existing build environment is `/private/tmp/pps-beta1-build-env`; pinned dependencies are in `packaging/macos-requirements.lock`.

```sh
python3.11 -m venv .venv-macos-build
.venv-macos-build/bin/python -m pip install -r packaging/macos-requirements.lock
.venv-macos-build/bin/python tools/build_macos.py --native-icons --developer-dir /Applications/Xcode.app/Contents/Developer
```

Full Xcode and its first-launch components are required for native asset compilation. The compiler environment is scoped to the build command; the global command-line developer directory was not changed. The helper includes dependency license notices and signs the resulting app locally. The lock pins Python packages, not the host Python framework or macOS deployment targets; inspect native runtime compatibility when rebuilding elsewhere.

To make the installer, place the app, an Applications symlink and installation instructions into `build/dmg_staging`, then run:

```sh
hdiutil create -volname 'Past Paper Studio Beta 1.0' -srcfolder build/dmg_staging -ov -format UDZO -imagekey zlib-level=6 'dist/Past Paper Studio Beta 1.0-arm64.dmg'
shasum -a 256 'dist/Past Paper Studio Beta 1.0-arm64.dmg' > 'dist/Past Paper Studio Beta 1.0-arm64.dmg.sha256'
```

Changing bundled source or assets requires rebuilding and re-signing the application. Changes to external user settings do not.
