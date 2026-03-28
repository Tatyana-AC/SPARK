import argparse
import ctypes
import importlib.util
import json
import os
import shutil
import string
import sys
import urllib.request
import zipfile
from pathlib import Path


FIRMWARE_FILES = (
    "boot.py",
    "jetson_transport.py",
    "protocol.py",
    "upload_protocol.py",
    "serial_bridge.py",
    "typeback.py",
    "usb_config.py",
    "code.py",
)

GITHUB_LATEST_BUNDLE_API = (
    "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"
)


class DeployError(RuntimeError):
    pass


def repo_root():
    return Path(__file__).resolve().parents[1]


def pico_source_dir(repo=None):
    return (repo or repo_root()) / "pico"


def pico_vendor_dir(repo=None):
    return pico_source_dir(repo) / "vendor"


def cached_adafruit_hid_dir(repo=None):
    return pico_vendor_dir(repo) / "adafruit_hid"


def cached_bundle_zip_path(repo=None):
    return pico_vendor_dir(repo) / "adafruit-circuitpython-bundle-py.zip"


def firmware_sources(repo=None):
    source_dir = pico_source_dir(repo)
    sources = [source_dir / name for name in FIRMWARE_FILES]
    missing = [path for path in sources if not path.exists()]
    if missing:
        raise DeployError(
            "Missing firmware source files: {}".format(", ".join(str(path) for path in missing))
        )
    return sources


def detect_target_path(target_override=None):
    if target_override:
        target = Path(target_override).expanduser().resolve()
        if not target.exists():
            raise DeployError(f"Target path does not exist: {target}")
        return target

    mac_target = Path("/Volumes/CIRCUITPY")
    if mac_target.exists():
        return mac_target

    linux_candidates = []
    for root in (Path("/media"), Path("/run/media")):
        if root.exists():
            linux_candidates.extend(root.glob("*/*"))
    for candidate in linux_candidates:
        if candidate.name == "CIRCUITPY" and candidate.exists():
            return candidate

    windows_candidates = _find_windows_circuitpy_mounts()
    if len(windows_candidates) == 1:
        return windows_candidates[0]
    if len(windows_candidates) > 1:
        raise DeployError(
            "Multiple CIRCUITPY drives found: {}".format(
                ", ".join(str(path) for path in windows_candidates)
            )
        )

    raise DeployError("Could not find a mounted CIRCUITPY volume")


def _find_windows_circuitpy_mounts():
    if os.name != "nt":
        return []

    kernel32 = ctypes.windll.kernel32
    mounts = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not Path(root).exists():
            continue
        volume_name = ctypes.create_unicode_buffer(261)
        result = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            volume_name,
            len(volume_name),
            None,
            None,
            None,
            None,
            0,
        )
        if result and volume_name.value == "CIRCUITPY":
            mounts.append(Path(root))
    return mounts


def find_local_adafruit_hid(repo=None, library_source=None):
    explicit_candidates = []
    if library_source:
        library_source = Path(library_source).expanduser().resolve()
        explicit_candidates.extend((library_source, library_source / "adafruit_hid"))

    repo = repo or repo_root()
    common_candidates = [
        repo / "lib" / "adafruit_hid",
        repo / "pico" / "lib" / "adafruit_hid",
        cached_adafruit_hid_dir(repo),
    ]

    for candidate in explicit_candidates + common_candidates:
        normalized = _normalize_adafruit_hid_candidate(candidate)
        if normalized is not None:
            return normalized

    spec = importlib.util.find_spec("adafruit_hid")
    if spec and spec.origin:
        normalized = _normalize_adafruit_hid_candidate(Path(spec.origin).resolve().parent)
        if normalized is not None:
            return normalized

    return None


def _normalize_adafruit_hid_candidate(path):
    if not path.exists():
        return None
    if path.is_dir() and path.name == "adafruit_hid" and (path / "__init__.py").exists():
        return path
    nested = path / "adafruit_hid"
    if nested.is_dir() and (nested / "__init__.py").exists():
        return nested
    return None


def fetch_latest_bundle_release():
    request = urllib.request.Request(
        GITHUB_LATEST_BUNDLE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SPARK-Pico-Deploy"},
    )
    response = urllib.request.urlopen(request)
    try:
        payload = response.read().decode("utf-8")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return json.loads(payload)


def select_bundle_asset_url(release_payload):
    for asset in release_payload.get("assets", []):
        name = asset.get("name", "")
        if "bundle-py" in name and name.endswith(".zip"):
            return asset["browser_download_url"]
    raise DeployError("Could not find a source bundle asset in the latest Adafruit release")


