"""
RAW Processing Utilities - Centralized RAW to RGB conversion.
Single source of truth for RAW processing settings.
"""
import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

# Supported RAW extensions
RAW_EXTENSIONS = {'.arw', '.cr2', '.nef', '.dng', '.raf', '.orf', '.rw2', '.pef', '.srw'}


def is_raw_file(path: Union[str, Path]) -> bool:
    """Check if file is a RAW image."""
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def load_raw(path: Union[str, Path]) -> Optional[np.ndarray]:
    """
    Load RAW file and convert to 16-bit RGB array.

    Uses maximum quality settings:
    - AHD demosaic (highest quality)
    - 16-bit output
    - Linear gamma (no tone curve)
    - No auto adjustments
    - Camera white balance

    Args:
        path: Path to RAW file

    Returns:
        numpy array (H, W, 3) uint16 RGB, or None if failed
    """
    try:
        import rawpy
    except ImportError:
        logger.error("rawpy not installed. Run: pip install rawpy")
        return None

    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                # Demosaic
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,

                # Bit depth
                output_bps=16,

                # Color space (sRGB primaries via camera color matrix)
                output_color=rawpy.ColorSpace.sRGB,

                # White balance
                use_camera_wb=True,

                # Disable auto adjustments
                no_auto_bright=True,

                # Linear gamma (no tone curve applied)
                gamma=(1, 1),

                # Full resolution
                half_size=False,
                four_color_rgb=False,

                # No noise reduction
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
            )
        return rgb

    except Exception as e:
        logger.error(f"Failed to load RAW {path}: {e}")
        return None


def save_tiff(
    img: np.ndarray,
    path: Union[str, Path],
    compression: str = 'zlib',
    photometric: str = 'rgb'
) -> bool:
    """
    Save image as 16-bit TIFF with optional compression.

    Args:
        img: numpy array (H, W, 3) RGB
        path: Output path
        compression: 'zlib' (recommended), 'lzw', or None
        photometric: 'rgb' or 'minisblack' for grayscale

    Returns:
        True if successful
    """
    try:
        import tifffile
    except ImportError:
        logger.error("tifffile not installed. Run: pip install tifffile")
        return False

    try:
        tifffile.imwrite(
            str(path),
            img,
            photometric=photometric,
            compression=compression,
        )
        return True

    except Exception as e:
        logger.error(f"Failed to save TIFF {path}: {e}")
        return False


def convert_raw_to_tiff(
    raw_path: Union[str, Path],
    tiff_path: Union[str, Path] = None,
    compression: str = 'zlib'
) -> Optional[str]:
    """
    Convert RAW file to 16-bit TIFF.

    Args:
        raw_path: Input RAW file path
        tiff_path: Output TIFF path (default: same name with .tiff)
        compression: 'zlib', 'lzw', or None

    Returns:
        Output path if successful, None otherwise
    """
    raw_path = Path(raw_path)

    if tiff_path is None:
        tiff_path = raw_path.with_suffix('.tiff')
    else:
        tiff_path = Path(tiff_path)

    # Load RAW
    rgb = load_raw(raw_path)
    if rgb is None:
        return None

    # Save TIFF
    if save_tiff(rgb, tiff_path, compression):
        logger.info(f"Converted: {raw_path.name} -> {tiff_path.name}")
        return str(tiff_path)

    return None


def convert_folder(
    input_folder: Union[str, Path],
    output_folder: Union[str, Path] = None,
    compression: str = 'zlib'
) -> dict:
    """
    Convert all RAW files in a folder to TIFF.

    Args:
        input_folder: Folder containing RAW files
        output_folder: Output folder (default: same as input)
        compression: 'zlib', 'lzw', or None

    Returns:
        Dict with 'success', 'failed', 'total' counts
    """
    input_folder = Path(input_folder)
    output_folder = Path(output_folder) if output_folder else input_folder
    output_folder.mkdir(parents=True, exist_ok=True)

    results = {'success': 0, 'failed': 0, 'total': 0}

    for raw_file in sorted(input_folder.iterdir()):
        if is_raw_file(raw_file):
            results['total'] += 1
            tiff_path = output_folder / f"{raw_file.stem}.tiff"

            if convert_raw_to_tiff(raw_file, tiff_path, compression):
                results['success'] += 1
            else:
                results['failed'] += 1

    return results


def extract_wb(path: Union[str, Path]) -> Optional[list]:
    """
    Extract camera white balance multipliers from a RAW file.

    Args:
        path: Path to RAW file

    Returns:
        List of 4 WB multipliers [R, G, B, G2], or None if failed
    """
    try:
        import rawpy
    except ImportError:
        logger.error("rawpy not installed. Run: pip install rawpy")
        return None

    try:
        with rawpy.imread(str(path)) as raw:
            return list(raw.camera_whitebalance)
    except Exception as e:
        logger.error(f"Failed to extract WB from {path}: {e}")
        return None


def load_raw_with_fixed_wb(
    path: Union[str, Path],
    wb_multipliers: list,
) -> Optional[np.ndarray]:
    """
    Load RAW using specific WB multipliers (for consistent calibration).

    Uses the same settings as load_raw() but with fixed WB instead of camera WB,
    ensuring identical white balance across checker and subject images.

    Args:
        path: Path to RAW file
        wb_multipliers: List of 4 WB multipliers [R, G, B, G2]

    Returns:
        numpy array (H, W, 3) uint16 RGB, or None if failed
    """
    try:
        import rawpy
    except ImportError:
        logger.error("rawpy not installed. Run: pip install rawpy")
        return None

    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                output_bps=16,
                output_color=rawpy.ColorSpace.sRGB,
                use_camera_wb=False,
                user_wb=wb_multipliers,
                no_auto_bright=True,
                gamma=(1, 1),
                half_size=False,
                four_color_rgb=False,
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
            )
        return rgb
    except Exception as e:
        logger.error(f"Failed to load RAW {path} with fixed WB: {e}")
        return None
