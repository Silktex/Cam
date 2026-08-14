#!/usr/bin/env python3
"""
End-to-end test of the calibration pipeline — mirrors the UI flow exactly.

For each sample batch:
  1. Extract WB from the batch's first RAW
  2. Re-process colorchecker_ok.ARW with that WB
  3. Detect colorchecker swatches on the WB-matched image
  4. Apply calibration to the batch's TIFFs (or cropped)
  5. Assert calibrated output is close to input (no massive shift)
"""

import sys
import logging
from pathlib import Path

# Ensure the app modules are importable
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_calibration")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).parent
CAPTURES = BASE / "media" / "captures"
CHECKER_RAW = CAPTURES / "colorchecker" / "captures" / "raw" / "colorchecker_ok.ARW"

BATCHES = sorted(
    p for p in CAPTURES.iterdir()
    if p.is_dir() and p.name.startswith("GRIMSBY")
)

# ---------------------------------------------------------------------------
# Imports from the actual codebase (uses the venv)
# ---------------------------------------------------------------------------
from scripts.processing.raw_utils import extract_wb, load_raw_with_fixed_wb, is_raw_file
from scripts.processing.calibration_service import CalibrationService

service = CalibrationService()


def channel_means(img: np.ndarray) -> dict:
    """Return per-channel means as a dict."""
    return {"R": float(img[..., 0].mean()),
            "G": float(img[..., 1].mean()),
            "B": float(img[..., 2].mean())}


def load_tiff(path: Path) -> np.ndarray:
    """Load a TIFF/PNG as float32 0-1."""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {path}")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img.dtype == np.uint16:
        return img.astype(np.float32) / 65535.0
    elif img.dtype == np.uint8:
        return img.astype(np.float32) / 255.0
    return img.astype(np.float32)


