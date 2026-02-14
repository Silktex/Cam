"""
Calibration Service - Color checker detection and color calibration.
Detects ColorChecker24 swatches, saves calibration profiles, and applies color correction.
"""
import os
import io
import json
import base64
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# Check for colour-science library
try:
    import colour
    from colour.characterisation import ColourChecker
    from colour_checker_detection import detect_colour_checkers_segmentation
    COLOUR_AVAILABLE = True
except ImportError:
    COLOUR_AVAILABLE = False
    logger.warning("colour-science not installed. Run: pip install colour-science colour-checker-detection")


# D65 illuminant for color space conversions
D65 = colour.CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer']['D65'] if COLOUR_AVAILABLE else None

# Standard ColorChecker24 reference
REFERENCE_COLOUR_CHECKER = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014'] if COLOUR_AVAILABLE else None

# Swatch labels for logging
SWATCH_LABELS = [
    'A-DarkSkin', 'B-LightSkin', 'C-BlueSky', 'D-Foliage', 'E-BlueFlower', 'F-BluishGreen',
    'G-Orange', 'H-PurplishBlue', 'I-ModerateRed', 'J-Purple', 'K-YellowGreen', 'L-OrangeYellow',
    'M-Blue', 'N-Green', 'O-Red', 'P-Yellow', 'Q-Magenta', 'R-Cyan',
    'S-White', 'T-Neutral8', 'U-Neutral6.5', 'V-Neutral5', 'W-Neutral3.5', 'X-Black',
]


# ─── Debug helpers ───

def _arr_stats(arr: np.ndarray, name: str) -> str:
    """One-line stats for a numpy array."""
    if arr is None or arr.size == 0:
        return f"  {name}: EMPTY/None"
    return (
        f"  {name}: shape={arr.shape} dtype={arr.dtype} "
        f"min={arr.min():.6f} max={arr.max():.6f} mean={arr.mean():.6f}"
    )


def _channel_stats(arr: np.ndarray, name: str) -> str:
    """Per-channel stats for an RGB image or (N,3) array."""
    if arr is None or arr.size == 0:
        return f"  {name}: EMPTY/None"
    if arr.ndim == 3:
        # Image (H, W, 3)
        lines = [f"  {name}: shape={arr.shape} dtype={arr.dtype}"]
        for c, ch in enumerate(['R', 'G', 'B']):
            ch_data = arr[:, :, c]
            lines.append(
                f"    {ch}: min={ch_data.min():.6f} max={ch_data.max():.6f} "
                f"mean={ch_data.mean():.6f} std={ch_data.std():.6f}"
            )
        return '\n'.join(lines)
    elif arr.ndim == 2 and arr.shape[1] == 3:
        # Swatches (N, 3)
        lines = [f"  {name}: shape={arr.shape} dtype={arr.dtype}"]
        for c, ch in enumerate(['R', 'G', 'B']):
            ch_data = arr[:, c]
            lines.append(
                f"    {ch}: min={ch_data.min():.6f} max={ch_data.max():.6f} "
                f"mean={ch_data.mean():.6f}"
            )
        return '\n'.join(lines)
    return _arr_stats(arr, name)


def _swatch_table(detected: np.ndarray, reference: np.ndarray) -> str:
    """Print side-by-side detected vs reference swatches with per-patch error."""
    lines = []
    lines.append("  {:>3s} {:>16s}  {:>22s}  {:>22s}  {:>8s}".format(
        '#', 'Label', 'Detected (R,G,B)', 'Reference (R,G,B)', 'dE(RGB)'
    ))
    lines.append("  " + "-" * 78)

    total_de = 0.0
    for i in range(min(len(detected), len(reference))):
        d = detected[i]
        r = reference[i]
        # Simple Euclidean distance in RGB (not perceptual, but diagnostic)
        de = np.sqrt(np.sum((d - r) ** 2))
        total_de += de
        label = SWATCH_LABELS[i] if i < len(SWATCH_LABELS) else f'S{i}'
        lines.append(
            f"  {i:3d} {label:>16s}  "
            f"({d[0]:.4f}, {d[1]:.4f}, {d[2]:.4f})  "
            f"({r[0]:.4f}, {r[1]:.4f}, {r[2]:.4f})  "
            f"{de:.4f}"
        )

    mean_de = total_de / max(len(detected), 1)
    lines.append(f"  --- Mean RGB dE: {mean_de:.4f}  Total: {total_de:.4f}")
    return '\n'.join(lines)