def download_bundle_zip(destination):
    release = fetch_latest_bundle_release()
    asset_url = select_bundle_asset_url(release)
    request = urllib.request.Request(asset_url, headers={"User-Agent": "SPARK-Pico-Deploy"})
    response = urllib.request.urlopen(request)
    try:
        destination.write_bytes(response.read())
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return destination


def extract_adafruit_hid_from_bundle(bundle_zip_path, target_lib_dir):
    target_lib_dir = Path(target_lib_dir)
    package_root = target_lib_dir / "adafruit_hid"
    if package_root.exists():
        shutil.rmtree(package_root)

    with zipfile.ZipFile(bundle_zip_path) as archive:
        members = [
            name
            for name in archive.namelist()
            if "/lib/adafruit_hid/" in name and not name.endswith("/")
        ]
        if not members:
            raise DeployError("Downloaded bundle did not contain lib/adafruit_hid")

        prefix = members[0].split("/lib/adafruit_hid/", 1)[0] + "/lib/adafruit_hid/"
        for member in members:
            relative_name = member[len(prefix) :]
            destination = package_root / relative_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source_file, destination.open("wb") as dest_file:
                shutil.copyfileobj(source_file, dest_file)

    return package_root


def ensure_adafruit_hid(target_root, repo=None, library_source=None, dry_run=False):
    target_root = Path(target_root)
    repo = repo or repo_root()
    lib_dir = target_root / "lib"
    target_package = lib_dir / "adafruit_hid"

    source_package = find_local_adafruit_hid(repo, library_source)
    if source_package is not None:
        if dry_run:
            return source_package, target_package, "local"
        copy_package_tree(source_package, target_package)
        return source_package, target_package, "local"

    cache_package = cached_adafruit_hid_dir(repo)
    if dry_run:
        return cache_package, target_package, "download"

    lib_dir.mkdir(parents=True, exist_ok=True)
    vendor_dir = pico_vendor_dir(repo)
    vendor_dir.mkdir(parents=True, exist_ok=True)
    bundle_zip = cached_bundle_zip_path(repo)
    try:
        download_bundle_zip(bundle_zip)
        source_package = extract_adafruit_hid_from_bundle(bundle_zip, vendor_dir)
        copy_package_tree(source_package, target_package)
    except Exception as exc:
        raise DeployError(f"Could not download and install adafruit_hid: {exc}") from exc
    return source_package, target_package, "download"


def copy_package_tree(source_dir, destination_dir):
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, destination_dir)


def copy_firmware_files(target_root, repo=None, dry_run=False):
    repo = repo or repo_root()
    target_root = Path(target_root)
    sources = firmware_sources(repo)
    copies = [(source, target_root / source.name) for source in sources]

    if dry_run:
        return copies

    stale_package_dir = target_root / "pico"
    if stale_package_dir.exists():
        shutil.rmtree(stale_package_dir)

    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    return copies


def run_deploy(target=None, library_source=None, dry_run=False):
    repo = repo_root()
    target_path = detect_target_path(target)
    copies = copy_firmware_files(target_path, repo=repo, dry_run=dry_run)
    library_result = ensure_adafruit_hid(
        target_path,
        repo=repo,
        library_source=library_source,
        dry_run=dry_run,
    )
    return target_path, copies, library_result


def build_parser():
    parser = argparse.ArgumentParser(description="Deploy SPARK CircuitPython firmware to a Pico")
    parser.add_argument("--target", help="Mounted CIRCUITPY path override")
    parser.add_argument("--library-source", help="Path containing an adafruit_hid package")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without copying")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Accepted for compatibility; deployment already overwrites target files non-interactively",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        target_path, copies, library_result = run_deploy(
            target=args.target,
            library_source=args.library_source,
            dry_run=args.dry_run,
        )
    except DeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Target: {target_path}")
    for source, destination in copies:
        action = "Would copy" if args.dry_run else "Copied"
        print(f"{action}: {source.name} -> {destination}")

    source_package, target_package, mode = library_result
    if args.dry_run:
        if mode == "local":
            print(f"Would copy local adafruit_hid: {source_package} -> {target_package}")
        else:
            print(f"Would download adafruit_hid into repo cache: {source_package}")
            print(f"Would copy cached adafruit_hid to: {target_package}")
    else:
        if mode == "local":
            print(f"Installed adafruit_hid from local source: {source_package}")
        else:
            print(f"Downloaded and cached adafruit_hid at: {source_package}")
            print(f"Installed adafruit_hid into: {target_package}")

    if not args.dry_run:
        print("Deployment complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
