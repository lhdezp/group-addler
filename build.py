import sys
import os
import shutil
import tempfile
import uuid
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))

for d in ["build", "dist"]:
    if os.path.isdir(d) and os.listdir(d):
        shutil.rmtree(d, ignore_errors=True)

print("=" * 50)
print("  Group Addler - Building Windows EXE")
print("=" * 50)
print()

from flet_cli.__pyinstaller.utils import copy_flet_bin, get_flet_bin_path
import flet_cli.__pyinstaller.config as hook_config

print("[1/3] Copying Flet desktop binaries...")
bin_path = get_flet_bin_path()
if bin_path:
    print(f"  Flet bin found at: {bin_path}")
    hook_config.temp_bin_dir = copy_flet_bin()
    if hook_config.temp_bin_dir:
        fletd_path = os.path.join(
            hook_config.temp_bin_dir, "fletd.exe"
        )
        if os.path.exists(fletd_path):
            os.remove(fletd_path)
        print(f"  Copied to temp: {hook_config.temp_bin_dir}")
else:
    print("  Warning: Flet desktop binaries not found, continuing anyway...")
    hook_config.temp_bin_dir = None

print("[2/3] Running PyInstaller...")

pyi_args = [
    "main.py",
    "--noconfirm",
    "--noconsole",
    "--name", "GroupAddler",
    "--hidden-import", "WPP_Whatsapp",
    "--hidden-import", "WPP_Whatsapp.api",
    "--hidden-import", "WPP_Whatsapp.api.Whatsapp",
    "--hidden-import", "WPP_Whatsapp.api.const",
    "--hidden-import", "WPP_Whatsapp.api.helpers",
    "--hidden-import", "WPP_Whatsapp.api.helpers.decorators",
    "--hidden-import", "WPP_Whatsapp.api.helpers.download_file",
    "--hidden-import", "WPP_Whatsapp.api.helpers.function",
    "--hidden-import", "WPP_Whatsapp.api.helpers.jsFunction",
    "--hidden-import", "WPP_Whatsapp.api.helpers.wa_version",
    "--hidden-import", "WPP_Whatsapp.api.helpers.wapi",
    "--hidden-import", "WPP_Whatsapp.api.layers",
    "--hidden-import", "WPP_Whatsapp.api.layers.BusinessLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.CatalogLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.CommunityLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.ControlsLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.GroupLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.HostLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.LabelsLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.ListenerLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.NewsletterLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.ProfileLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.RetrieverLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.SenderLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.StatusLayer",
    "--hidden-import", "WPP_Whatsapp.api.layers.UILayer",
    "--hidden-import", "WPP_Whatsapp.api.model",
    "--hidden-import", "WPP_Whatsapp.api.model.status_find",
    "--hidden-import", "WPP_Whatsapp.controllers",
    "--hidden-import", "WPP_Whatsapp.controllers.auth",
    "--hidden-import", "WPP_Whatsapp.controllers.browser",
    "--hidden-import", "WPP_Whatsapp.controllers.init_multi",
    "--hidden-import", "WPP_Whatsapp.controllers.initializer",
    "--hidden-import", "WPP_Whatsapp.utils",
    "--hidden-import", "WPP_Whatsapp.utils.batch_operations",
    "--hidden-import", "WPP_Whatsapp.utils.ffmpeg",
    "--hidden-import", "WPP_Whatsapp.utils.rate_limiter",
    "--hidden-import", "playwright",
    "--hidden-import", "playwright._impl",
    "--hidden-import", "playwright._impl._api_structures",
    "--hidden-import", "playwright._impl._browser",
    "--hidden-import", "playwright._impl._browser_context",
    "--hidden-import", "playwright._impl._browser_type",
    "--hidden-import", "playwright._impl._connection",
    "--hidden-import", "playwright._impl._driver",
    "--hidden-import", "playwright._impl._greenlets",
    "--hidden-import", "playwright._impl._playwright",
    "--hidden-import", "playwright._impl._transport",
    "--hidden-import", "playwright._impl._local_utils",
    "--hidden-import", "playwright._impl._stream",
    "--hidden-import", "playwright._impl._json_pipe",
    "--hidden-import", "playwright._impl._errors",
    "--hidden-import", "playwright._impl._helper",
    "--hidden-import", "playwright._impl._path_utils",
    "--hidden-import", "playwright._impl._str_utils",
    "--hidden-import", "playwright._impl._waiter",
    "--hidden-import", "playwright._impl._event_context_manager",
    "--hidden-import", "playwright._impl._sync_base",
    "--hidden-import", "playwright._impl._async_base",
    "--hidden-import", "playwright._impl._selectors",
    "--hidden-import", "playwright._impl._set_input_files_helpers",
    "--hidden-import", "playwright._impl._element_handle",
    "--hidden-import", "playwright._impl._frame",
    "--hidden-import", "playwright._impl._page",
    "--hidden-import", "playwright._impl._network",
    "--hidden-import", "playwright._impl._dialog",
    "--hidden-import", "playwright._impl._download",
    "--hidden-import", "playwright._impl._file_chooser",
    "--hidden-import", "playwright._impl._js_handle",
    "--hidden-import", "playwright._impl._locator",
    "--hidden-import", "playwright._impl._artifact",
    "--hidden-import", "playwright._impl._cdp_session",
    "--hidden-import", "playwright._impl._console_message",
    "--hidden-import", "playwright._impl._web_error",
    "--hidden-import", "playwright._impl._tracing",
    "--hidden-import", "playwright._impl._video",
    "--hidden-import", "playwright._impl._clock",
    "--hidden-import", "playwright._impl._fetch",
    "--hidden-import", "playwright._impl._har_router",
    "--hidden-import", "playwright._impl._impl_to_api_mapping",
    "--hidden-import", "playwright._impl._input",
    "--hidden-import", "playwright._impl._map",
    "--hidden-import", "playwright._impl._object_factory",
    "--hidden-import", "playwright._impl._glob",
    "--hidden-import", "playwright._impl._assertions",
    "--hidden-import", "playwright._repo_version",
    "--hidden-import", "playwright.async_api",
    "--hidden-import", "playwright.async_api._context_manager",
    "--hidden-import", "playwright.async_api._generated",
    "--hidden-import", "playwright.sync_api",
    "--hidden-import", "playwright.sync_api._context_manager",
    "--hidden-import", "playwright.sync_api._generated",
    "--hidden-import", "greenlet",
    "--hidden-import", "click",
    "--hidden-import", "event_emitter_js",
    "--hidden-import", "aiohttp",
    "--hidden-import", "aiohappyeyeballs",
    "--hidden-import", "aiosignal",
    "--hidden-import", "frozenlist",
    "--hidden-import", "msgpack",
    "--collect-data", "playwright",
    "--collect-data", "WPP_Whatsapp",
    "--collect-data", "flet",
    "--collect-data", "flet_cli",
    "--collect-data", "flet_desktop",
    "--collect-data", "event_emitter_js",
]