def _validate_swatches(swatches: np.ndarray, name: str) -> List[str]:
    """Validate swatch array and return list of warnings."""
    warnings = []
    if swatches is None or swatches.size == 0:
        warnings.append(f"{name}: EMPTY array!")
        return warnings

    if swatches.shape != (24, 3):
        warnings.append(f"{name}: shape={swatches.shape}, expected (24, 3)")

    if np.any(np.isnan(swatches)):
        warnings.append(f"{name}: contains NaN values!")

    if np.any(np.isinf(swatches)):
        warnings.append(f"{name}: contains Inf values!")

    if np.any(swatches < 0):
        count = np.sum(swatches < 0)
        warnings.append(f"{name}: {count} negative values (min={swatches.min():.6f})")

    if np.any(swatches > 1.0):
        count = np.sum(swatches > 1.0)
        warnings.append(f"{name}: {count} values > 1.0 (max={swatches.max():.6f})")

    # Check neutral row monotonicity (last 6 swatches: white → black)
    if swatches.shape[0] >= 24:
        neutrals = swatches[18:24]  # Row 3: white, N8, N6.5, N5, N3.5, black
        neutral_lum = np.mean(neutrals, axis=1)  # Average of RGB channels
        is_monotonic = all(neutral_lum[i] >= neutral_lum[i + 1] for i in range(5))
        if not is_monotonic:
            warnings.append(
                f"{name}: neutral row NOT monotonic! "
                f"luminances=[{', '.join(f'{v:.4f}' for v in neutral_lum)}]"
            )
        else:
            # Log it for reference even when OK
            warnings.append(
                f"{name}: neutral row OK (monotonic): "
                f"[{', '.join(f'{v:.4f}' for v in neutral_lum)}]"
            )

    return warnings


def _save_debug_image(image: np.ndarray, path: Path, label: str):
    """Save a debug image (auto-handles float/uint, RGB/BGR)."""
    try:
        img = image.copy()
        if img.dtype in (np.float32, np.float64):
            img = np.clip(img, 0, 1)
            img = (img * 65535).astype(np.uint16)
        if len(img.shape) == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(path), img)
        logger.info(f"  DEBUG IMAGE saved: {label} -> {path.name}")
    except Exception as e:
        logger.warning(f"  Failed to save debug image {label}: {e}")


@dataclass
class ColorCheckerData:
    """Data container for detected ColorChecker information."""
    detected_swatches: np.ndarray       # Shape: (24, 3) - RGB values from camera
    reference_swatches: np.ndarray      # Shape: (24, 3) - Known correct RGB values
    swatch_masks: list                   # Bounding boxes for overlay [y1, y2, x1, x2]
    checker_image: np.ndarray           # Cropped checker region
    source_image: str                    # Original image path
    flip_h: bool = False                 # Applied horizontal flip
    flip_v: bool = False                 # Applied vertical flip
    rotation: int = 0                    # Applied rotation (0, 90, 180, 270)
    detection_id: str = ""               # Unique ID for this detection session


@dataclass
class CalibrationResult:
    """Result of calibrating a single image."""
    success: bool
    source_path: str
    output_path: Optional[str] = None
    error: Optional[str] = None


