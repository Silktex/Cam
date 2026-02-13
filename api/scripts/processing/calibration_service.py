"""
Calibration Service - Color checker detection and color calibration.
Detects ColorChecker24 swatches, saves calibration profiles, and applies color correction.
"""
import os
import io
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

        # Cache for current detection session
        self._current_detection: Optional[ColorCheckerData] = None

    def detect_colorchecker(self, image_path: str) -> Optional[ColorCheckerData]:
        """
        Detect ColorChecker24 in an image.

        Args:
            image_path: Path to image file

        Returns:
            ColorCheckerData with detected swatches, or None if not detected
        """
        if not COLOUR_AVAILABLE:
            raise ImportError("colour-science library not installed")

        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Load image - try colour.io first, fallback to cv2
        image = None
        try:
            image = colour.io.read_image(str(image_path))
        except Exception as e:
            logger.warning(f"colour.io.read_image failed: {e}, trying cv2")

        if image is None:
            # Fallback to cv2
            img_cv2 = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if img_cv2 is None:
                raise ValueError(f"Failed to read image: {image_path}")

            # Convert BGR to RGB and normalize to 0-1 range
            if len(img_cv2.shape) == 3:
                img_cv2 = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2RGB)

            if img_cv2.dtype == np.uint8:
                image = img_cv2.astype(np.float32) / 255.0
            elif img_cv2.dtype == np.uint16:
                image = img_cv2.astype(np.float32) / 65535.0
            else:
                image = img_cv2.astype(np.float32)

        logger.info(f"Loaded image {image_path.name}: shape={image.shape}, dtype={image.dtype}")

        # Detect color checker
        try:
            detection_results = list(detect_colour_checkers_segmentation(image, additional_data=True))
        except Exception as e:
            logger.error(f"ColorChecker detection error: {e}")
            raise ValueError(f"ColorChecker detection failed: {e}")

        if not detection_results:
            logger.warning(f"No ColorChecker detected in {image_path}")
            return None

        # Use first detected checker
        checker_data = detection_results[0]
        swatch_colours, swatch_masks, checker_image, _ = checker_data.values

        logger.info(f"Detected {len(swatch_colours)} swatches")

        # Get reference swatches (with default flip to match common camera orientation)
        reference_checker = self._get_reference_checker()
        reference_swatches = colour.XYZ_to_RGB(
            colour.xyY_to_XYZ(list(reference_checker.data.values())),
            'sRGB',
            reference_checker.illuminant
        )

        # Generate unique detection ID
        detection_id = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        data = ColorCheckerData(
            detected_swatches=swatch_colours,
            reference_swatches=reference_swatches,
            swatch_masks=swatch_masks,
            checker_image=checker_image,
            source_image=str(image_path),
            detection_id=detection_id,
        )

        # Cache for session
        self._current_detection = data

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

        # Reshape swatches to 4x6 grid
        swatches = data.detected_swatches.reshape(4, 6, 3)
        masks = np.array(data.swatch_masks).reshape(4, 6, 4)

        if axis == 'horizontal':
            # Flip rows 0 and 2 horizontally (specific to ColorChecker layout)
            swatches[0] = swatches[0][::-1]
            swatches[2] = swatches[2][::-1]
            masks[0] = masks[0][::-1]
            masks[2] = masks[2][::-1]
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
        return new_data

    def generate_overlay_image(self, data: ColorCheckerData) -> bytes:
        """
        Generate PNG image with swatch boxes overlaid on checker image.

        Args:
            data: ColorCheckerData from detection

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

        # Draw swatch boxes with labels
        swatch_labels = list('ABCDEFGHIJKLMNOPQRSTUVWX')

        for i, mask in enumerate(data.swatch_masks):
            y1, y2, x1, x2 = [int(m) for m in mask]

            # Draw rectangle
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Draw label
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

        # Save as NPZ
        np.savez(
            profile_path,
            detected_swatches=data.detected_swatches,
            reference_swatches=data.reference_swatches,
            source_image=data.source_image,
            flip_horizontal=data.flip_h,
            flip_vertical=data.flip_v,
            rotation=data.rotation,
            created_at=datetime.now().isoformat(),
            checker_type='ColorChecker24',
        )

        logger.info(f"Saved ColorChecker profile: {profile_path}")
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
                return ColorCheckerData(
                    detected_swatches=data['detected_swatches'],
                    reference_swatches=data['reference_swatches'],
                    swatch_masks=[],  # Not saved in profile
                    checker_image=np.array([]),  # Not saved in profile
                    source_image=str(data['source_image']),
                    flip_h=bool(data['flip_horizontal']),
                    flip_v=bool(data['flip_vertical']),
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

    def calibrate_image(self, image: np.ndarray, data: ColorCheckerData) -> np.ndarray:
        """
        Apply color calibration to a single image.

        Args:
            image: Input image (RGB, float 0-1 or uint8/uint16)
            data: ColorCheckerData with calibration info

        Returns:
            Color-corrected image
        """
        if not COLOUR_AVAILABLE:
            raise ImportError("colour-science library not installed")

        # Normalize to float 0-1 if needed
        if image.dtype == np.uint8:
            image = image.astype(np.float32) / 255.0
        elif image.dtype == np.uint16:
            image = image.astype(np.float32) / 65535.0

        # Apply color correction using colour-science
        corrected = colour.colour_correction(
            image,
            data.detected_swatches,
            data.reference_swatches
        )

        return corrected

    def calibrate_batch(
        self,
        batch_path: str,
        checker_data: ColorCheckerData,
    ) -> List[CalibrationResult]:
        """
        Apply color calibration to all images in a batch.

        Args:
            batch_path: Path to batch folder
            checker_data: ColorCheckerData with calibration info

        Returns:
            List of CalibrationResult for each image
        """
        batch_path = Path(batch_path)
        results = []

        # Find source images (prefer cropped > tiff > raw)
        source_folder = None
        for folder_name in ['cropped', 'tiff', 'raw']:
            folder = batch_path / folder_name
            if folder.exists() and list(folder.iterdir()):
                source_folder = folder
                break

        if not source_folder:
            return [CalibrationResult(
                success=False,
                source_path=str(batch_path),
                error="No source images found"
            )]

        # Create output folder
        output_folder = batch_path / "color_calibrated"
        output_folder.mkdir(exist_ok=True)

        # Process each image
        image_extensions = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}

        for image_path in sorted(source_folder.iterdir()):
            if image_path.suffix.lower() not in image_extensions:
                continue

            try:
                # Load image
                image = colour.io.read_image(str(image_path))

                # Apply calibration
                corrected = self.calibrate_image(image, checker_data)

                # Save as 16-bit PNG
                corrected_clipped = np.clip(colour.cctf_encoding(corrected), 0, 1)
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
                logger.info(f"Calibrated: {image_path.name}")

            except Exception as e:
                logger.error(f"Failed to calibrate {image_path}: {e}")
                results.append(CalibrationResult(
                    success=False,
                    source_path=str(image_path),
                    error=str(e),
                ))

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

    def _get_reference_checker(self, flip_h: bool = True) -> 'ColourChecker':
        """
        Get reference ColorChecker with optional horizontal flip.
        Default flip matches common camera orientation.
        """
        checker = REFERENCE_COLOUR_CHECKER

        if flip_h:
            checker = self._flip_colour_checker(checker, 'horizontal')

        return checker

    def _flip_colour_checker(self, colour_checker: 'ColourChecker', flip_axis: str) -> 'ColourChecker':
        """
        Flip ColorChecker reference data.

        This is needed because the physical checker orientation may differ
        from how it appears in the captured image.
        """
        swatch_names = list(colour_checker.data.keys())
        swatch_values = list(colour_checker.data.values())
        rows = colour_checker.rows
        columns = colour_checker.columns

        # Reshape into grids
        swatch_array = np.array(swatch_values).reshape(rows, columns, 3)
        name_array = np.array(swatch_names).reshape(rows, columns)

        # Flip both names and values
        if flip_axis == 'horizontal':
            # Flip specific rows for ColorChecker24 layout
            name_array[0] = name_array[0][::-1]
            name_array[2] = name_array[2][::-1]
            swatch_array[0] = swatch_array[0][::-1]
            swatch_array[2] = swatch_array[2][::-1]
        elif flip_axis == 'vertical':
            swatch_array = np.flipud(swatch_array)
            name_array = np.flipud(name_array)
        else:
            raise ValueError("flip_axis must be 'horizontal' or 'vertical'")

        # Flatten back
        flipped_values = swatch_array.reshape(-1, 3).tolist()
        flipped_names = name_array.reshape(-1).tolist()
        flipped_data = dict(zip(flipped_names, flipped_values))

        return ColourChecker(
            name=f"{colour_checker.name} - Flipped {flip_axis}",
            data=flipped_data,
            illuminant=colour_checker.illuminant,
            rows=rows,
            columns=columns
        )
