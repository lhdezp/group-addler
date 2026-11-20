from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BINARY_SUFFIXES = {".dll", ".so", ".dylib"}


def _resolve_package_dir(package: str) -> Path | None:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def _collect_proto_files(proto_dir: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Return PyInstaller --add-data entries and hidden imports for neonize protos.

    neonize's generated modules import each other as top-level modules
    (``import waE2E``), so every proto folder must be importable and present as
    data in the bundle.
    """
    datas: list[tuple[str, str]] = []
    submodules: list[str] = []

    for entry in sorted(proto_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("__"):
            continue
        submodules.append(entry.name)
        for file in sorted(entry.glob("*.py")):
            destination = f"neonize/proto/{entry.name}/{file.name}"
            datas.append((str(file), destination))

    return datas, submodules


def main() -> int:
    if sys.platform != "win32":
        print("This build script only packages the Windows desktop app.")
        print("Run it from Windows with a Windows virtual environment.")
        return 1

    os.chdir(PROJECT_ROOT)

    for directory in ("build", "dist"):
        path = PROJECT_ROOT / directory
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    print("=" * 50)
    print("  Group Addler - Building Windows EXE")
    print("=" * 50)
    print()

    neonize_dir = _resolve_package_dir("neonize")
    if neonize_dir is None:
        print("Error: neonize is not installed in the active environment.")
        print("Run: uv sync --group dev")
        return 1

    proto_dir = neonize_dir / "proto"
    if not proto_dir.is_dir():
        print(f"Error: neonize proto directory not found at {proto_dir}")
        return 1

    native_libs = [
        path.name
        for path in neonize_dir.iterdir()
        if path.is_file() and path.suffix in BINARY_SUFFIXES
    ]
    if not native_libs:
        print("Warning: no neonize native library found. The app may try to")
        print("download it at runtime and fail without internet access.")

    print("[1/3] Copying Flet desktop binaries...")
    try:
        from flet_cli.__pyinstaller import config as hook_config
        from flet_cli.__pyinstaller.utils import copy_flet_bin, get_flet_bin_path
    except ImportError:
        print("Error: flet-cli is required to build the executable.")
        print("Run: uv sync --group dev")
        return 1

    bin_path = get_flet_bin_path()
    if bin_path:
        print(f"  Flet bin found at: {bin_path}")
        hook_config.temp_bin_dir = copy_flet_bin()
        if hook_config.temp_bin_dir:
            fletd_path = os.path.join(hook_config.temp_bin_dir, "fletd.exe")
            if os.path.exists(fletd_path):
                os.remove(fletd_path)
            print(f"  Copied to temp: {hook_config.temp_bin_dir}")
    else:
        print("  Warning: Flet desktop binaries not found, continuing anyway...")
        hook_config.temp_bin_dir = None

    print("[2/3] Running PyInstaller...")

    proto_datas, proto_submodules = _collect_proto_files(proto_dir)
    hidden_imports = ["segno", "magic", *proto_submodules]

    pyi_args = [
        "main.py",
        "--noconfirm",
        "--noconsole",
        "--name",
        "GroupAddler",
        "--path",
        str(proto_dir),
        "--collect-submodules",
        "neonize",
        "--collect-data",
        "neonize",
        "--collect-data",
        "flet",
        "--collect-data",
        "flet_cli",
        "--collect-data",
        "flet_desktop",
    ]
    for source, destination in proto_datas:
        pyi_args.extend(["--add-data", f"{source};{destination}"])
    for module in hidden_imports:
        pyi_args.extend(["--hidden-import", module])

    print(f"  PyInstaller args count: {len(pyi_args)}")
    print("  Building: main.py -> GroupAddler.exe")
    print()

    import PyInstaller.__main__

    PyInstaller.__main__.run(pyi_args)

    print()
    print("[3/3] Cleaning up...")
    if hook_config.temp_bin_dir and os.path.exists(hook_config.temp_bin_dir):
        print(f"  Removing temp dir: {hook_config.temp_bin_dir}")
        shutil.rmtree(hook_config.temp_bin_dir, ignore_errors=True)

    executable = PROJECT_ROOT / "dist" / "GroupAddler" / "GroupAddler.exe"
    if executable.is_file():
        print()
        print("=" * 50)
        print("  BUILD COMPLETED SUCCESSFULLY")
        print("=" * 50)
        print(f"  Folder: {executable.parent}")
        print()
        print("  Copy the entire 'GroupAddler' folder to the target machine.")
        print("=" * 50)
        return 0

    print()
    print("WARNING: Output not found. Check the dist/ folder.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
