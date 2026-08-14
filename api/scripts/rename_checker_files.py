#!/usr/bin/env python3
"""
Rename colorchecker image files (RAW, TIFF, JPG) to match their NPZ profile names.

Reads each .npz profile, finds the old timestamp-based files across
raw/, tiff/, full_webview/, thumbnail/ (and uploads/), renames them
to the profile name, and updates source_image / checker_raw_path
inside the NPZ.

Usage:
    python3 rename_checker_files.py          # dry run (default)
    python3 rename_checker_files.py --apply  # actually rename
"""
import sys
import shutil
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy is required. Install with: pip install numpy")
    sys.exit(1)

DRY_RUN = "--apply" not in sys.argv

# ── Paths ──
BASE = Path(__file__).resolve().parent.parent  # api/
PROFILES_DIR = BASE / "media" / "colorchecker" / "profiles"
CAPTURES_DIR = BASE / "media" / "captures" / "colorchecker" / "captures"
SUBDIRS = ["raw", "tiff", "full_webview", "thumbnail", "uploads"]

# Extension map per subdirectory
EXT_MAP = {
    "raw": [".ARW", ".arw", ".CR2", ".cr2", ".NEF", ".nef", ".DNG", ".dng"],
    "tiff": [".tiff", ".tif"],
    "full_webview": [".jpg", ".jpeg", ".png"],
    "thumbnail": [".jpg", ".jpeg", ".png"],
    "uploads": [".tiff", ".tif", ".jpg", ".jpeg", ".png"],
}


def find_file_by_stem(directory: Path, stem: str, extensions: list) -> Path | None:
    """Find a file in directory matching stem with any of the given extensions."""
    for ext in extensions:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def main():
    if DRY_RUN:
        print("=" * 60)
        print("  DRY RUN — no files will be changed")
        print("  Run with --apply to execute renames")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  APPLYING RENAMES")
        print("=" * 60)

    print()

    npz_files = sorted(PROFILES_DIR.glob("*.npz"))
    if not npz_files:
        print("No NPZ profiles found.")
        return

    renames = []  # (old_path, new_path)
    npz_updates = []  # (npz_path, new_source_image, new_checker_raw_path)

    for npz_path in npz_files:
        profile_name = npz_path.stem
        data = np.load(npz_path, allow_pickle=True)
        source_image = str(data.get("source_image", ""))
        checker_raw = str(data.get("checker_raw_path", ""))

        if not source_image:
            print(f"  SKIP {profile_name}: no source_image in NPZ")
            continue

        old_stem = Path(source_image).stem

        # If the source already matches the profile name, skip
        if old_stem == profile_name:
            print(f"  OK   {profile_name}: already matches")
            continue

        print(f"  {profile_name}")
        print(f"    old stem: {old_stem}")

        new_source_image = ""
        new_checker_raw = ""

        for subdir in SUBDIRS:
            dir_path = CAPTURES_DIR / subdir
            if not dir_path.exists():
                continue

            extensions = EXT_MAP.get(subdir, [])

            # For uploads, the stem might differ from the tiff stem
            if subdir == "uploads":
                search_stem = old_stem
            else:
                # For raw, the stem from source_image (which is a tiff)
                # might not match exactly — use checker_raw stem for raw/
                if subdir == "raw" and checker_raw:
                    search_stem = Path(checker_raw).stem
                else:
                    search_stem = old_stem

            old_file = find_file_by_stem(dir_path, search_stem, extensions)
            if not old_file:
                continue

            new_file = dir_path / f"{profile_name}{old_file.suffix}"

            # Check for collision
            if new_file.exists() and new_file != old_file:
                print(f"    CONFLICT {subdir}/: {new_file.name} already exists, skipping")
                continue

            renames.append((old_file, new_file))
            print(f"    {subdir}/: {old_file.name} -> {new_file.name}")

            # Track new paths for NPZ update
            if subdir == "tiff" or (subdir == "uploads" and not new_source_image):
                new_source_image = str(new_file)
            if subdir == "raw":
                new_checker_raw = str(new_file)

        # If source was in raw/ directly (like ge_cc -> colorchecker_ok.ARW)
        if not new_source_image:
            # source might be in raw/ itself
            for subdir in SUBDIRS:
                dir_path = CAPTURES_DIR / subdir
                old_file = find_file_by_stem(dir_path, old_stem, EXT_MAP.get(subdir, []))
                if old_file:
                    new_source_image = str(dir_path / f"{profile_name}{old_file.suffix}")
                    break

        if new_source_image or new_checker_raw:
            npz_updates.append((npz_path, new_source_image, new_checker_raw))

        print()

    # Summary
    print(f"\nTotal renames: {len(renames)}")
    print(f"Total NPZ updates: {len(npz_updates)}")

    if DRY_RUN:
        print("\nRun with --apply to execute.")
        return

    # Execute renames
    print("\nRenaming files...")
    for old_path, new_path in renames:
        old_path.rename(new_path)
        print(f"  renamed: {old_path.name} -> {new_path.name}")

    # Update NPZ files
    print("\nUpdating NPZ profiles...")
    for npz_path, new_src, new_raw in npz_updates:
        data = dict(np.load(npz_path, allow_pickle=True))

        if new_src:
            data["source_image"] = new_src
        if new_raw:
            data["checker_raw_path"] = new_raw

        # Save back
        np.savez(npz_path.with_suffix(""), **data)  # np.savez adds .npz
        print(f"  updated: {npz_path.name}")
        print(f"    source_image -> {Path(new_src).name if new_src else '(unchanged)'}")
        print(f"    checker_raw  -> {Path(new_raw).name if new_raw else '(unchanged)'}")

    print("\nDone!")


if __name__ == "__main__":
    main()
