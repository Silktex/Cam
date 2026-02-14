"""
Crop Service - Manual and Auto cropping for fabric images.
Optimized: Reads directly from RAW, outputs compressed 16-bit TIFF.

Interactive Workflow:
1. Get top image preview → show to user
2. Auto-detect OR manual select crop box on top image
3. Preview crop result on top image → user accepts/rejects
4. If accepted → apply same crop to all images
"""
import os
import io
import base64
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from .raw_utils import load_raw, save_tiff, is_raw_file, RAW_EXTENSIONS

logger = logging.getLogger(__name__)
TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
SUPPORTED_EXTENSIONS = TIFF_EXTENSIONS | IMAGE_EXTENSIONS

# Image position naming convention
POSITION_NAMES = ['top', 'side_1', 'side_2', 'side_3', 'side_4', 'side_5', 'side_6', 'side_7', 'side_8']


@dataclass
class CropResult:
    success: bool
    source_path: str
    output_path: Optional[str] = None
    bbox: Optional[List[int]] = None
    error: Optional[str] = None


class CropService:
    """Handles manual and auto cropping of images with interactive preview workflow."""

    def __init__(self, use_gpu: bool = None):
        self.use_gpu = use_gpu if use_gpu is not None else settings.USE_GPU

    def get_top_image_for_crop(self, batch_path: str) -> Optional[Dict]:
        """
        Get the TOP image for crop interface.
        Returns image info and existing thumbnail URL (already color-corrected).
        """
        batch_path = Path(batch_path)
        source_folder, source_type = self._get_source_folder(batch_path)
        if not source_folder:
            return None

        images = self._list_images(source_folder, source_type)
        top_image = self._find_top_image(images)

        if not top_image:
            return None

        batch_name = batch_path.name

        # Use existing thumbnail (already color-corrected from capture)
        thumb_path = batch_path / "thumbnail" / f"{top_image.stem}.jpg"

        # Prefer full_webview (2400px) over thumbnail (400px) for better crop quality
        webview_path = batch_path / "full_webview" / f"{top_image.stem}.jpg"

        if webview_path.exists():
            # Use full webview for better quality
            preview_img = cv2.imread(str(webview_path))
            if preview_img is None:
                return None
            preview_h, preview_w = preview_img.shape[:2]

            # Get original RAW dimensions
            full_img = self._load_image(top_image, source_type)
            if full_img is None:
                return None
            orig_h, orig_w = full_img.shape[:2]

            return {
                "batch_name": batch_name,
                "filename": top_image.name,
                "width": orig_w,              # Original RAW width
                "height": orig_h,             # Original RAW height
                "preview_width": preview_w,   # Preview image width (2400)
                "preview_height": preview_h,  # Preview image height
                "preview_url": f"/media/captures/{batch_name}/full_webview/{top_image.stem}.jpg",
                "thumbnail_url": f"/media/captures/{batch_name}/thumbnail/{top_image.stem}.jpg",
                "source_type": source_type,
            }
        elif thumb_path.exists():
            # Fallback to thumbnail
            thumb_img = cv2.imread(str(thumb_path))
            if thumb_img is None:
                return None
            thumb_h, thumb_w = thumb_img.shape[:2]

            full_img = self._load_image(top_image, source_type)
            if full_img is None:
                return None
            orig_h, orig_w = full_img.shape[:2]

            return {
                "batch_name": batch_name,
                "filename": top_image.name,
                "width": orig_w,
                "height": orig_h,
                "preview_width": thumb_w,
                "preview_height": thumb_h,
                "preview_url": f"/media/captures/{batch_name}/thumbnail/{top_image.stem}.jpg",
                "thumbnail_url": f"/media/captures/{batch_name}/thumbnail/{top_image.stem}.jpg",
                "source_type": source_type,
            }
        else:
            # No thumbnail exists, generate one
            img = self._load_image(top_image, source_type)
            if img is None:
                return None
            h, w = img.shape[:2]

            return {
                "batch_name": batch_name,
                "filename": top_image.name,
                "width": w,
                "height": h,
                "thumb_width": w,
                "thumb_height": h,
                "thumbnail_url": self._generate_thumbnail_base64(img),
                "source_type": source_type,
            }

    def auto_detect_crop(self, batch_path: str, crop_size: int = 2048) -> Optional[Dict]:
        """
        Auto-detect crop boundary on TOP image, then center a square crop
        of crop_size x crop_size on the detected region.
        Returns detected bbox without saving anything.
        """
        batch_path = Path(batch_path)
        source_folder, source_type = self._get_source_folder(batch_path)
        if not source_folder:
            return {"success": False, "error": "No source images found"}

        images = self._list_images(source_folder, source_type)
        top_image = self._find_top_image(images)

        if not top_image:
            return {"success": False, "error": "No top image found"}

        # Load image
        img = self._load_image(top_image, source_type)
        if img is None:
            return {"success": False, "error": "Failed to load image"}

        h, w = img.shape[:2]

        # Try to auto-detect crop boundary using contour detection
        try:
            detected_bbox = self._detect_fabric_boundary(img)
            if detected_bbox:
                dx1, dy1, dx2, dy2 = detected_bbox

                # Center of detected region
                cx = (dx1 + dx2) // 2
                cy = (dy1 + dy2) // 2

                # Clamp crop_size to image dimensions
                actual_size = min(crop_size, w, h)
                half = actual_size // 2

                # Center the square crop on the detected region, clamped to image bounds
                x1 = cx - half
                y1 = cy - half
                x2 = x1 + actual_size
                y2 = y1 + actual_size

                # Shift if out of bounds
                if x1 < 0:
                    x2 -= x1
                    x1 = 0
                if y1 < 0:
                    y2 -= y1
                    y1 = 0
                if x2 > w:
                    x1 -= (x2 - w)
                    x2 = w
                if y2 > h:
                    y1 -= (y2 - h)
                    y2 = h

                # Final clamp
                x1 = max(0, x1)
                y1 = max(0, y1)

                # Generate preview of cropped result
                cropped = img[y1:y2, x1:x2]
                preview_b64 = self._generate_thumbnail_base64(cropped, max_size=800)

                return {
                    "success": True,
                    "bbox": [x1, y1, x2, y2],
                    "crop_width": x2 - x1,
                    "crop_height": y2 - y1,
                    "original_width": w,
                    "original_height": h,
                    "crop_size": actual_size,
                    "detected_bbox": [dx1, dy1, dx2, dy2],
                    "preview_url": preview_b64,
                    "method": "auto",
                }
            else:
                return {"success": False, "error": "Could not detect fabric boundary"}
        except Exception as e:
            logger.error(f"Auto-detect failed: {e}")
            return {"success": False, "error": str(e)}

    def preview_manual_crop(self, batch_path: str, bbox: List[int]) -> Optional[Dict]:
        """
        Preview manual crop on TOP image without saving.
        Returns preview image as base64.
        """
        batch_path = Path(batch_path)
        source_folder, source_type = self._get_source_folder(batch_path)
        if not source_folder:
            return {"success": False, "error": "No source images found"}

        images = self._list_images(source_folder, source_type)
        top_image = self._find_top_image(images)

        if not top_image:
            return {"success": False, "error": "No top image found"}

        img = self._load_image(top_image, source_type)
        if img is None:
            return {"success": False, "error": "Failed to load image"}

        h, w = img.shape[:2]
        x1, y1, x2, y2 = bbox

        # Ensure correct ordering
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        # Clamp to image bounds
        x1 = max(0, min(x1, w))
        x2 = max(0, min(x2, w))
        y1 = max(0, min(y1, h))
        y2 = max(0, min(y2, h))

        if x2 - x1 < 10 or y2 - y1 < 10:
            return {"success": False, "error": "Crop region too small"}

        # Crop and generate preview
        cropped = img[y1:y2, x1:x2]
        preview_b64 = self._generate_thumbnail_base64(cropped, max_size=800)

        return {
            "success": True,
            "bbox": [x1, y1, x2, y2],
            "crop_width": x2 - x1,
            "crop_height": y2 - y1,
            "original_width": w,
            "original_height": h,
            "preview_url": preview_b64,
            "method": "manual",
        }

    def apply_crop_to_all(
        self,
        batch_path: str,
        bbox: List[int] = None,
        crop_type: str = "manual",
        points: List[Dict] = None,
        rotation: float = 0,
    ) -> List[CropResult]:
        """
        Apply confirmed crop to ALL images in the batch.
        Supports both simple bbox crop and 4-point perspective transform with rotation.

        Args:
            batch_path: Path to batch folder
            bbox: Simple bounding box [x1, y1, x2, y2] (legacy)
            crop_type: 'manual' or 'auto'
            points: 4 corner points [{x, y}, ...] for perspective transform
            rotation: Rotation angle in degrees
        """
        batch_path = Path(batch_path)
        results = []

        source_folder, source_type = self._get_source_folder(batch_path)
        if not source_folder:
            return [CropResult(
                success=False,
                source_path=str(batch_path),
                error="No source images found (raw/ or tiff/ folder)"
            )]

        logger.info(f"Applying {crop_type} crop to all images from {source_folder}")
        logger.info(f"Crop params - rotation: {rotation} (type: {type(rotation)}), points: {points is not None}, bbox: {bbox is not None}")

        # Create output folders
        output_folder = batch_path / "cropped"
        output_folder.mkdir(exist_ok=True)

        thumbnail_folder = batch_path / "cropped_thumbnail"
        thumbnail_folder.mkdir(exist_ok=True)

        # Get all images
        images = self._list_images(source_folder, source_type)

        # Determine crop method
        use_perspective = points is not None and len(points) == 4

        for image_path in images:
            try:
                img = self._load_image(image_path, source_type)
                if img is None:
                    results.append(CropResult(
                        success=False,
                        source_path=str(image_path),
                        error="Failed to load image"
                    ))
                    continue

                h, w = img.shape[:2]

                # Apply crop FIRST on the original image
                # (UI shows rotated image but crop points are in original coordinate space)
                if use_perspective:
                    # 4-point perspective transform
                    logger.info(f"Perspective crop on {image_path.name}: img size {w}x{h}, points: {points}")
                    cropped = self._perspective_crop(img, points)
                elif bbox:
                    # Simple bbox crop
                    x1, y1, x2, y2 = bbox
                    x1, x2 = min(x1, x2), max(x1, x2)
                    y1, y2 = min(y1, y2), max(y1, y2)

                    cx1 = max(0, min(x1, w))
                    cx2 = max(0, min(x2, w))
                    cy1 = max(0, min(y1, h))
                    cy2 = max(0, min(y2, h))

                    if cx2 - cx1 < 1 or cy2 - cy1 < 1:
                        results.append(CropResult(
                            success=False,
                            source_path=str(image_path),
                            error="Crop region too small"
                        ))
                        continue

                    cropped = img[cy1:cy2, cx1:cx2]
                else:
                    results.append(CropResult(
                        success=False,
                        source_path=str(image_path),
                        error="No crop parameters provided"
                    ))
                    continue

                if cropped is None or cropped.size == 0:
                    results.append(CropResult(
                        success=False,
                        source_path=str(image_path),
                        error="Crop resulted in empty image"
                    ))
                    continue

                # NOTE: No rotation needed after perspective crop!
                # The UI inverse-transforms the crop points before sending them.
                # The perspective transform maps those (rotated) points to a straight rectangle.
                # So the output is already straightened - no additional rotation required.
                logger.info(f"Rotation value received: {rotation} (applied via point transform, not image rotation)")

                # Save as TIFF
                output_path = output_folder / f"{image_path.stem}.tiff"
                self._save_image(cropped, output_path)

                # Generate thumbnail for cropped image
                thumbnail_path = thumbnail_folder / f"{image_path.stem}.jpg"
                self._save_thumbnail(cropped, thumbnail_path)

                results.append(CropResult(
                    success=True,
                    source_path=str(image_path),
                    output_path=str(output_path),
                    bbox=bbox if bbox else [0, 0, cropped.shape[1], cropped.shape[0]]
                ))
                logger.info(f"Cropped: {image_path.name} -> {output_path.name}")

            except Exception as e:
                logger.error(f"Error cropping {image_path}: {e}")
                results.append(CropResult(
                    success=False,
                    source_path=str(image_path),
                    error=str(e)
                ))

        return results

    def _rotate_image(self, img: np.ndarray, angle: float) -> np.ndarray:
        """
        Rotate image by given angle (degrees) around center.
        Expands canvas to fit the entire rotated image without clipping.
        """
        h, w = img.shape[:2]
        center = (w / 2, h / 2)

        # Get rotation matrix
        M = cv2.getRotationMatrix2D(center, angle, 1.0)

        # Calculate new canvas size to fit rotated image
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int(h * sin + w * cos)
        new_h = int(h * cos + w * sin)

        # Adjust translation to center rotated image in new canvas
        M[0, 2] += (new_w - w) / 2
        M[1, 2] += (new_h - h) / 2

        # Perform rotation with expanded canvas
        rotated = cv2.warpAffine(img, M, (new_w, new_h), borderMode=cv2.BORDER_CONSTANT)
        return rotated

    def _perspective_crop(self, img: np.ndarray, points: List[Dict]) -> np.ndarray:
        """
        Apply perspective transform using 4 corner points.
        Points should be in order: top-left, top-right, bottom-right, bottom-left
        """
        # Convert points to numpy array
        src_points = np.float32([
            [points[0]['x'], points[0]['y']],
            [points[1]['x'], points[1]['y']],
            [points[2]['x'], points[2]['y']],
            [points[3]['x'], points[3]['y']],
        ])

        # Calculate output dimensions (average of opposite sides)
        top_width = np.sqrt((points[1]['x'] - points[0]['x'])**2 + (points[1]['y'] - points[0]['y'])**2)
        bottom_width = np.sqrt((points[2]['x'] - points[3]['x'])**2 + (points[2]['y'] - points[3]['y'])**2)
        left_height = np.sqrt((points[3]['x'] - points[0]['x'])**2 + (points[3]['y'] - points[0]['y'])**2)
        right_height = np.sqrt((points[2]['x'] - points[1]['x'])**2 + (points[2]['y'] - points[1]['y'])**2)

        out_width = int((top_width + bottom_width) / 2)
        out_height = int((left_height + right_height) / 2)

        # Destination points (rectangle)
        dst_points = np.float32([
            [0, 0],
            [out_width, 0],
            [out_width, out_height],
            [0, out_height],
        ])

        # Get perspective transform matrix and apply
        M = cv2.getPerspectiveTransform(src_points, dst_points)
        warped = cv2.warpPerspective(img, M, (out_width, out_height))

        return warped

    def _detect_fabric_boundary(self, img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect fabric boundary using edge detection and contours.
        Works with 16-bit images by converting to 8-bit for processing.
        """
        h, w = img.shape[:2]

        # Convert to grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        # Convert 16-bit to 8-bit for contour detection
        if gray.dtype == np.uint16:
            # Normalize to 8-bit
            gray = (gray / 256).astype(np.uint8)

        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Use adaptive thresholding for better results
        # First try Otsu's method
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Morphological operations to clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            # Try edge detection as fallback
            edges = cv2.Canny(blurred, 50, 150)
            edges = cv2.dilate(edges, kernel, iterations=2)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Find the largest contour that's not the entire image
        valid_contours = []
        image_area = h * w

        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Contour should be significant but not the entire image
            if area > image_area * 0.05 and area < image_area * 0.95:
                valid_contours.append(cnt)

        if not valid_contours:
            # If no valid contours, use the largest one
            valid_contours = contours

        largest = max(valid_contours, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(largest)

        # Add padding (3%)
        pad = int(min(bw, bh) * 0.03)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + bh + pad)

        return (x1, y1, x2, y2)

    def _find_top_image(self, images: List[Path]) -> Optional[Path]:
        """Find the TOP image from the list."""
        for img in images:
            name_lower = img.name.lower()
            if '_top' in name_lower or name_lower.startswith('top'):
                return img
        # Return first image if no top found
        return images[0] if images else None

    def _generate_thumbnail_base64(self, img: np.ndarray, max_size: int = 1200, apply_gamma: bool = True) -> str:
        """
        Generate base64-encoded JPEG thumbnail from image.

        Args:
            img: Input image (can be 8-bit or 16-bit)
            max_size: Maximum dimension
            apply_gamma: Apply gamma correction (True for RAW/linear images)
        """
        h, w = img.shape[:2]

        # Convert 16-bit to 8-bit
        if img.dtype == np.uint16:
            if apply_gamma:
                # RAW images are in linear space, apply gamma 2.2 for display
                img_float = img.astype(np.float32) / 65535.0
                img_float = np.power(np.clip(img_float, 0, 1), 1.0 / 2.2)
                img = (img_float * 255).astype(np.uint8)
            else:
                img = (img / 256).astype(np.uint8)

        # Resize if too large
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64 = base64.b64encode(buffer).decode('utf-8')
        return f"data:image/jpeg;base64,{b64}"

    def _save_thumbnail(self, img: np.ndarray, path: Path, max_size: int = 800):
        """
        Save image as JPEG thumbnail.
        Image is expected to already be in sRGB with proper gamma.
        """
        h, w = img.shape[:2]

        # Convert 16-bit to 8-bit (simple scaling, image already has proper gamma)
        if img.dtype == np.uint16:
            img = (img / 256).astype(np.uint8)

        # Resize if too large
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Save as JPEG
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        logger.info(f"Saved thumbnail: {path.name}")

    # ─── Legacy methods for backward compatibility ───

    def manual_crop(
        self,
        batch_path: str,
        bbox: Tuple[int, int, int, int],
        apply_to_all: bool = True,
        specific_images: List[str] = None,
    ) -> List[CropResult]:
        """Legacy: Direct manual crop (no preview). Use apply_crop_to_all instead."""
        return self.apply_crop_to_all(str(batch_path), list(bbox), crop_type="manual")

    def auto_crop(
        self,
        batch_path: str,
        prompt: str = "fabric sample",
        apply_to_all: bool = True,
    ) -> List[CropResult]:
        """Legacy: Direct auto crop. Now uses preview workflow."""
        batch_path = Path(batch_path)

        # Auto-detect on top image
        result = self.auto_detect_crop(str(batch_path))

        if not result.get("success"):
            return [CropResult(
                success=False,
                source_path=str(batch_path),
                error=result.get("error", "Auto-detect failed")
            )]

        # Apply to all
        bbox = result["bbox"]
        return self.apply_crop_to_all(str(batch_path), bbox, crop_type="auto")

    def get_preview(self, batch_path: str) -> Optional[Dict]:
        """Legacy: Get preview info. Use get_top_image_for_crop instead."""
        return self.get_top_image_for_crop(batch_path)

    # ─── Internal helper methods ───

    def _get_source_folder(self, batch_path: Path) -> Tuple[Optional[Path], str]:
        """
        Get source folder for cropping.
        Priority: raw/ (direct from RAW) > tiff/ > root
        """
        raw_folder = batch_path / "raw"
        if raw_folder.exists():
            raw_files = [f for f in raw_folder.iterdir()
                        if f.suffix.lower() in RAW_EXTENSIONS]
            if raw_files:
                return raw_folder, 'raw'

        tiff_folder = batch_path / "tiff"
        if tiff_folder.exists() and list(tiff_folder.glob("*.tif*")):
            return tiff_folder, 'tiff'

        if list(batch_path.glob("*.tiff")) or list(batch_path.glob("*.tif")):
            return batch_path, 'tiff'

        return None, ''

    def _list_images(self, folder: Path, source_type: str = 'tiff') -> List[Path]:
        """List all images in folder based on source type."""
        images = []
        if source_type == 'raw':
            for ext in RAW_EXTENSIONS:
                images.extend(folder.glob(f"*{ext}"))
                images.extend(folder.glob(f"*{ext.upper()}"))
        else:
            for ext in SUPPORTED_EXTENSIONS:
                images.extend(folder.glob(f"*{ext}"))
                images.extend(folder.glob(f"*{ext.upper()}"))
        return sorted(images)

    def _load_image(self, path: Path, source_type: str = 'tiff') -> Optional[np.ndarray]:
        """Load image from path."""
        if source_type == 'raw' or is_raw_file(path):
            # Load RAW with display-ready settings (sRGB, proper gamma)
            # This matches how thumbnails are generated during capture
            rgb = self._load_raw_for_display(path)
            if rgb is not None:
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return None
        else:
            return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)

    def _load_raw_for_display(self, path: Path) -> Optional[np.ndarray]:
        """
        Load RAW file using centralized raw_utils settings.
        Returns linear sRGB 16-bit — consistent with camera_service TIFF output.
        """
        return load_raw(path)

    def _save_image(self, img: np.ndarray, path: Path):
        """
        Save image as compressed 16-bit TIFF.
        Image is expected to already be in sRGB color space with proper gamma.
        """
        if len(img.shape) == 3 and img.shape[2] == 3:
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        else:
            img_rgb = img

        if not save_tiff(img_rgb, path, compression='zlib'):
            logger.warning("save_tiff failed, using cv2 fallback")
            cv2.imwrite(str(path), img)
