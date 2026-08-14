"""
OpenCV-based auto-crop fallback when SAM3 is not available.
Uses bilateral filtering + multi-strategy contour detection to find
fabric/rectangular objects in images.
"""
import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np

SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp',
}


@dataclass
class CropResult:
    input_path: str
    output_paths: List[str] = field(default_factory=list)
    success: bool = False
    message: str = ""
    num_objects: int = 0
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class OpenCVCropConfig:
    min_area_ratio: float = 0.01
    max_area_ratio: float = 0.4
    padding: int = 20
    output_format: str = "tiff"
    save_metadata: bool = True
    min_crop_width: int = 200
    min_crop_height: int = 200
    min_aspect_ratio: float = 0.3
    max_aspect_ratio: float = 3.0
    min_rectangularity: float = 0.5
    max_objects: int = 5


class OpenCVAutoCropper:
    """Fallback auto-cropper using OpenCV contour detection."""

    def __init__(self, config: OpenCVCropConfig = None):
        self.config = config or OpenCVCropConfig()

    def read_image(self, path: str) -> np.ndarray:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Cannot read image: {path}")
        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]
        return img

    def _downscale(self, image: np.ndarray, max_dim: int = 1500):
        """Downscale image for processing, return (small_img, scale_factor)."""
        h, w = image.shape[:2]
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            small = image.copy()
        return small, scale

    def _to_gray(self, image: np.ndarray) -> np.ndarray:
        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image.copy()

    def _filter_contours(
        self, contours, small_area: float, scale: float
    ) -> List[Tuple[np.ndarray, float]]:
        """Filter and score contours by area, aspect ratio, rectangularity."""
        min_area = small_area * self.config.min_area_ratio
        max_area = small_area * self.config.max_area_ratio
        min_w = self.config.min_crop_width * scale
        min_h = self.config.min_crop_height * scale

        results = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < min_w or bh < min_h:
                continue

            aspect = bw / bh if bh > 0 else 0
            if aspect < self.config.min_aspect_ratio or aspect > self.config.max_aspect_ratio:
                continue

            rect_area = bw * bh
            rectangularity = area / rect_area if rect_area > 0 else 0
            if rectangularity < self.config.min_rectangularity:
                continue

            score = (area / small_area) * rectangularity
            results.append((contour, score, area))

        # Sort by area descending
        results.sort(key=lambda x: x[2], reverse=True)
        return [(c, s) for c, s, _ in results]

    def _deduplicate(
        self, candidates: List[Tuple[np.ndarray, float]]
    ) -> List[Tuple[np.ndarray, float]]:
        """Remove duplicate detections by center proximity."""
        unique = []
        seen_centers = []

        for contour, score in candidates:
            x, y, bw, bh = cv2.boundingRect(contour)
            cx, cy = x + bw // 2, y + bh // 2

            is_dup = False
            for sx, sy, sw, sh in seen_centers:
                if abs(cx - sx) < max(bw, sw) * 0.4 and abs(cy - sy) < max(bh, sh) * 0.4:
                    is_dup = True
                    break
            if not is_dup:
                seen_centers.append((cx, cy, bw, bh))
                unique.append((contour, score))

            if len(unique) >= self.config.max_objects:
                break

        return unique

    def _find_objects(self, image: np.ndarray) -> List[Tuple[np.ndarray, float]]:
        """
        Multi-strategy object detection.
        Tries several approaches and merges/deduplicates results.
        """
        small, scale = self._downscale(image)
        gray = self._to_gray(small)
        sh, sw = gray.shape[:2]
        small_area = sh * sw

        all_candidates = []
        kernel_large = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))

        # Strategy 1: Bilateral filter + adaptive threshold
        # Bilateral preserves edges while smoothing texture
        bilateral = cv2.bilateralFilter(gray, 15, 75, 75)
        smooth = cv2.GaussianBlur(bilateral, (31, 31), 0)
        # Edges on the smoothed image highlight object boundaries
        edges = cv2.Canny(smooth, 15, 50)
        kernel_edge = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        closed = cv2.dilate(edges, kernel_edge, iterations=2)
        closed = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, kernel_edge, iterations=3)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_candidates.extend(self._filter_contours(contours, small_area, scale))

        # Strategy 2: Local variance thresholding
        # Fabric/uniform regions have low local variance vs textured background
        blurred = cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)
        mean_val = cv2.blur(blurred, (41, 41))
        mean_sq = cv2.blur(blurred ** 2, (41, 41))
        variance = np.clip(mean_sq - mean_val ** 2, 0, None)
        # Low variance + above-median brightness = likely object
        var_thresh = np.percentile(variance, 35)
        median_brightness = np.median(blurred)
        mask = ((variance < var_thresh) & (blurred > median_brightness * 0.8)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_large, iterations=3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_large, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_candidates.extend(self._filter_contours(contours, small_area, scale))

        # Strategy 3: Otsu on bilateral-filtered image
        _, otsu = cv2.threshold(bilateral, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel_large, iterations=2)
        otsu = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, kernel_large, iterations=2)
        contours, _ = cv2.findContours(otsu, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        all_candidates.extend(self._filter_contours(contours, small_area, scale))

        # Scale all contours back to original coordinates
        scaled = []
        for contour, score in all_candidates:
            if scale < 1.0:
                contour = (contour.astype(np.float64) / scale).astype(np.int32)
            scaled.append((contour, score))

        return self._deduplicate(scaled)

    def process_image(
        self,
        input_path: str,
        output_dir: str,
        prompt: Optional[str] = None,
    ) -> CropResult:
        """Process a single image to detect and crop objects."""
        try:
            image = self.read_image(input_path)
            h, w = image.shape[:2]

            detections = self._find_objects(image)

            if not detections:
                return CropResult(
                    input_path=input_path,
                    success=True,
                    message="No objects detected in image (OpenCV fallback)",
                    num_objects=0,
                )

            base_name = Path(input_path).stem
            save_dir = os.path.join(output_dir, base_name)
            os.makedirs(save_dir, exist_ok=True)

            output_paths = []
            metadata = {
                "source": input_path,
                "prompt": "opencv-fallback",
                "image_size": [w, h],
                "crop_type": "rectangular",
                "objects": [],
            }

            for obj_id, (contour, score) in enumerate(detections):
                x, y, bw, bh = cv2.boundingRect(contour)
                pad = self.config.padding
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(w, x + bw + pad)
                y2 = min(h, y + bh + pad)

                cropped = image[y1:y2, x1:x2]
                crop_h, crop_w = cropped.shape[:2]

                crop_filename = f"fabric_{obj_id}.{self.config.output_format}"
                crop_path = os.path.join(save_dir, crop_filename)
                cv2.imwrite(crop_path, cropped)
                output_paths.append(crop_path)

                metadata["objects"].append({
                    "id": obj_id,
                    "bbox": [x1, y1, x2, y2],
                    "crop_size": [crop_w, crop_h],
                    "score": float(score),
                    "area": int(cv2.contourArea(contour)),
                    "crop_path": crop_path,
                })

            if self.config.save_metadata:
                meta_path = os.path.join(save_dir, f"{base_name}_metadata.json")
                with open(meta_path, "w") as f:
                    json.dump(metadata, f, indent=4)

            return CropResult(
                input_path=input_path,
                output_paths=output_paths,
                success=True,
                message=f"Detected {len(detections)} objects (OpenCV fallback)",
                num_objects=len(detections),
                metadata=metadata,
            )

        except Exception as e:
            return CropResult(
                input_path=input_path,
                success=False,
                message=f"Error: {e}",
            )

    def process_directory(
        self,
        input_dir: str,
        output_dir: str,
        prompt: Optional[str] = None,
    ) -> List[CropResult]:
        if not os.path.isdir(input_dir):
            return [CropResult(input_path=input_dir, success=False, message=f"Not found: {input_dir}")]

        os.makedirs(output_dir, exist_ok=True)
        results = []
        for filename in sorted(os.listdir(input_dir)):
            ext = os.path.splitext(filename)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                path = os.path.join(input_dir, filename)
                results.append(self.process_image(path, output_dir, prompt))
        return results