print(f"  PyInstaller args count: {len(pyi_args)}")
print(f"  Building: main.py -> GroupAddler.exe")
print()

import PyInstaller.__main__
PyInstaller.__main__.run(pyi_args)

print()
print("[3/3] Cleaning up...")
if hook_config.temp_bin_dir and os.path.exists(hook_config.temp_bin_dir):
    print(f"  Removing temp dir: {hook_config.temp_bin_dir}")
    shutil.rmtree(hook_config.temp_bin_dir, ignore_errors=True)

print()
if os.path.isfile("dist/GroupAddler.exe"):
    size_mb = os.path.getsize("dist/GroupAddler.exe") / (1024 * 1024)
    print("=" * 50)
    print("  BUILD COMPLETED SUCCESSFULLY")
    print("=" * 50)
    print(f"  EXE: dist\\GroupAddler.exe ({size_mb:.1f} MB)")
    print()
    print("  Copy GroupAddler.exe to the target machine.")
    print("  Requires Microsoft Edge (preinstalled on Win 11).")
    print("=" * 50)
elif os.path.isdir("dist/GroupAddler"):
    print("=" * 50)
    print("  BUILD COMPLETED SUCCESSFULLY")
    print("=" * 50)
    print("  Folder: dist\\GroupAddler\\GroupAddler.exe")
    print()
    print("  Copy the entire 'GroupAddler' folder to the target.")
    print("  Requires Microsoft Edge (preinstalled on Win 11).")
    print("=" * 50)
else:
    print("  WARNING: Output not found. Check dist/ folder.")
    if os.path.isdir("dist"):
        for item in os.listdir("dist"):
            print(f"    {item}")
