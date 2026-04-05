import argparse
import ctypes
import importlib.util
import json
import os
import shutil
import string
import sys
import time
import urllib.request
import zipfile
from pathlib import Path


FIRMWARE_FILES = (
    "boot.py",
    "jetson_transport.py",
    "pico_debug.py",
    "protocol.py",
    "runtime_runner.py",
    "upload_protocol.py",
    "serial_bridge.py",
    "usb_config.py",
    "code.py",
)

RUNTIME_LIBRARY_PATHS = (
    "adafruit_hid",
)

PRESERVE_PATHS = (
    "boot_out.txt",
    "System Volume Information/",
    ".Trashes/",
    ".Spotlight-V100/",
    ".fseventsd/",
)

GITHUB_LATEST_BUNDLE_API = (
    "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"
)
TRANSIENT_COPY_RETRIES = 5
TRANSIENT_COPY_SLEEP_S = 1.0


class DeployError(RuntimeError):
    pass


def repo_root():
    return Path(__file__).resolve().parents[2]


def pico_source_dir(repo=None):
    return (repo or repo_root()) / "pico"


def pico_vendor_dir(repo=None):
    return (repo or repo_root()) / "tools" / "pico" / "vendor"


def cached_adafruit_hid_dir(repo=None):
    return pico_vendor_dir(repo) / "adafruit_hid"


def cached_bundle_zip_path(repo=None):
    return pico_vendor_dir(repo) / "adafruit-circuitpython-bundle-py.zip"


def cached_runtime_library_paths(repo=None):
    vendor_dir = pico_vendor_dir(repo)
    return [vendor_dir / relative_path for relative_path in RUNTIME_LIBRARY_PATHS]


def default_runtime_manifest():
    return FIRMWARE_FILES


def default_preserve_paths():
    return PRESERVE_PATHS


def normalize_target_relpath(path):
    return str(path).replace("\\", "/").strip("/").lower()


def is_preserved_path(path, preserve_paths=None):
    normalized = normalize_target_relpath(path)
    for preserve_path in preserve_paths or default_preserve_paths():
        entry = str(preserve_path).replace("\\", "/")
        is_dir = entry.endswith("/")
        normalized_entry = normalize_target_relpath(entry)
        if is_dir:
            if normalized == normalized_entry or normalized.startswith(normalized_entry + "/"):
                return True
            continue
        if normalized == normalized_entry:
            return True
    return False


def _relative_target_path(path):
    return Path(normalize_target_relpath(path)) if normalize_target_relpath(path) else Path()


def iter_target_files_from_source(source_path, target_relative_root):
    source_path = Path(source_path)
    target_relative_root = _relative_target_path(target_relative_root)
    if source_path.is_dir():
        for child in sorted(source_path.rglob("*")):
            if child.is_file():
                yield normalize_target_relpath(target_relative_root / child.relative_to(source_path))
        return
    yield normalize_target_relpath(target_relative_root)


def iter_library_target_files_from_sources(source_paths, target_paths):
    for source_path, target_path in zip(source_paths, target_paths):
        yield from iter_target_files_from_source(source_path, target_path)


def build_source_plan(repo=None, library_source=None):
    repo = repo or repo_root()
    firmware = [(source, Path(source.name)) for source in firmware_sources(repo)]
    source_paths, target_paths, mode = resolve_runtime_library_sources(repo=repo, library_source=library_source)
    return {
        "firmware": firmware,
        "library_sources": source_paths,
        "library_targets": [Path("lib") / Path(relative_path).name for relative_path in RUNTIME_LIBRARY_PATHS],
        "library_mode": mode,
    }


def default_desired_target_paths_from_source_plan(source_plan):
    desired = {
        normalize_target_relpath(destination)
        for _, destination in source_plan["firmware"]
    }
    desired.update(
        iter_library_target_files_from_sources(
            source_plan["library_sources"],
            source_plan["library_targets"],
        )
    )
    return desired


def _desired_directory_paths(desired_paths):
    directories = set()
    for desired_path in desired_paths:
        path = _relative_target_path(desired_path)
        for parent in path.parents:
            if str(parent) == ".":
                continue
            directories.add(normalize_target_relpath(parent))
    return directories


def find_stale_target_paths(target_root, desired_paths, preserve_paths=None):
    target_root = Path(target_root)
    desired_paths = {normalize_target_relpath(path) for path in desired_paths}
    desired_directories = _desired_directory_paths(desired_paths)
    stale_paths = []

    for path in sorted(target_root.rglob("*")):
        rel = normalize_target_relpath(path.relative_to(target_root))
        if path.is_file():
            if rel in desired_paths or is_preserved_path(rel, preserve_paths):
                continue
            stale_paths.append(path)

    for path in sorted(target_root.rglob("*"), key=lambda entry: len(entry.relative_to(target_root).parts), reverse=True):
        if not path.is_dir():
            continue
        rel = normalize_target_relpath(path.relative_to(target_root))
        if not rel or rel in desired_directories or is_preserved_path(rel, preserve_paths):
            continue
        if any(child not in stale_paths and child.exists() for child in path.iterdir()):
            continue
        stale_paths.append(path)

    return stale_paths


