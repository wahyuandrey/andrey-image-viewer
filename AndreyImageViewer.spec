# -*- mode: python ; coding: utf-8 -*-

import os

# Tentukan lokasi folder binari vips Anda
vips_bin_dir = r"C:\vips\vips-dev-8.18\bin"

# Ambil semua file DLL atau file biner yang ada di dalam folder bin vips
vips_binaries = []
if os.path.exists(vips_bin_dir):
    for f in os.listdir(vips_bin_dir):
        if f.endswith(('.dll', '.exe', '.lib')):
            full_path = os.path.join(vips_bin_dir, f)
            # Masukkan ke dalam format tuple PyInstaller: (path_asal, folder_tujuan_di_exe)
            vips_binaries.append((full_path, '.'))

a = Analysis(
    ['andrey_image_viewer.py'],
    pathex=[],
    binaries=vips_binaries,  # <-- Masukkan biner vips di sini
    datas=[],
    hiddenimports=['pyvips', 'cffi', 'tifffile', 'cv2', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 1. Perhatikan pada EXE: TIDAK menyertakan a.binaries dan a.datas di sini
exe = EXE(
    pyz,
    a.scripts,
    [],
    name='Andrey Image Viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='lib',
)

# 2. Tambahkan blok COLLECT di bawah EXE untuk mengumpulkan semuanya ke dalam satu folder
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Andrey Image Viewer',  # Nama folder hasil akhir di dalam folder 'dist'
    contents_directory='lib',  # <-- Mengubah folder _internal menjadi folder "lib"
)
