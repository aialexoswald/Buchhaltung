# PyInstaller-Bauplan für die Mac-App:  pyinstaller --noconfirm packaging/Buchhaltung.spec
import os

from PyInstaller.utils.hooks import collect_data_files

WURZEL = os.path.abspath(os.path.join(SPECPATH, ".."))
PAKET = os.path.join(WURZEL, "buchhaltung")
VERSION = os.environ.get("BUCHHALTUNG_VERSION", "1.0")

a = Analysis(
    [os.path.join(SPECPATH, "mac_start.py")],
    pathex=[WURZEL],
    datas=[
        (os.path.join(PAKET, "templates"), "buchhaltung/templates"),
        (os.path.join(PAKET, "static"), "buchhaltung/static"),
        (os.path.join(PAKET, "schema.sql"), "buchhaltung"),
        *collect_data_files("reportlab"),
    ],
    hiddenimports=["buchhaltung.ansichten"],
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Buchhaltung", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Buchhaltung")
app = BUNDLE(
    coll,
    name="Buchhaltung.app",
    bundle_identifier="at.futura.buchhaltung",
    version=VERSION,
    info_plist={
        # Kein Dock-Symbol: die Oberfläche läuft im Browser, beendet wird über „Beenden“
        "LSUIElement": True,
        "CFBundleDisplayName": "Buchhaltung",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
    },
)