class CalibrationService:
    """
    Handles ColorChecker detection and color calibration.

    Workflow:
    1. detect_colorchecker() - Detect swatches in image
    2. apply_flip() / apply_rotation() - Adjust orientation to match reference
    3. save_profile() - Save calibration data as NPZ
    4. calibrate_batch() - Apply calibration to batch of images
    """

    def __init__(self):
        self.profiles_dir = settings.COLORCHECKER_DIR / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Debug output directory
        self.debug_dir = settings.COLORCHECKER_DIR / "debug"
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        # Cache for current detection session
        self._current_detection: Optional[ColorCheckerData] = None

    def detect_colorchecker(self, image_path: str, image_override: np.ndarray = None) -> Optional[ColorCheckerData]:
        """
        Detect ColorChecker24 in an image.

        Args:
            image_path: Path to image file
            image_override: Optional pre-loaded image array (float32, 0-1, RGB).
                When provided, skips file loading and uses this array directly.
                Useful for WB-matched detection where the RAW has been re-processed.

        Returns:
            ColorCheckerData with detected swatches, or None if not detected
        """
        if not COLOUR_AVAILABLE:
            raise ImportError("colour-science library not installed")

        image_path = Path(image_path)

        logger.info("=" * 80)
        logger.info("COLORCHECKER DETECTION START")
        logger.info(f"  Source: {image_path}")

        if image_override is not None:
            # Use pre-loaded image (e.g. WB-matched RAW conversion)
            image = image_override
            load_method = "image_override (WB-matched)"
            logger.info(f"  Using image_override array")
        else:
            if not image_path.exists():
                raise FileNotFoundError(f"Image not found: {image_path}")

            logger.info(f"  File size: {image_path.stat().st_size} bytes")

            # Load image - try colour.io first, fallback to cv2
            image = None
            load_method = "unknown"
            try:
                image = colour.io.read_image(str(image_path))
                load_method = "colour.io.read_image"
            except Exception as e:
                logger.warning(f"  colour.io.read_image failed: {e}, trying cv2")

            if image is None:
                # Fallback to cv2
                img_cv2 = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
                if img_cv2 is None:
                    raise ValueError(f"Failed to read image: {image_path}")

                load_method = f"cv2.imread (original dtype={img_cv2.dtype})"

                # Convert BGR to RGB and normalize to 0-1 range
                if len(img_cv2.shape) == 3:
                    img_cv2 = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2RGB)

                if img_cv2.dtype == np.uint8:
                    image = img_cv2.astype(np.float32) / 255.0
                elif img_cv2.dtype == np.uint16:
                    image = img_cv2.astype(np.float32) / 65535.0
                else:
                    image = img_cv2.astype(np.float32)

        logger.info(f"  Load method: {load_method}")
        logger.info(_channel_stats(image, "Loaded image"))

        # Save debug: source image
        _save_debug_image(image, self.debug_dir / "01_source_image.png", "source")

        # Detect color checker
        try:
            detection_results = list(detect_colour_checkers_segmentation(image, additional_data=True))
        except Exception as e:
            logger.error(f"  ColorChecker detection error: {e}")
            raise ValueError(f"ColorChecker detection failed: {e}")

        if not detection_results:
            logger.warning(f"  No ColorChecker detected in {image_path}")
            return None

        # Use first detected checker
        checker_data = detection_results[0]
        swatch_colours, swatch_masks, checker_image, _ = checker_data.values

        logger.info(f"  Swatches found: {len(swatch_colours)}")
        logger.info(_arr_stats(swatch_colours, "Detected swatches (raw)"))

        # Save debug: checker region
        _save_debug_image(checker_image, self.debug_dir / "02_checker_region.png", "checker region")

        # Get reference swatches — NO default flip, user does it interactively
        reference_swatches = colour.XYZ_to_RGB(
            colour.xyY_to_XYZ(list(REFERENCE_COLOUR_CHECKER.data.values())),
            'sRGB',
            REFERENCE_COLOUR_CHECKER.illuminant,
            apply_cctf_encoding=False,  # EXPLICIT: linear output
        )

        logger.info(_arr_stats(reference_swatches, "Reference swatches (linear sRGB)"))

        # Validate both
        for w in _validate_swatches(swatch_colours, "Detected"):
            logger.info(f"  VALIDATE {w}")
        for w in _validate_swatches(reference_swatches, "Reference"):
            logger.info(f"  VALIDATE {w}")

        # Log swatch table
        logger.info("  SWATCH COMPARISON:")
        logger.info('\n' + _swatch_table(swatch_colours, reference_swatches))

        # No auto-orient — user applies flips/rotations interactively via UI
        flip_h = False
        flip_v = False

        # Generate unique detection ID
        detection_id = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        data = ColorCheckerData(
            detected_swatches=swatch_colours,
            reference_swatches=reference_swatches,
            swatch_masks=swatch_masks,
            checker_image=checker_image,
            source_image=str(image_path),
            flip_h=flip_h,
            flip_v=flip_v,
            detection_id=detection_id,
        )

        # Cache for session
        self._current_detection = data

        logger.info(f"  Detection ID: {detection_id}")
        logger.info("COLORCHECKER DETECTION END")
        logger.info("=" * 80)

        return data

    def apply_flip(self, data: ColorCheckerData, axis: str) -> ColorCheckerData:
        """
        Apply flip transformation to detected swatches.

        Args:
            data: ColorCheckerData from detection
            axis: 'horizontal' or 'vertical'

        Returns:
            New ColorCheckerData with flipped swatches
        """
        if axis not in ('horizontal', 'vertical'):
            raise ValueError("axis must be 'horizontal' or 'vertical'")

        logger.info(f"FLIP: applying {axis} flip to detected swatches")

        # Reshape swatches to 4x6 grid
        swatches = data.detected_swatches.reshape(4, 6, 3)
        masks = np.array(data.swatch_masks).reshape(4, 6, 4)

        if axis == 'horizontal':
            # Flip ALL columns (standard horizontal flip)
            swatches = swatches[:, ::-1, :]
            masks = masks[:, ::-1, :]
            new_flip_h = not data.flip_h
            new_flip_v = data.flip_v
        else:  # vertical
            swatches = np.flipud(swatches)
            masks = np.flipud(masks)
            new_flip_h = data.flip_h
            new_flip_v = not data.flip_v

        # Flatten back
        new_swatches = swatches.reshape(24, 3)
        new_masks = masks.reshape(24, 4).tolist()

        # Also flip the checker image for display
        if axis == 'horizontal':
            new_checker_image = np.fliplr(data.checker_image)
        else:
            new_checker_image = np.flipud(data.checker_image)

        new_data = ColorCheckerData(
            detected_swatches=new_swatches,
            reference_swatches=data.reference_swatches,
            swatch_masks=new_masks,
            checker_image=new_checker_image,
            source_image=data.source_image,
            flip_h=new_flip_h,
            flip_v=new_flip_v,
            rotation=data.rotation,
            detection_id=data.detection_id,
        )

        self._current_detection = new_data

        # Log updated comparison
        logger.info(f"  After flip: flip_h={new_flip_h} flip_v={new_flip_v}")
        logger.info("  SWATCH COMPARISON (after flip):")
        logger.info('\n' + _swatch_table(new_swatches, data.reference_swatches))

        return new_data

    def apply_rotation(self, data: ColorCheckerData, degrees: int) -> ColorCheckerData:
        """
        Apply rotation transformation to detected swatches.

        Args:
            data: ColorCheckerData from detection
            degrees: Rotation angle (90, 180, 270, or -90)

        Returns:
            New ColorCheckerData with rotated swatches
        """
        # Normalize degrees
        degrees = degrees % 360
        if degrees not in (0, 90, 180, 270):
            raise ValueError("degrees must be 0, 90, 180, or 270")

        if degrees == 0:
            return data

        logger.info(f"ROTATE: applying {degrees}° rotation to detected swatches")

        # Reshape swatches to 4x6 grid
        swatches = data.detected_swatches.reshape(4, 6, 3)
        masks = np.array(data.swatch_masks).reshape(4, 6, 4)

        # Apply rotation
        k = degrees // 90  # Number of 90-degree rotations
        swatches = np.rot90(swatches, k=k)
        masks = np.rot90(masks, k=k)

        # Flatten - note shape may change for 90/270 rotations
        new_shape = swatches.shape[0] * swatches.shape[1]
        new_swatches = swatches.reshape(new_shape, 3)
        new_masks = masks.reshape(new_shape, 4).tolist()

        # Rotate the checker image
        if degrees == 90:
            new_checker_image = np.rot90(data.checker_image, k=-1)
        elif degrees == 180:
            new_checker_image = np.rot90(data.checker_image, k=2)
        else:  # 270
            new_checker_image = np.rot90(data.checker_image, k=1)

        new_rotation = (data.rotation + degrees) % 360

        new_data = ColorCheckerData(
            detected_swatches=new_swatches,
            reference_swatches=data.reference_swatches,
            swatch_masks=new_masks,
            checker_image=new_checker_image,
            source_image=data.source_image,
            flip_h=data.flip_h,
            flip_v=data.flip_v,
            rotation=new_rotation,
            detection_id=data.detection_id,
        )

        self._current_detection = new_data

        logger.info(f"  After rotation: rotation={new_rotation}")
        logger.info("  SWATCH COMPARISON (after rotate):")
        logger.info('\n' + _swatch_table(new_swatches, data.reference_swatches))

        return new_data

    def generate_overlay_image(self, data: ColorCheckerData, show_colors: bool = True) -> bytes:
        """
        Generate PNG image with swatch boxes and detected colors overlaid on checker image.

        Args:
            data: ColorCheckerData from detection
            show_colors: If True, show detected color squares next to each swatch

        Returns:
            PNG image bytes
        """
        # Convert to 8-bit for visualization
        img = data.checker_image.copy()
        if img.max() <= 1.0:
            img = (img * 255).astype(np.uint8)
        elif img.dtype == np.float32 or img.dtype == np.float64:
            img = np.clip(img * 255, 0, 255).astype(np.uint8)

        # Convert RGB to BGR for OpenCV
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # Get detected swatch colors (convert to 8-bit BGR for OpenCV)
        detected_colors = data.detected_swatches
        if detected_colors.max() <= 1.0:
            detected_colors = (detected_colors * 255).astype(np.uint8)
        else:
            detected_colors = detected_colors.astype(np.uint8)

        # Draw swatch boxes with labels and detected colors
        swatch_labels = list('ABCDEFGHIJKLMNOPQRSTUVWX')

        for i, mask in enumerate(data.swatch_masks):
            y1, y2, x1, x2 = [int(m) for m in mask]
            swatch_h = y2 - y1
            swatch_w = x2 - x1

            # Draw rectangle outline
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Draw detected color square inside the swatch (bottom-right corner)
            if show_colors and i < len(detected_colors):
                # Get detected color (RGB) and convert to BGR for OpenCV
                r, g, b = detected_colors[i]
                color_bgr = (int(b), int(g), int(r))

                # Draw color square (25% of swatch size, positioned at bottom-right)
                color_size = max(int(min(swatch_w, swatch_h) * 0.4), 15)
                cx1 = x2 - color_size - 4
                cy1 = y2 - color_size - 4
                cx2 = x2 - 4
                cy2 = y2 - 4

                # Filled color square with white border
                cv2.rectangle(img, (cx1 - 2, cy1 - 2), (cx2 + 2, cy2 + 2), (255, 255, 255), -1)
                cv2.rectangle(img, (cx1, cy1), (cx2, cy2), color_bgr, -1)

            # Draw label at top-left
            if i < len(swatch_labels):
                label = swatch_labels[i]
                font_scale = 0.5
                thickness = 1
                (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)

                # Background for text
                cv2.rectangle(img, (x1, y1 - text_h - 4), (x1 + text_w + 4, y1), (0, 255, 0), -1)
                cv2.putText(img, label, (x1 + 2, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness)

        # Encode as PNG
        _, buffer = cv2.imencode('.png', img)
        return buffer.tobytes()

    def generate_overlay_base64(self, data: ColorCheckerData) -> str:
        """Generate base64-encoded overlay image."""
        png_bytes = self.generate_overlay_image(data)
        b64 = base64.b64encode(png_bytes).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    def save_profile(self, data: ColorCheckerData, name: str) -> str:
        """
        Save ColorChecker detection data as NPZ profile.

        Args:
            data: ColorCheckerData from detection
            name: Profile name (alphanumeric + underscore)

        Returns:
            Path to saved profile
        """
        # Sanitize name
        safe_name = "".join(c for c in name if c.isalnum() or c == '_')
        if not safe_name:
            safe_name = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        profile_path = self.profiles_dir / f"{safe_name}.npz"

        # Derive checker RAW path from source TIFF path
        source_path = Path(data.source_image)
        checker_raw_path = ""
        raw_dir = source_path.parent.parent / "raw"
        if raw_dir.exists():
            for ext in ['.ARW', '.arw', '.CR2', '.cr2', '.NEF', '.nef', '.DNG', '.dng']:
                candidate = raw_dir / f"{source_path.stem}{ext}"
                if candidate.exists():
                    checker_raw_path = str(candidate)
                    break

        logger.info("=" * 80)
        logger.info(f"SAVE PROFILE: {safe_name}")
        logger.info(f"  Source image: {data.source_image}")
        logger.info(f"  Checker RAW: {checker_raw_path or 'NOT FOUND'}")
        logger.info(f"  Flip H={data.flip_h} V={data.flip_v} Rotation={data.rotation}")
        logger.info(_arr_stats(data.detected_swatches, "Detected swatches"))
        logger.info(_arr_stats(data.reference_swatches, "Reference swatches"))

        # Final validation before save
        for w in _validate_swatches(data.detected_swatches, "Detected"):
            logger.info(f"  VALIDATE {w}")
        for w in _validate_swatches(data.reference_swatches, "Reference"):
            logger.info(f"  VALIDATE {w}")

        # Log final swatch table that will be saved
        logger.info("  FINAL SWATCH TABLE (this is what gets saved):")
        logger.info('\n' + _swatch_table(data.detected_swatches, data.reference_swatches))

        # Save as NPZ
        np.savez(
            profile_path,
            detected_swatches=data.detected_swatches,
            reference_swatches=data.reference_swatches,
            source_image=data.source_image,
            checker_raw_path=checker_raw_path,
            flip_horizontal=data.flip_h,
            flip_vertical=data.flip_v,
            rotation=data.rotation,
            created_at=datetime.now().isoformat(),
            checker_type='ColorChecker24',
        )

        logger.info(f"  Saved: {profile_path}")
        logger.info("=" * 80)
        return str(profile_path)

    def save_colorchecker_profile(self, data: ColorCheckerData, name: str) -> str:
        """Alias for save_profile for backward compatibility."""
        return self.save_profile(data, name)

    def load_profile(self, name: str) -> Optional[ColorCheckerData]:
        """
        Load ColorChecker profile from NPZ file.

        Args:
            name: Profile name (without .npz extension)

        Returns:
            ColorCheckerData or None if not found
        """
        profile_path = self.profiles_dir / f"{name}.npz"

        if not profile_path.exists():
            logger.warning(f"Profile not found: {profile_path}")
            return None

        try:
            with np.load(profile_path, allow_pickle=True) as data:
                detected = data['detected_swatches']
                reference = data['reference_swatches']

                logger.info("=" * 80)
                logger.info(f"LOAD PROFILE: {name}")
                logger.info(f"  Source: {data['source_image']}")
                logger.info(f"  Flip H={data['flip_horizontal']} V={data['flip_vertical']} Rot={data['rotation']}")
                logger.info(_arr_stats(detected, "Detected swatches"))
                logger.info(_arr_stats(reference, "Reference swatches"))

                # Validate loaded data
                for w in _validate_swatches(detected, "Detected"):
                    logger.info(f"  VALIDATE {w}")
                for w in _validate_swatches(reference, "Reference"):
                    logger.info(f"  VALIDATE {w}")

                logger.info("  LOADED SWATCH TABLE:")
                logger.info('\n' + _swatch_table(detected, reference))

                # Use saved flip values — no auto-orient override
                flip_h = bool(data['flip_horizontal'])
                flip_v = bool(data['flip_vertical'])

                logger.info("=" * 80)

                return ColorCheckerData(
                    detected_swatches=detected,
                    reference_swatches=reference,
                    swatch_masks=[],  # Not saved in profile
                    checker_image=np.array([]),  # Not saved in profile
                    source_image=str(data['source_image']),
                    flip_h=flip_h,
                    flip_v=flip_v,
                    rotation=int(data['rotation']),
                    detection_id=f"loaded_{name}",
                )
        except Exception as e:
            logger.error(f"Failed to load profile {name}: {e}")
            return None

    def load_colorchecker_profile(self, name: str) -> Optional[ColorCheckerData]:
        """Alias for load_profile for backward compatibility."""
        return self.load_profile(name)

    def list_profiles(self) -> List[Dict]:
        """
        List all saved ColorChecker profiles.

        Returns:
            List of profile info dicts with name, created_at, source_image
        """
        profiles = []

        for npz_file in sorted(self.profiles_dir.glob("*.npz")):
            try:
                with np.load(npz_file, allow_pickle=True) as data:
                    profiles.append({
                        "name": npz_file.stem,
                        "path": str(npz_file),
                        "created_at": str(data.get('created_at', 'unknown')),
                        "source_image": str(data.get('source_image', '')),
                        "checker_type": str(data.get('checker_type', 'ColorChecker24')),
                    })
            except Exception as e:
                logger.warning(f"Failed to read profile {npz_file}: {e}")

        return profiles

    def delete_profile(self, name: str) -> bool:
        """
        Delete a saved profile.

        Args:
            name: Profile name

        Returns:
            True if deleted, False if not found
        """
        profile_path = self.profiles_dir / f"{name}.npz"

        if profile_path.exists():
            profile_path.unlink()
            logger.info(f"Deleted profile: {name}")
            return True

        return False

    def calibrate_image(self, image: np.ndarray, data: ColorCheckerData,
                        image_name: str = "unknown") -> np.ndarray:
        """
        Apply color calibration to a single image.

        Designed for LINEAR input images (16-bit TIFFs from camera RAW):
        - Input image is already linear (no gamma decoding needed)
        - Detected swatches are from linear image (already linear)
        - Reference swatches from XYZ_to_RGB are linear (apply_cctf_encoding=False)
        - Correction applied in linear space, output stays linear

        Args:
            image: Input image (RGB, float 0-1 or uint8/uint16)
            data: ColorCheckerData with calibration info
            image_name: Name for debug logging

        Returns:
            Color-corrected image (linear sRGB, float 0-1)
        """
        if not COLOUR_AVAILABLE:
            raise ImportError("colour-science library not installed")

        logger.info(f"  CALIBRATE IMAGE: {image_name}")

        # Normalize image to float 0-1 if needed
        if image.dtype == np.uint8:
            logger.info(f"    Converting uint8 -> float32 (/255)")
            image = image.astype(np.float32) / 255.0
        elif image.dtype == np.uint16:
            logger.info(f"    Converting uint16 -> float32 (/65535)")
            image = image.astype(np.float32) / 65535.0

        logger.info(_channel_stats(image, f"    Input ({image_name})"))

        # Log swatch data being used
        logger.info(_arr_stats(data.detected_swatches, "    Swatches (detected)"))
        logger.info(_arr_stats(data.reference_swatches, "    Swatches (reference)"))

        # Auto-detect and fix serpentine swatch ordering.
        # Some ColorChecker detection methods read alternating rows in opposite
        # directions, causing half the patches to be matched to wrong reference
        # values.  For each row of 6, check if reversing the detected order
        # gives a better match to reference — if so, flip that row.
        detected_swatches = data.detected_swatches.copy()
        for row in range(4):
            s, e = row * 6, row * 6 + 6
            det_row = detected_swatches[s:e]
            ref_row = data.reference_swatches[s:e]
            de_fwd = np.mean(np.sqrt(np.sum((det_row - ref_row) ** 2, axis=1)))
            de_rev = np.mean(np.sqrt(np.sum((det_row[::-1] - ref_row) ** 2, axis=1)))
            if de_rev < de_fwd * 0.7:
                detected_swatches[s:e] = det_row[::-1]
                logger.warning(
                    f"    Row {row} swatches reversed — auto-corrected "
                    f"(dE fwd={de_fwd:.4f} rev={de_rev:.4f})"
                )

        # Adapt reference swatches to scene illuminant via white-patch scaling.
        # Reference swatches assume D65 illuminant (bright, neutral), but the scene
        # lighting may be very different. Without adaptation, the correction matrix
        # learns to bridge the entire illuminant gap, causing massive overcorrection.
        # By scaling reference to match the detected white patch, the matrix only
        # corrects camera-specific spectral errors.
        det_white = detected_swatches[18]  # S-White (index 18)
        ref_white = data.reference_swatches[18]

        safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
        wp_scale = det_white / safe_ref

        logger.info(f"    White-point scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")

        adapted_reference = data.reference_swatches * wp_scale

        logger.info(_swatch_table(detected_swatches, adapted_reference))

        # Diagonal (per-channel) correction only — no cross-channel terms.
        # A full 3x3 matrix can rotate hues (e.g. green → purple) because its
        # off-diagonal elements mix channels. A diagonal matrix can only adjust
        # per-channel gain, which is all that's needed after white-point adaptation
        # removes the illuminant difference. This corrects residual camera
        # spectral sensitivity errors without introducing hue shifts.
        gains = np.ones(3)
        for c in range(3):
            det_c = detected_swatches[:, c]
            ref_c = adapted_reference[:, c]
            denom = np.sum(det_c ** 2)
            if denom > 1e-10:
                gains[c] = np.sum(det_c * ref_c) / denom

        logger.info(f"    Diagonal gains: R={gains[0]:.4f} G={gains[1]:.4f} B={gains[2]:.4f}")

        corrected = image * gains

        logger.info(_channel_stats(corrected, f"    After diagonal correction"))

        # Check for out-of-range values before clipping
        below_zero = np.sum(corrected < 0)
        above_one = np.sum(corrected > 1)
        if below_zero > 0 or above_one > 0:
            total = corrected.size
            logger.warning(
                f"    OUT OF RANGE: {below_zero} pixels < 0 ({100*below_zero/total:.2f}%), "
                f"{above_one} pixels > 1 ({100*above_one/total:.2f}%)"
            )

        corrected_clipped = np.clip(corrected, 0, 1)

        logger.info(_channel_stats(corrected_clipped, f"    After clip (linear output)"))

        # Return linear — no gamma encoding. The rest of the pipeline (RAW→TIFF,
        # crop) is linear, so calibrated output should be too. Gamma is applied
        # only at final display/export stage.
        return corrected_clipped

    def calibrate_batch(
        self,
        batch_path: str,
        checker_data: ColorCheckerData,
        checker_raw_path: Optional[str] = None,
    ) -> List[CalibrationResult]:
        """
        Apply color calibration to all images in a batch.

        Args:
            batch_path: Path to batch folder
            checker_data: ColorCheckerData with calibration info
            checker_raw_path: Optional path to checker's RAW file. When provided,
                its WB multipliers are extracted and used to re-convert each
                subject RAW, ensuring consistent white balance across all images.

        Returns:
            List of CalibrationResult for each image
        """
        from .raw_utils import extract_wb, load_raw_with_fixed_wb, is_raw_file, RAW_EXTENSIONS

        batch_path = Path(batch_path)
        results = []

        logger.info("=" * 80)
        logger.info("CALIBRATE BATCH START")
        logger.info(f"  Batch path: {batch_path}")
        logger.info(f"  Checker RAW path: {checker_raw_path or 'None (using per-image WB)'}")
        logger.info(f"  Profile source: {checker_data.source_image}")
        logger.info(f"  Profile flip: H={checker_data.flip_h} V={checker_data.flip_v} Rot={checker_data.rotation}")

        # Extract checker WB if a RAW path was provided
        fixed_wb = None
        if checker_raw_path:
            checker_raw = Path(checker_raw_path)
            if checker_raw.exists():
                fixed_wb = extract_wb(checker_raw)
                if fixed_wb:
                    logger.info(f"  Fixed WB extracted: {fixed_wb}")
                else:
                    logger.warning(f"  Could not extract WB from {checker_raw_path}, falling back to per-image WB")

        # Find source images (prefer tiff > cropped > raw)
        # NOTE: changed order — tiff first to use reconverted linear TIFFs
        source_folder = None
        for folder_name in ['cropped', 'tiff', 'raw']:
            folder = batch_path / folder_name
            if folder.exists() and list(folder.iterdir()):
                source_folder = folder
                break

        if not source_folder:
            logger.error("  No source images found in batch!")
            return [CalibrationResult(
                success=False,
                source_path=str(batch_path),
                error="No source images found"
            )]

        logger.info(f"  Source folder: {source_folder.name}/")

        # List what's available
        for folder_name in ['tiff', 'cropped', 'raw']:
            folder = batch_path / folder_name
            if folder.exists():
                count = len(list(folder.iterdir()))
                marker = " <-- USING" if folder == source_folder else ""
                logger.info(f"    {folder_name}/: {count} files{marker}")

        # Locate raw folder for fixed-WB re-conversion
        raw_folder = batch_path / "raw"

        # Create output folder
        output_folder = batch_path / "color_calibrated"
        output_folder.mkdir(exist_ok=True)

        # Also create debug folder for this batch
        batch_debug_dir = output_folder / "_debug"
        batch_debug_dir.mkdir(exist_ok=True)

        # Process each image
        image_extensions = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}
        image_count = 0

        for image_path in sorted(source_folder.iterdir()):
            if image_path.suffix.lower() not in image_extensions:
                continue

            image_count += 1
            logger.info(f"  --- Processing [{image_count}]: {image_path.name}")

            try:
                image = None
                load_source = "colour.io.read_image"

                # If fixed WB requested, try to re-convert from RAW
                if fixed_wb and raw_folder.exists():
                    for ext in RAW_EXTENSIONS:
                        raw_candidate = raw_folder / f"{image_path.stem}{ext}"
                        if raw_candidate.exists():
                            rgb_16 = load_raw_with_fixed_wb(raw_candidate, fixed_wb)
                            if rgb_16 is not None:
                                image = rgb_16.astype(np.float32) / 65535.0
                                load_source = f"load_raw_with_fixed_wb({raw_candidate.name})"
                                logger.info(f"    Re-converted with fixed WB from {raw_candidate.name}")
                            break

                # Fall back to loading the source image directly
                if image is None:
                    image = colour.io.read_image(str(image_path))

                logger.info(f"    Load source: {load_source}")

                # Save debug: original
                if image_count <= 3:  # Only first 3 to save disk
                    _save_debug_image(
                        image,
                        batch_debug_dir / f"{image_path.stem}_01_original.png",
                        "original"
                    )

                # Apply calibration (returns gamma-encoded sRGB)
                corrected = self.calibrate_image(image, checker_data, image_name=image_path.name)

                # Save debug: corrected
                if image_count <= 3:
                    _save_debug_image(
                        corrected,
                        batch_debug_dir / f"{image_path.stem}_02_corrected_gamma.png",
                        "corrected+gamma"
                    )

                # Save as 16-bit PNG (already gamma-encoded, just clip and scale)
                corrected_clipped = np.clip(corrected, 0, 1)
                corrected_16bit = (corrected_clipped * 65535).astype(np.uint16)

                output_path = output_folder / f"{image_path.stem}_calibrated.png"

                # Convert RGB to BGR for OpenCV
                corrected_bgr = cv2.cvtColor(corrected_16bit, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(output_path), corrected_bgr)

                results.append(CalibrationResult(
                    success=True,
                    source_path=str(image_path),
                    output_path=str(output_path),
                ))
                logger.info(f"    Saved: {output_path.name}")

            except Exception as e:
                logger.error(f"    FAILED: {e}", exc_info=True)
                results.append(CalibrationResult(
                    success=False,
                    source_path=str(image_path),
                    error=str(e),
                ))

        success_count = sum(1 for r in results if r.success)
        logger.info(f"  BATCH COMPLETE: {success_count}/{len(results)} succeeded")
        logger.info(f"  Debug images in: {batch_debug_dir}")
        logger.info("CALIBRATE BATCH END")
        logger.info("=" * 80)

        return results

    def get_preview_comparison(self, batch_path: str) -> Optional[Dict]:
        """
        Get before/after preview for calibration.

        Returns dict with original and calibrated image URLs.
        """
        batch_path = Path(batch_path)
        calibrated_folder = batch_path / "color_calibrated"

        if not calibrated_folder.exists():
            return None

        # Find first calibrated image
        for img in sorted(calibrated_folder.iterdir()):
            if img.suffix.lower() in {'.png', '.jpg', '.jpeg', '.tiff', '.tif'}:
                # Find corresponding original
                original_name = img.stem.replace('_calibrated', '')

                # Check various source folders
                original_path = None
                for folder in ['cropped', 'tiff', 'raw']:
                    for ext in ['.tiff', '.tif', '.png', '.jpg']:
                        candidate = batch_path / folder / f"{original_name}{ext}"
                        if candidate.exists():
                            original_path = candidate
                            break
                    if original_path:
                        break

                batch_name = batch_path.name

                return {
                    "original_url": f"/media/captures/{batch_name}/{original_path.parent.name}/{original_path.name}" if original_path else None,
                    "calibrated_url": f"/media/captures/{batch_name}/color_calibrated/{img.name}",
                }

        return None

    def get_current_detection(self) -> Optional[ColorCheckerData]:
        """Get the current cached detection."""
        return self._current_detection

    def _get_reference_checker(self) -> 'ColourChecker':
        """
        Get reference ColorChecker — returns UNMODIFIED canonical order.
        User applies flips/rotations interactively to the detected swatches instead.
        """
        return REFERENCE_COLOUR_CHECKER