def fmt_means(means: dict) -> str:
    return f"R={means['R']:.4f} G={means['G']:.4f} B={means['B']:.4f}"


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test_batch(batch_dir: Path):
    batch_name = batch_dir.name
    logger.info("=" * 70)
    logger.info(f"BATCH: {batch_name}")
    logger.info("=" * 70)

    # --- 1. Find a RAW in this batch to get WB ---
    raw_dir = batch_dir / "raw"
    if not raw_dir.exists():
        logger.warning(f"  No raw/ folder — skipping")
        return None

    raw_files = sorted(p for p in raw_dir.iterdir() if is_raw_file(p))
    if not raw_files:
        logger.warning(f"  No RAW files — skipping")
        return None

    subject_raw = raw_files[0]
    logger.info(f"  Subject RAW (for WB): {subject_raw.name}")

    wb = extract_wb(subject_raw)
    if wb is None:
        logger.error(f"  Failed to extract WB — skipping")
        return None
    logger.info(f"  WB multipliers: {wb}")

    # --- 2. Re-process colorchecker_ok.ARW with this batch's WB ---
    logger.info(f"  Re-processing checker with batch WB...")
    checker_rgb = load_raw_with_fixed_wb(CHECKER_RAW, wb)
    if checker_rgb is None:
        logger.error(f"  Failed to load checker with fixed WB — skipping")
        return None

    # Normalize to float 0-1
    checker_float = checker_rgb.astype(np.float32) / 65535.0
    logger.info(f"  Checker image: {checker_float.shape}, {fmt_means(channel_means(checker_float))}")

    # --- 3. Detect colorchecker on WB-matched image ---
    logger.info(f"  Detecting colorchecker...")
    checker_data = service.detect_colorchecker(
        str(CHECKER_RAW),
        image_override=checker_float,
    )
    if checker_data is None:
        logger.error(f"  Detection failed — skipping")
        return None

    logger.info(f"  Detected {len(checker_data.detected_swatches)} swatches")

    # --- 4. Find source images (prefer cropped > tiff) ---
    source_dir = None
    for folder in ["cropped", "tiff"]:
        d = batch_dir / folder
        if d.exists() and any(d.iterdir()):
            source_dir = d
            break

    if source_dir is None:
        logger.warning(f"  No cropped/ or tiff/ folder — skipping")
        return None

    source_files = sorted(source_dir.iterdir())
    logger.info(f"  Source folder: {source_dir.name}/ ({len(source_files)} files)")

    # --- 5. For each subject, re-convert RAW with checker WB, calibrate, compare ---
    results = []
    for src_file in source_files:
        if src_file.suffix.lower() not in (".tiff", ".tif", ".png"):
            continue

        stem = src_file.stem
        logger.info(f"  --- {stem} ---")

        # Try to find matching RAW and re-convert with fixed WB
        matching_raw = None
        for rf in raw_files:
            if rf.stem == stem:
                matching_raw = rf
                break

        if matching_raw:
            logger.info(f"    Re-converting RAW with checker WB...")
            subject_rgb = load_raw_with_fixed_wb(matching_raw, wb)
            if subject_rgb is not None:
                subject = subject_rgb.astype(np.float32) / 65535.0
            else:
                logger.warning(f"    RAW re-conversion failed, loading {source_dir.name} file")
                subject = load_tiff(src_file)
        else:
            subject = load_tiff(src_file)

        input_means = channel_means(subject)
        logger.info(f"    Input:      {fmt_means(input_means)}")

        # --- 6. Calibrate ---
        calibrated = service.calibrate_image(subject, checker_data, stem)

        output_means = channel_means(calibrated)
        logger.info(f"    Calibrated: {fmt_means(output_means)}")

        # --- 7. Check: output should be close to input ---
        max_shift = max(
            abs(output_means["R"] - input_means["R"]),
            abs(output_means["G"] - input_means["G"]),
            abs(output_means["B"] - input_means["B"]),
        )
        ratio_r = output_means["R"] / max(input_means["R"], 1e-6)
        ratio_g = output_means["G"] / max(input_means["G"], 1e-6)
        ratio_b = output_means["B"] / max(input_means["B"], 1e-6)

        status = "PASS" if max_shift < 0.05 else "FAIL"
        logger.info(
            f"    Max shift:  {max_shift:.4f}  "
            f"Ratios: R={ratio_r:.3f} G={ratio_g:.3f} B={ratio_b:.3f}  "
            f"[{status}]"
        )

        results.append({
            "file": stem,
            "input": input_means,
            "output": output_means,
            "max_shift": max_shift,
            "status": status,
        })

        # Only test first 2 images per batch to keep it fast
        if len(results) >= 2:
            break

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not CHECKER_RAW.exists():
        logger.error(f"Checker RAW not found: {CHECKER_RAW}")
        sys.exit(1)

    logger.info(f"Checker RAW: {CHECKER_RAW}")
    logger.info(f"Batches found: {[b.name for b in BATCHES]}")
    logger.info("")

    all_results = {}
    for batch_dir in BATCHES:
        try:
            results = test_batch(batch_dir)
            if results:
                all_results[batch_dir.name] = results
        except Exception as e:
            logger.error(f"  EXCEPTION in {batch_dir.name}: {e}", exc_info=True)

    # --- Summary ---
    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)

    total = 0
    passed = 0
    for batch_name, results in all_results.items():
        for r in results:
            total += 1
            if r["status"] == "PASS":
                passed += 1
            logger.info(
                f"  {r['status']}  {batch_name}/{r['file']}  "
                f"shift={r['max_shift']:.4f}  "
                f"in=({fmt_means(r['input'])})  "
                f"out=({fmt_means(r['output'])})"
            )

    logger.info("")
    logger.info(f"  {passed}/{total} passed (max channel shift < 0.05)")

    if passed < total:
        logger.warning(f"  {total - passed} FAILED — calibration shifted too much")
        sys.exit(1)
    else:
        logger.info("  All tests passed.")


if __name__ == "__main__":
    main()