def delete_stale_paths(stale_paths):
    for path in stale_paths:
        _remove_existing_path(path)


def exact_sync_cleanup(target_root, desired_paths, preserve_paths=None):
    stale_paths = find_stale_target_paths(target_root, desired_paths, preserve_paths)
    delete_stale_paths(stale_paths)


def _source_size_bytes(source_path):
    source_path = Path(source_path)
    if source_path.is_dir():
        return sum(child.stat().st_size for child in source_path.rglob("*") if child.is_file())
    return source_path.stat().st_size


def plan_copy_bytes(source_plan):
    total = 0
    for source, _ in source_plan["firmware"]:
        total += _source_size_bytes(source)
    for source in source_plan["library_sources"]:
        total += _source_size_bytes(source)
    return total


def target_free_bytes(target_path):
    return shutil.disk_usage(target_path).free


def needs_space_cleanup(target_path, source_plan):
    return target_free_bytes(target_path) < plan_copy_bytes(source_plan)


def still_insufficient_space(target_path, source_plan):
    return target_free_bytes(target_path) < plan_copy_bytes(source_plan)


def build_copy_plan(target_root, source_plan):
    target_root = Path(target_root)
    support_copies = []
    code_copy = []

    for source, relative_destination in source_plan["firmware"]:
        copy = (source, target_root / relative_destination)
        if Path(relative_destination).name == "code.py":
            code_copy.append(copy)
        else:
            support_copies.append(copy)

    support_copies.extend(
        (source_path, target_root / target_path)
        for source_path, target_path in zip(
            source_plan["library_sources"],
            source_plan["library_targets"],
        )
    )

    return support_copies, code_copy


def copy_planned_files(copies):
    for source, destination in copies:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).is_dir():
            copy_library_path(source, destination)
            continue
        _copy_with_retry(source, destination)


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
    return extract_required_libraries_from_bundle(
        bundle_zip_path,
        target_lib_dir,
        required_paths=("adafruit_hid",),
    )[0]


def extract_required_libraries_from_bundle(bundle_zip_path, target_lib_dir, required_paths=None):
    target_lib_dir = Path(target_lib_dir)
    required_paths = tuple(required_paths or RUNTIME_LIBRARY_PATHS)
    extracted = []

    with zipfile.ZipFile(bundle_zip_path) as archive:
        names = archive.namelist()
        for relative_path in required_paths:
            destination = target_lib_dir / relative_path
            _remove_existing_path(destination)
            _extract_bundle_path(archive, names, relative_path, destination)
            extracted.append(destination)

    return extracted


def _extract_bundle_path(archive, names, relative_path, destination):
    normalized = relative_path.replace("\\", "/")
    if normalized.endswith(".py"):
        suffix = f"/lib/{normalized}"
        matches = [name for name in names if name.endswith(suffix)]
        if not matches:
            raise DeployError(f"Downloaded bundle did not contain lib/{normalized}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(matches[0]) as source_file, destination.open("wb") as dest_file:
            shutil.copyfileobj(source_file, dest_file)
        return

    marker = f"/lib/{normalized}/"
    matches = [name for name in names if marker in name and not name.endswith("/")]
    if not matches:
        raise DeployError(f"Downloaded bundle did not contain lib/{normalized}")

    prefix = matches[0].split(marker, 1)[0] + marker
    for member in matches:
        relative_name = member[len(prefix) :]
        target_path = destination / relative_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source_file, target_path.open("wb") as dest_file:
            shutil.copyfileobj(source_file, dest_file)


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
    copy_library_path(source_dir, destination_dir)


def copy_library_path(source_path, destination_path):
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    _remove_existing_path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, destination_path)
        return
    shutil.copy2(source_path, destination_path)


def _remove_existing_path(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _resolve_library_source_paths(repo=None, library_source=None):
    repo = repo or repo_root()
    explicit_root = Path(library_source).expanduser().resolve() if library_source else None
    resolved = []

    for relative_path in RUNTIME_LIBRARY_PATHS:
        candidates = []
        if explicit_root is not None:
            candidates.append(explicit_root / relative_path)
        candidates.extend(
            (
                repo / "lib" / relative_path,
                repo / "pico" / "lib" / relative_path,
                pico_vendor_dir(repo) / relative_path,
            )
        )
        if relative_path == "adafruit_hid":
            imported = find_local_adafruit_hid(repo, library_source)
            if imported is not None:
                candidates.insert(0, imported)

        match = next((candidate for candidate in candidates if candidate.exists()), None)
        if match is None:
            return None
        resolved.append(match)

    return resolved


def resolve_runtime_library_sources(repo=None, library_source=None):
    repo = repo or repo_root()
    source_paths = _resolve_library_source_paths(repo=repo, library_source=library_source)
    if source_paths is not None:
        target_paths = [Path("lib") / Path(relative_path).name for relative_path in RUNTIME_LIBRARY_PATHS]
        return source_paths, target_paths, "local"

    vendor_dir = pico_vendor_dir(repo)
    vendor_dir.mkdir(parents=True, exist_ok=True)
    bundle_zip = cached_bundle_zip_path(repo)
    try:
        download_bundle_zip(bundle_zip)
        source_paths = extract_required_libraries_from_bundle(
            bundle_zip,
            vendor_dir,
            required_paths=RUNTIME_LIBRARY_PATHS,
        )
    except Exception as exc:
        raise DeployError(f"Could not prepare runtime libraries: {exc}") from exc

    target_paths = [Path("lib") / Path(relative_path).name for relative_path in RUNTIME_LIBRARY_PATHS]
    return source_paths, target_paths, "download"


def ensure_runtime_libraries(target_root, repo=None, library_source=None, dry_run=False):
    target_root = Path(target_root)
    repo = repo or repo_root()
    source_paths, relative_targets, mode = resolve_runtime_library_sources(repo=repo, library_source=library_source)
    target_paths = [target_root / relative_target for relative_target in relative_targets]

    if dry_run:
        return source_paths, target_paths, mode

    (target_root / "lib").mkdir(parents=True, exist_ok=True)
    for source_path, target_path in zip(source_paths, target_paths):
        copy_library_path(source_path, target_path)
    return source_paths, target_paths, mode


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
        _copy_with_retry(source, destination)

    return copies


def _copy_with_retry(source, destination):
    attempt = 0
    while True:
        try:
            shutil.copy2(source, destination)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) != 433 or attempt >= TRANSIENT_COPY_RETRIES:
                raise
            attempt += 1
            time.sleep(TRANSIENT_COPY_SLEEP_S)


def run_deploy(target=None, library_source=None, dry_run=False, repo=None):
    repo = repo or repo_root()
    target_path = detect_target_path(target)
    source_plan = build_source_plan(repo=repo, library_source=library_source)
    desired_paths = default_desired_target_paths_from_source_plan(source_plan)
    preserve_paths = set(default_preserve_paths())
    stale_paths = find_stale_target_paths(target_path, desired_paths, preserve_paths)
    support_copies, code_copy = build_copy_plan(target_path, source_plan)
    all_copies = support_copies + code_copy
    library_result = (
        source_plan["library_sources"],
        [target_path / target_path_rel for target_path_rel in source_plan["library_targets"]],
        source_plan["library_mode"],
    )

    if dry_run:
        return target_path, all_copies, library_result, stale_paths

    mutation_started = False
    try:
        if needs_space_cleanup(target_path, source_plan):
            mutation_started = True
            delete_stale_paths(stale_paths)
            stale_paths = find_stale_target_paths(target_path, desired_paths, preserve_paths)
            if still_insufficient_space(target_path, source_plan):
                raise DeployError("Not enough space after stale cleanup; preserved and desired files were left untouched")

        mutation_started = True
        copy_planned_files(support_copies)
        if stale_paths:
            delete_stale_paths(stale_paths)
        copy_planned_files(code_copy)
        return target_path, all_copies, library_result, stale_paths
    except DeployError as exc:
        if mutation_started:
            raise DeployError(f"{exc} Reconnect or reset the Pico and rerun deploy.") from exc
        raise
    except Exception as exc:
        if mutation_started:
            raise DeployError(f"Deployment failed after mutating CIRCUITPY: {exc}. Reconnect or reset the Pico and rerun deploy.") from exc
        raise


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
        target_path, copies, library_result, stale_paths = run_deploy(
            target=args.target,
            library_source=args.library_source,
            dry_run=args.dry_run,
        )
    except DeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Target: {target_path}")
    for stale_path in stale_paths:
        action = "Would delete" if args.dry_run else "Deleted"
        try:
            relative = stale_path.relative_to(target_path)
        except ValueError:
            relative = stale_path
        print(f"{action}: {relative}")
    for source, destination in copies:
        action = "Would copy" if args.dry_run else "Copied"
        print(f"{action}: {source.name} -> {destination}")

    source_paths, target_paths, mode = library_result
    if args.dry_run:
        if mode == "local":
            for source_path, target_path in zip(source_paths, target_paths):
                print(f"Would copy local runtime library: {source_path} -> {target_path}")
        else:
            print("Would download runtime libraries into repo cache:")
            for source_path in source_paths:
                print(f"  - {source_path}")
            print("Would copy cached runtime libraries to:")
            for target_path in target_paths:
                print(f"  - {target_path}")
    else:
        if mode == "local":
            for source_path in source_paths:
                print(f"Installed runtime library from local source: {source_path}")
        else:
            print("Downloaded and cached runtime libraries at:")
            for source_path in source_paths:
                print(f"  - {source_path}")
        print("Installed runtime libraries into:")
        for target_path in target_paths:
            print(f"  - {target_path}")

    if not args.dry_run:
        print("Deployment complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
