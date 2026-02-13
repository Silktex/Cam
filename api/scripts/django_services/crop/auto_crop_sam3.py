#!/usr/bin/env python3
"""
Auto-crop fabric images using SAM3 (Segment Anything Model 3) from Meta AI.

This script is specifically optimized for detecting and cropping fabric/textile
samples from images. It uses a permanent fabric-detection prompt and ensures
rectangular/square output crops.

Requirements:
    - SAM3 repository installed: git clone https://github.com/facebookresearch/sam3.git && cd sam3 && pip install -e .
    - HuggingFace access for SAM3 model checkpoints

Usage:
    python auto_crop_sam3.py /path/to/image.jpg
    python auto_crop_sam3.py /path/to/images/
    python auto_crop_sam3.py -i /path/to/image.jpg -o /path/to/output/
"""

import argparse
import json
import os
import sys
import gc
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm

# SAM3 imports
try:
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    HAS_SAM3 = True
except ImportError:
    HAS_SAM3 = False
    print("Warning: SAM3 not available. Install from: https://github.com/facebookresearch/sam3")

__version__ = "2.0.0"

# Supported image formats
RAW_EXTENSIONS = {'.arw', '.nef', '.cr2', '.cr3', '.dng', '.raf', '.orf', '.rw2'}
STANDARD_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}
SUPPORTED_EXTENSIONS = RAW_EXTENSIONS | STANDARD_EXTENSIONS

# =============================================================================
# PERMANENT FABRIC DETECTION PROMPTS
# =============================================================================
# These prompts are optimized for detecting fabric/textile samples in images.
# Multiple prompts are tried in order to maximize detection success.

FABRIC_PROMPTS = [
    # Primary prompt - simple single word works best with SAM3
    "fabric",
    # Secondary prompt - alternative simple term
    "cloth",
    # Tertiary prompt - multi-word with good detection rate
    "flat rectangular material, cloth, fabric",
    # Fallback prompts - broader detection
    "rectangular fabric, square cloth, textile piece",
    "textile material, fabric swatch",
]

# Default prompt used for fabric detection
DEFAULT_FABRIC_PROMPT = FABRIC_PROMPTS[0]


@dataclass
class CropResult:
    """Result of a single crop operation."""
    input_path: str
    output_paths: List[str] = field(default_factory=list)
    success: bool = False
    message: str = ""
    num_objects: int = 0
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SAM3Config:
    """Configuration for SAM3 auto-crop optimized for fabric detection."""
    # Model settings
    device: str = "cuda" if torch.cuda.is_available() else "cpu"

    # Detection settings - optimized for fabric samples
    threshold: float = 0.3  # Lower threshold for better fabric detection
    mask_threshold: float = 0.4
    max_objects: int = 10  # Usually only a few fabric samples per image
    min_area_ratio: float = 0.01  # Fabric samples are usually significant portion of image
    max_overlap_iou: float = 0.5  # More aggressive duplicate removal

    # Crop settings
    padding: int = 20  # More padding for fabric edges
    output_format: str = "tiff"
    save_masks: bool = False  # Disabled by default - use --save-masks to enable
    save_overlays: bool = True
    save_metadata: bool = True

    # Fabric-specific settings
    use_multi_prompt: bool = True  # Try multiple prompts if first fails
    force_rectangular: bool = True  # Force rectangular/square output crops
    min_aspect_ratio: float = 0.3  # Minimum width/height ratio (avoid thin strips)
    max_aspect_ratio: float = 3.0  # Maximum width/height ratio

    # Precise cropping settings - NEW
    precise_crop: bool = True  # Ensure crop rectangle stays WITHIN detected fabric
    inward_margin: int = 5  # Pixels to shrink inward from fabric boundary for safety
    use_contour_fitting: bool = True  # Use contour-based rectangle fitting
    min_coverage_ratio: float = 0.85  # Minimum ratio of crop area that must be fabric

    # Small region filtering settings
    min_crop_width: int = 100  # Minimum crop width in pixels
    min_crop_height: int = 100  # Minimum crop height in pixels
    cleanup_mask: bool = True  # Apply morphological cleanup to remove small islands
    min_component_area: int = 500  # Minimum connected component area to keep (pixels)

    # Perspective correction settings
    perspective_correct: bool = True  # Apply perspective transform to straighten fabric
    perspective_threshold: float = 0.95  # Only apply if fabric coverage below this ratio


class SAM3AutoCropper:
    """Auto-cropper using SAM3 for object detection and segmentation."""

    def __init__(self, config: SAM3Config):
        """
        Initialize SAM3 auto-cropper.

        Args:
            config: Configuration parameters
        """
        self.config = config
        self.model = None
        self.processor = None
        self._load_model()

    def _load_model(self):
        """Load SAM3 model and processor."""
        if not HAS_SAM3:
            raise ImportError(
                "SAM3 not available. Install from: "
                "git clone https://github.com/facebookresearch/sam3.git && cd sam3 && pip install -e ."
            )

        print(f"Loading SAM3 model...")
        print(f"Device: {self.config.device}")

        # Clear GPU memory
        torch.cuda.empty_cache()
        gc.collect()

        # Build SAM3 model
        # Find SAM3 installation path for BPE tokenizer
        import sam3
        # Handle editable install where __file__ may be None
        if sam3.__file__ is not None:
            sam3_path = os.path.dirname(sam3.__file__)
        else:
            # For editable installs, use the spec origin or default path
            import importlib.util
            spec = importlib.util.find_spec("sam3")
            if spec and spec.origin:
                sam3_path = os.path.dirname(spec.origin)
            else:
                # Fallback to common locations
                sam3_path = "/tmp/sam3/sam3"

        bpe_path = os.path.join(sam3_path, "assets", "bpe_simple_vocab_16e6.txt.gz")
        if not os.path.exists(bpe_path):
            # Try alternate location
            bpe_path = "/tmp/sam3/sam3/assets/bpe_simple_vocab_16e6.txt.gz"

        self.model = build_sam3_image_model(
            bpe_path=bpe_path,
            device=self.config.device
        )
        self.processor = Sam3Processor(self.model, device=self.config.device)

        print("SAM3 model loaded successfully!")

    def cleanup_mask(self, mask: np.ndarray) -> np.ndarray:
        """
        Clean up mask by removing small connected components (islands) and filling holes.

        This helps eliminate small spurious detections that result in unwanted
        small cropped regions.

        Args:
            mask: Binary mask (0/1 or 0/255)

        Returns:
            Cleaned binary mask with small components removed
        """
        if not self.config.cleanup_mask:
            return mask

        # Ensure binary mask
        binary_mask = (mask > 0).astype(np.uint8)

        # Find connected components
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary_mask, connectivity=8
        )

        # Create output mask keeping only large enough components
        cleaned_mask = np.zeros_like(binary_mask)

        for label_id in range(1, num_labels):  # Skip background (label 0)
            area = stats[label_id, cv2.CC_STAT_AREA]
            if area >= self.config.min_component_area:
                cleaned_mask[labels == label_id] = 1

        # Optional: Fill small holes in the remaining regions
        # Use morphological closing to fill small gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_CLOSE, kernel)

        return cleaned_mask

    def get_quadrilateral_corners(
        self,
        mask: np.ndarray
    ) -> Optional[np.ndarray]:
        """
        Find the 4 corners of the fabric region from the mask.

        Uses contour approximation to find a quadrilateral, or falls back
        to minimum area rotated rectangle if a clean quad isn't found.

        Args:
            mask: Binary mask of the fabric region

        Returns:
            4x2 numpy array of corner points ordered as:
            [top-left, top-right, bottom-right, bottom-left]
            or None if corners cannot be determined
        """
        # Ensure binary mask
        binary_mask = (mask > 0).astype(np.uint8) * 255

        # Find contours
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Get the largest contour
        largest_contour = max(contours, key=cv2.contourArea)

        # Try to approximate to a quadrilateral
        epsilon = 0.02 * cv2.arcLength(largest_contour, True)
        approx = cv2.approxPolyDP(largest_contour, epsilon, True)

        if len(approx) == 4:
            # Found a quadrilateral directly
            corners = approx.reshape(4, 2).astype(np.float32)
        else:
            # Fallback to minimum area rotated rectangle
            rect = cv2.minAreaRect(largest_contour)
            corners = cv2.boxPoints(rect).astype(np.float32)

        # Order corners: top-left, top-right, bottom-right, bottom-left
        corners = self._order_corners(corners)

        return corners

    def _order_corners(self, corners: np.ndarray) -> np.ndarray:
        """
        Order corners in a consistent way: TL, TR, BR, BL.

        Args:
            corners: 4x2 array of corner points

        Returns:
            4x2 array with corners ordered as [TL, TR, BR, BL]
        """
        # Sort by y-coordinate (top to bottom)
        sorted_by_y = corners[np.argsort(corners[:, 1])]

        # Top two points (smallest y values)
        top_points = sorted_by_y[:2]
        # Bottom two points (largest y values)
        bottom_points = sorted_by_y[2:]

        # Sort top points by x (left to right)
        top_left, top_right = top_points[np.argsort(top_points[:, 0])]

        # Sort bottom points by x (left to right)
        bottom_left, bottom_right = bottom_points[np.argsort(bottom_points[:, 0])]

        return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)

    def apply_perspective_transform(
        self,
        image: np.ndarray,
        mask: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Apply perspective transform to straighten the fabric region.

        Only applies if the bounding rectangle covers more area than the fabric
        (i.e., there's background visible in the crop). This avoids unnecessary
        transforms when the crop is already tightly fitted.

        Args:
            image: RGB numpy array (cropped image)
            mask: Binary mask of the fabric region (cropped)

        Returns:
            Tuple of (transformed_image, transformed_mask)
        """
        if not self.config.perspective_correct:
            return image, mask

        # Calculate areas to decide if transform is needed
        crop_h, crop_w = image.shape[:2]
        rectangle_area = crop_w * crop_h
        fabric_area = np.sum(mask > 0)

        # Only apply perspective transform if rectangle covers more area than fabric
        # (meaning there's background/empty space in the crop)
        coverage_ratio = fabric_area / rectangle_area if rectangle_area > 0 else 1.0

        if coverage_ratio >= self.config.perspective_threshold:
            print(f"    Skipping perspective transform: fabric coverage {coverage_ratio:.1%} (>= {self.config.perspective_threshold:.0%} threshold)")
            return image, mask

        print(f"    Applying perspective transform: fabric coverage {coverage_ratio:.1%}")

        # Get the corners of the fabric region
        corners = self.get_quadrilateral_corners(mask)

        if corners is None:
            print("    Warning: Could not detect corners for perspective correction")
            return image, mask

        # Calculate the dimensions of the output rectangle
        # Use the maximum of the widths and heights to preserve detail
        width_top = np.linalg.norm(corners[1] - corners[0])
        width_bottom = np.linalg.norm(corners[2] - corners[3])
        height_left = np.linalg.norm(corners[3] - corners[0])
        height_right = np.linalg.norm(corners[2] - corners[1])

        max_width = int(max(width_top, width_bottom))
        max_height = int(max(height_left, height_right))

        # Ensure minimum dimensions
        max_width = max(max_width, 50)
        max_height = max(max_height, 50)

        # No margin needed - output is just the fabric region
        output_width = max_width
        output_height = max_height

        # Define destination points (full rectangle, no margin)
        dst_corners = np.array([
            [0, 0],                           # Top-left
            [output_width, 0],                # Top-right
            [output_width, output_height],    # Bottom-right
            [0, output_height]                # Bottom-left
        ], dtype=np.float32)

        # Compute the perspective transform matrix
        transform_matrix = cv2.getPerspectiveTransform(corners, dst_corners)

        # Apply the transform to the image (no background fill - use BORDER_REPLICATE)
        transformed_image = cv2.warpPerspective(
            image,
            transform_matrix,
            (output_width, output_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE  # Replicate edge pixels instead of filling
        )

        # Apply the transform to the mask
        transformed_mask = cv2.warpPerspective(
            (mask * 255).astype(np.uint8),
            transform_matrix,
            (output_width, output_height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255  # Assume transformed region is all fabric
        )

        # Convert mask back to 0/1
        transformed_mask = (transformed_mask > 127).astype(np.uint8)

        return transformed_image, transformed_mask

    def read_image(self, path: str) -> Image.Image:
        """
        Read image from file.

        Args:
            path: Image file path

        Returns:
            PIL Image in RGB mode
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        ext = os.path.splitext(path)[1].lower()

        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {ext}")

        # Handle RAW formats
        if ext in RAW_EXTENSIONS:
            try:
                import rawpy
                with rawpy.imread(path) as raw:
                    rgb_array = raw.postprocess()
                return Image.fromarray(rgb_array)
            except ImportError:
                raise ValueError(f"rawpy not installed, cannot read RAW format: {ext}")
            except Exception as e:
                raise ValueError(f"Cannot read RAW image: {path} - {e}")

        # Handle standard formats
        try:
            image = Image.open(path).convert("RGB")
            return image
        except Exception as e:
            raise ValueError(f"Cannot read image: {path} - {e}")

    def segment_image(
        self,
        image: Image.Image,
        prompt: str
    ) -> Tuple[List[np.ndarray], List[List[float]], List[float]]:
        """
        Segment image using text prompt.

        Args:
            image: PIL Image
            prompt: Text description of objects to detect

        Returns:
            Tuple of (masks, boxes, scores)
        """
        # Set image in processor
        inference_state = self.processor.set_image(image)

        # Run text prompt
        output = self.processor.set_text_prompt(
            state=inference_state,
            prompt=prompt
        )

        masks = output.get("masks", [])
        boxes = output.get("boxes", [])
        scores = output.get("scores", [])

        # Convert to numpy/lists if needed
        processed_masks = []
        processed_boxes = []
        processed_scores = []

        for i in range(len(masks)):
            mask = masks[i]
            if isinstance(mask, torch.Tensor):
                mask = mask.cpu().numpy()
            # SAM3 returns masks with shape [1, H, W], squeeze to [H, W]
            if mask.ndim == 3 and mask.shape[0] == 1:
                mask = mask.squeeze(0)
            processed_masks.append(mask.astype(np.uint8))

            box = boxes[i] if i < len(boxes) else None
            if box is not None:
                if isinstance(box, torch.Tensor):
                    box = box.cpu().tolist()
                processed_boxes.append(box)

            score = scores[i] if i < len(scores) else 1.0
            if isinstance(score, torch.Tensor):
                score = score.item()
            processed_scores.append(float(score))

        return processed_masks, processed_boxes, processed_scores

    def segment_fabric(
        self,
        image: Image.Image
    ) -> Tuple[List[np.ndarray], List[List[float]], List[float]]:
        """
        Segment fabric from image using multiple specialized prompts.

        Tries multiple fabric-detection prompts in order until detection succeeds.

        Args:
            image: PIL Image

        Returns:
            Tuple of (masks, boxes, scores)
        """
        prompts_to_try = FABRIC_PROMPTS if self.config.use_multi_prompt else [DEFAULT_FABRIC_PROMPT]

        for prompt in prompts_to_try:
            print(f"  Trying prompt: '{prompt}'")
            masks, boxes, scores = self.segment_image(image, prompt)

            # Filter by threshold
            valid_masks = []
            valid_boxes = []
            valid_scores = []

            for mask, box, score in zip(masks, boxes, scores):
                if score >= self.config.threshold:
                    valid_masks.append(mask)
                    valid_boxes.append(box)
                    valid_scores.append(score)

            if valid_masks:
                print(f"  Found {len(valid_masks)} fabric regions with prompt: '{prompt}'")
                return valid_masks, valid_boxes, valid_scores

        print("  No fabric detected with any prompt")
        return [], [], []

    def get_rectangular_bbox(
        self,
        mask: np.ndarray,
        image_shape: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        """
        Get axis-aligned rectangular bounding box from mask.

        This ensures the output crop is always rectangular/square.

        Args:
            mask: Binary mask
            image_shape: (height, width) of image

        Returns:
            Tuple of (x1, y1, x2, y2) for rectangular bounding box
        """
        h, w = image_shape

        # Find mask bounds
        y_coords, x_coords = np.where(mask > 0)
        if len(x_coords) == 0 or len(y_coords) == 0:
            return 0, 0, w, h

        x1, x2 = int(x_coords.min()), int(x_coords.max())
        y1, y2 = int(y_coords.min()), int(y_coords.max())

        # Ensure minimum size
        min_size = 50
        if x2 - x1 < min_size:
            center_x = (x1 + x2) // 2
            x1 = max(0, center_x - min_size // 2)
            x2 = min(w, center_x + min_size // 2)

        if y2 - y1 < min_size:
            center_y = (y1 + y2) // 2
            y1 = max(0, center_y - min_size // 2)
            y2 = min(h, center_y + min_size // 2)

        return x1, y1, x2, y2

    def get_precise_inner_bbox(
        self,
        mask: np.ndarray,
        image_shape: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        """
        Get the largest axis-aligned rectangle that fits INSIDE the fabric mask.

        This ensures the crop rectangle is entirely within the detected fabric area,
        avoiding any background pixels at the edges.

        Uses contour analysis and iterative erosion to find the optimal inner rectangle.

        Args:
            mask: Binary mask of detected fabric
            image_shape: (height, width) of image

        Returns:
            Tuple of (x1, y1, x2, y2) for inner bounding box
        """
        # Ensure mask is binary uint8
        binary_mask = (mask > 0).astype(np.uint8) * 255

        # Find contours
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            # Fallback to standard bbox
            return self.get_rectangular_bbox(mask, image_shape)

        # Get the largest contour (main fabric region)
        largest_contour = max(contours, key=cv2.contourArea)

        # Note: minAreaRect gives rotated rectangle, but we need axis-aligned
        # So we use distance transform approach instead
        _ = cv2.minAreaRect(largest_contour)  # Keep for potential future use

        # Method 2: Find largest inscribed rectangle using distance transform
        # This is more accurate for finding rectangle fully inside the mask
        dist_transform = cv2.distanceTransform(binary_mask, cv2.DIST_L2, 5)

        # Find the point with maximum distance (center of largest inscribed circle)
        _, max_dist, _, max_loc = cv2.minMaxLoc(dist_transform)

        if max_dist < 10:  # Mask too thin, fallback
            return self.get_rectangular_bbox(mask, image_shape)

        # Grow rectangle from center point until it hits mask boundary
        cx, cy = max_loc
        best_rect = self._find_largest_inscribed_rect(binary_mask, cx, cy, dist_transform)

        if best_rect is None:
            # Fallback to eroded bounding box
            return self._get_eroded_bbox(mask, image_shape)

        return best_rect

    def _find_largest_inscribed_rect(
        self,
        binary_mask: np.ndarray,
        cx: int,
        cy: int,
        dist_transform: np.ndarray
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Find the largest axis-aligned rectangle inscribed within the mask.

        Uses a binary search approach expanding from the center point.

        Args:
            binary_mask: Binary mask (255 for fabric, 0 for background)
            cx, cy: Center point (point with max distance to boundary)
            dist_transform: Distance transform of the mask

        Returns:
            (x1, y1, x2, y2) or None if failed
        """
        h, w = binary_mask.shape

        # Start with a small rectangle at center and expand
        # Use distance transform value as initial radius estimate
        initial_radius = int(dist_transform[cy, cx])

        best_area = 0
        best_rect = None

        # Try different aspect ratios and sizes
        for aspect in [1.0, 0.75, 1.33, 0.5, 2.0]:
            for scale in np.linspace(0.3, 1.5, 20):
                half_w = int(initial_radius * scale * np.sqrt(aspect))
                half_h = int(initial_radius * scale / np.sqrt(aspect))

                x1 = max(0, cx - half_w)
                y1 = max(0, cy - half_h)
                x2 = min(w, cx + half_w)
                y2 = min(h, cy + half_h)

                # Check if rectangle is fully inside mask
                if x2 <= x1 or y2 <= y1:
                    continue

                rect_region = binary_mask[y1:y2, x1:x2]
                total_pixels = rect_region.size
                fabric_pixels = np.sum(rect_region > 0)

                # Rectangle must be entirely inside fabric
                coverage = fabric_pixels / total_pixels if total_pixels > 0 else 0

                if coverage >= 0.99:  # Allow tiny tolerance for anti-aliasing
                    area = (x2 - x1) * (y2 - y1)
                    if area > best_area:
                        best_area = area
                        best_rect = (x1, y1, x2, y2)

        # If no perfect fit found, use high-coverage rectangle
        if best_rect is None:
            # Try to find rectangle with at least min_coverage_ratio
            for aspect in [1.0, 0.75, 1.33]:
                for scale in np.linspace(0.2, 1.0, 15):
                    half_w = int(initial_radius * scale * np.sqrt(aspect))
                    half_h = int(initial_radius * scale / np.sqrt(aspect))

                    x1 = max(0, cx - half_w)
                    y1 = max(0, cy - half_h)
                    x2 = min(w, cx + half_w)
                    y2 = min(h, cy + half_h)

                    if x2 <= x1 or y2 <= y1:
                        continue

                    rect_region = binary_mask[y1:y2, x1:x2]
                    total_pixels = rect_region.size
                    fabric_pixels = np.sum(rect_region > 0)
                    coverage = fabric_pixels / total_pixels if total_pixels > 0 else 0

                    if coverage >= self.config.min_coverage_ratio:
                        area = (x2 - x1) * (y2 - y1)
                        if area > best_area:
                            best_area = area
                            best_rect = (x1, y1, x2, y2)

        return best_rect

    def _get_eroded_bbox(
        self,
        mask: np.ndarray,
        image_shape: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        """
        Get bounding box from eroded mask for tighter fit inside fabric.

        Args:
            mask: Binary mask
            image_shape: (height, width) of image

        Returns:
            Tuple of (x1, y1, x2, y2) for eroded bounding box
        """
        h, w = image_shape

        # Erode mask to shrink boundaries inward
        binary_mask = (mask > 0).astype(np.uint8) * 255
        kernel_size = max(3, self.config.inward_margin)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        eroded = cv2.erode(binary_mask, kernel, iterations=1)

        # Find bounds of eroded mask
        y_coords, x_coords = np.where(eroded > 0)

        if len(x_coords) == 0 or len(y_coords) == 0:
            # Erosion removed everything, use original with smaller margin
            return self.get_rectangular_bbox(mask, image_shape)

        x1, x2 = int(x_coords.min()), int(x_coords.max())
        y1, y2 = int(y_coords.min()), int(y_coords.max())

        # Ensure minimum size
        min_size = 50
        if x2 - x1 < min_size:
            center_x = (x1 + x2) // 2
            x1 = max(0, center_x - min_size // 2)
            x2 = min(w, center_x + min_size // 2)

        if y2 - y1 < min_size:
            center_y = (y1 + y2) // 2
            y1 = max(0, center_y - min_size // 2)
            y2 = min(h, center_y + min_size // 2)

        return x1, y1, x2, y2

    def get_contour_fitted_bbox(
        self,
        mask: np.ndarray,
        image_shape: Tuple[int, int]
    ) -> Tuple[int, int, int, int]:
        """
        Get axis-aligned bounding box fitted to the main fabric contour.

        This provides a tighter fit than simple min/max coordinates by:
        1. Finding the largest contour
        2. Approximating the contour polygon
        3. Computing axis-aligned bbox from the approximation

        Args:
            mask: Binary mask
            image_shape: (height, width) of image

        Returns:
            Tuple of (x1, y1, x2, y2) for contour-fitted bounding box
        """
        # Ensure mask is binary uint8
        binary_mask = (mask > 0).astype(np.uint8) * 255

        # Find contours
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return self.get_rectangular_bbox(mask, image_shape)

        # Get the largest contour
        largest_contour = max(contours, key=cv2.contourArea)

        # Approximate contour with polygon
        epsilon = 0.02 * cv2.arcLength(largest_contour, True)
        approx = cv2.approxPolyDP(largest_contour, epsilon, True)

        # Get bounding rectangle from approximated contour
        x, y, rect_w, rect_h = cv2.boundingRect(approx)

        x1, y1 = x, y
        x2, y2 = x + rect_w, y + rect_h

        # Shrink inward by margin if precise cropping enabled
        if self.config.precise_crop:
            margin = self.config.inward_margin
            x1 = min(x1 + margin, x2 - 10)
            y1 = min(y1 + margin, y2 - 10)
            x2 = max(x2 - margin, x1 + 10)
            y2 = max(y2 - margin, y1 + 10)

        return x1, y1, x2, y2

    def make_square_crop(
        self,
        bbox: Tuple[int, int, int, int],
        image_shape: Tuple[int, int],
        padding: int = 0
    ) -> Tuple[int, int, int, int]:
        """
        Optionally make bounding box square while keeping it within image bounds.

        Args:
            bbox: (x1, y1, x2, y2) bounding box
            image_shape: (height, width) of image
            padding: Additional padding to add

        Returns:
            Adjusted (x1, y1, x2, y2) bounding box
        """
        h, w = image_shape
        x1, y1, x2, y2 = bbox

        # Add padding
        x1 = max(0, x1 - padding)
        y1 = max(0, y1 - padding)
        x2 = min(w, x2 + padding)
        y2 = min(h, y2 + padding)

        # Check aspect ratio
        crop_w = x2 - x1
        crop_h = y2 - y1

        if crop_w > 0 and crop_h > 0:
            aspect = crop_w / crop_h

            # If aspect ratio is extreme, adjust to make more square-ish
            if aspect < self.config.min_aspect_ratio or aspect > self.config.max_aspect_ratio:
                # Make it closer to square
                target_size = max(crop_w, crop_h)
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2

                x1 = max(0, center_x - target_size // 2)
                x2 = min(w, center_x + target_size // 2)
                y1 = max(0, center_y - target_size // 2)
                y2 = min(h, center_y + target_size // 2)

        return x1, y1, x2, y2

    def compute_iou(self, mask1: np.ndarray, mask2: np.ndarray) -> float:
        """Compute Intersection over Union between two masks."""
        inter = np.logical_and(mask1, mask2).sum()
        union = np.logical_or(mask1, mask2).sum()
        return inter / union if union != 0 else 0

    def filter_objects(
        self,
        masks: List[np.ndarray],
        boxes: List[List[float]],
        scores: List[float],
        image_size: Tuple[int, int]
    ) -> Tuple[List[np.ndarray], List[List[float]], List[float]]:
        """
        Filter detected objects based on area, dimensions, and overlap.

        Removes:
        - Objects with area below min_area_ratio of image
        - Objects with bounding box smaller than min_crop_width/height
        - Small connected components within masks (cleanup)
        - Duplicate overlapping detections

        Args:
            masks: List of binary masks
            boxes: List of bounding boxes [x1, y1, x2, y2]
            scores: List of confidence scores
            image_size: (width, height) of image

        Returns:
            Filtered (masks, boxes, scores)
        """
        if not masks:
            return [], [], []

        image_area = image_size[0] * image_size[1]
        min_area = image_area * self.config.min_area_ratio

        # Create list of (mask, box, score, area) tuples
        detections = []
        for mask, box, score in zip(masks, boxes, scores):
            # Apply mask cleanup to remove small islands
            cleaned_mask = self.cleanup_mask(mask)

            # Check if mask still has content after cleanup
            area = np.sum(cleaned_mask > 0)
            if area < min_area:
                continue

            # Calculate bounding box dimensions from cleaned mask
            y_coords, x_coords = np.where(cleaned_mask > 0)
            if len(x_coords) == 0 or len(y_coords) == 0:
                continue

            bbox_width = int(x_coords.max()) - int(x_coords.min())
            bbox_height = int(y_coords.max()) - int(y_coords.min())

            # Filter by minimum crop dimensions
            if bbox_width < self.config.min_crop_width:
                print(f"    Skipping small region: width {bbox_width}px < {self.config.min_crop_width}px")
                continue
            if bbox_height < self.config.min_crop_height:
                print(f"    Skipping small region: height {bbox_height}px < {self.config.min_crop_height}px")
                continue

            detections.append({
                'mask': cleaned_mask,
                'box': box,
                'score': score,
                'area': area,
                'bbox_width': bbox_width,
                'bbox_height': bbox_height
            })

        # Sort by area descending (largest first)
        detections = sorted(detections, key=lambda x: x['area'], reverse=True)

        # Filter duplicates using IOU
        filtered = []
        for det in detections:
            if len(filtered) >= self.config.max_objects:
                break

            is_duplicate = False
            for kept in filtered:
                if self.compute_iou(det['mask'], kept['mask']) > self.config.max_overlap_iou:
                    is_duplicate = True
                    break

            if not is_duplicate:
                filtered.append(det)

        # Unpack results
        filtered_masks = [d['mask'] for d in filtered]
        filtered_boxes = [d['box'] for d in filtered]
        filtered_scores = [d['score'] for d in filtered]

        return filtered_masks, filtered_boxes, filtered_scores

    def crop_object(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        box: List[float],
        padding: int
    ) -> Tuple[np.ndarray, np.ndarray, Tuple[int, int, int, int]]:
        """
        Crop fabric from image using rectangular bounding box.

        Ensures output is always a clean rectangular/square crop.
        When precise_crop is enabled, the rectangle stays WITHIN the fabric area.

        Args:
            image: RGB numpy array
            mask: Binary mask
            box: Bounding box [x1, y1, x2, y2]
            padding: Pixels to add around crop

        Returns:
            Tuple of (cropped_image, cropped_mask, bbox)
        """
        h, w = image.shape[:2]

        # Choose bounding box method based on config
        if self.config.precise_crop:
            # PRECISE CROPPING: Rectangle stays WITHIN fabric boundary
            if self.config.use_contour_fitting:
                # Try inscribed rectangle first (largest rect fully inside mask)
                bbox = self.get_precise_inner_bbox(mask, (h, w))
            else:
                # Use contour-fitted bbox with inward margin
                bbox = self.get_contour_fitted_bbox(mask, (h, w))

            # For precise cropping, DON'T add padding (it would extend outside fabric)
            # The inward_margin in config already provides safety buffer
            x1, y1, x2, y2 = bbox

            # Verify the crop is still mostly within fabric
            rect_mask = mask[y1:y2, x1:x2]
            if rect_mask.size > 0:
                coverage = np.sum(rect_mask > 0) / rect_mask.size
                if coverage < self.config.min_coverage_ratio:
                    # Fallback to eroded bbox if coverage too low
                    print(f"    Warning: Low coverage ({coverage:.2%}), using eroded bbox")
                    bbox = self._get_eroded_bbox(mask, (h, w))
                    x1, y1, x2, y2 = bbox

        else:
            # STANDARD CROPPING: Rectangle can extend beyond fabric (with padding)
            if self.config.force_rectangular:
                bbox = self.get_rectangular_bbox(mask, (h, w))
            elif box:
                bbox = tuple(int(v) for v in box)
            else:
                bbox = self.get_rectangular_bbox(mask, (h, w))

            # Apply padding and aspect ratio adjustments (may extend beyond fabric)
            x1, y1, x2, y2 = self.make_square_crop(bbox, (h, w), padding)

        # Ensure bounds are valid
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        # Crop image and mask
        cropped_image = image[y1:y2, x1:x2]
        cropped_mask = mask[y1:y2, x1:x2]

        # Apply perspective transform to straighten the fabric
        if self.config.perspective_correct:
            cropped_image, cropped_mask = self.apply_perspective_transform(
                cropped_image, cropped_mask
            )

        return cropped_image, cropped_mask, (x1, y1, x2, y2)

    def process_image(
        self,
        input_path: str,
        output_dir: str,
        prompt: Optional[str] = None
    ) -> CropResult:
        """
        Process a single image to detect and crop fabric.

        Args:
            input_path: Source image path
            output_dir: Output directory for crops
            prompt: Optional custom prompt (uses fabric prompts by default)

        Returns:
            CropResult with processing results
        """
        try:
            print(f"Processing: {input_path}")

            # Read image
            image_pil = self.read_image(input_path)
            image_np = np.array(image_pil)

            # Clear GPU cache
            torch.cuda.empty_cache()

            # Segment fabric using specialized prompts
            if prompt:
                # Use custom prompt if provided
                masks, boxes, scores = self.segment_image(image_pil, prompt)
            else:
                # Use fabric-specific multi-prompt detection
                masks, boxes, scores = self.segment_fabric(image_pil)

            # Filter objects
            masks, boxes, scores = self.filter_objects(
                masks, boxes, scores,
                (image_pil.width, image_pil.height)
            )

            if not masks:
                return CropResult(
                    input_path=input_path,
                    success=True,
                    message="No fabric detected in image",
                    num_objects=0
                )

            # Create output directory
            base_name = Path(input_path).stem
            save_dir = os.path.join(output_dir, base_name)
            os.makedirs(save_dir, exist_ok=True)

            output_paths = []
            prompt_used = prompt if prompt else "fabric (auto-detected)"
            metadata = {
                "source": input_path,
                "prompt": prompt_used,
                "image_size": [image_pil.width, image_pil.height],
                "crop_type": "rectangular",
                "objects": []
            }

            # Process each detected fabric region
            for obj_id, (mask, box, score) in enumerate(zip(masks, boxes, scores)):
                # Crop fabric with rectangular output
                cropped_image, cropped_mask, bbox = self.crop_object(
                    image_np, mask, box, self.config.padding
                )

                # Calculate crop dimensions
                crop_h, crop_w = cropped_image.shape[:2]
                print(f"  Fabric {obj_id}: {crop_w}x{crop_h}px, score={score:.3f}")

                # Save cropped image
                crop_filename = f"fabric_{obj_id}.{self.config.output_format}"
                crop_path = os.path.join(save_dir, crop_filename)

                # Convert RGB to BGR for OpenCV
                cropped_bgr = cv2.cvtColor(cropped_image, cv2.COLOR_RGB2BGR)
                cv2.imwrite(crop_path, cropped_bgr)
                output_paths.append(crop_path)

                # Save mask if enabled
                mask_path = None
                if self.config.save_masks:
                    mask_filename = f"fabric_{obj_id}_mask.png"
                    mask_path = os.path.join(save_dir, mask_filename)
                    cv2.imwrite(mask_path, (cropped_mask * 255).astype(np.uint8))

                # Save overlay if enabled
                overlay_path = None
                if self.config.save_overlays:
                    overlay_filename = f"fabric_{obj_id}_overlay.png"
                    overlay_path = os.path.join(save_dir, overlay_filename)

                    # Create overlay with mask highlight
                    overlay = image_np.copy()
                    # Draw rectangle around detected fabric
                    cv2.rectangle(overlay, (bbox[0], bbox[1]), (bbox[2], bbox[3]),
                                  (0, 255, 0), 3)
                    # Also highlight the mask area
                    mask_overlay = overlay.copy()
                    mask_overlay[mask > 0] = [0, 200, 0]
                    overlay = cv2.addWeighted(overlay, 0.7, mask_overlay, 0.3, 0)
                    overlay_bgr = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)
                    cv2.imwrite(overlay_path, overlay_bgr)

                # Add object metadata
                metadata["objects"].append({
                    "id": obj_id,
                    "bbox": list(bbox),
                    "crop_size": [crop_w, crop_h],
                    "score": float(score),
                    "area": int(np.sum(mask > 0)),
                    "crop_path": crop_path,
                    "mask_path": mask_path,
                    "overlay_path": overlay_path
                })

            # Save metadata if enabled
            if self.config.save_metadata:
                metadata_path = os.path.join(save_dir, f"{base_name}_metadata.json")
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=4)

            return CropResult(
                input_path=input_path,
                output_paths=output_paths,
                success=True,
                message=f"Detected {len(masks)} fabric regions",
                num_objects=len(masks),
                metadata=metadata
            )

        except FileNotFoundError as e:
            return CropResult(
                input_path=input_path,
                success=False,
                message=str(e)
            )
        except ValueError as e:
            return CropResult(
                input_path=input_path,
                success=False,
                message=str(e)
            )
        except Exception as e:
            return CropResult(
                input_path=input_path,
                success=False,
                message=f"Error: {e}"
            )

    def process_directory(
        self,
        input_dir: str,
        output_dir: str,
        prompt: Optional[str] = None
    ) -> List[CropResult]:
        """
        Process all images in directory to detect and crop fabric.

        Args:
            input_dir: Source directory
            output_dir: Destination directory
            prompt: Optional custom prompt (uses fabric prompts by default)

        Returns:
            List of CropResult for each image
        """
        if not os.path.isdir(input_dir):
            return [CropResult(
                input_path=input_dir,
                success=False,
                message=f"Directory not found: {input_dir}"
            )]

        os.makedirs(output_dir, exist_ok=True)

        # Get list of image files
        image_files = []
        for filename in sorted(os.listdir(input_dir)):
            ext = os.path.splitext(filename)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                image_files.append(filename)

        if not image_files:
            print(f"No supported image files found in: {input_dir}")
            return []

        print(f"Found {len(image_files)} images to process")
        print(f"Using fabric detection prompts: {FABRIC_PROMPTS[0][:50]}...")

        results = []
        for filename in tqdm(image_files, desc="Processing fabric images"):
            input_path = os.path.join(input_dir, filename)
            result = self.process_image(input_path, output_dir, prompt)
            results.append(result)

            # Clear GPU cache periodically
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

        return results


def main() -> int:
    """CLI entry point for fabric auto-crop."""
    parser = argparse.ArgumentParser(
        description="Auto-crop fabric images using SAM3 - Optimized for fabric/textile detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Fabric Auto-Crop Tool v%(prog)s
    
This tool automatically detects and crops fabric/textile samples from images.
Just provide a file path or directory - no prompt needed!

Examples:
  # Single image - just provide the path
  %(prog)s /path/to/fabric_image.jpg

  # Batch processing - provide a directory
  %(prog)s /path/to/images/

  # With custom output directory
  %(prog)s /path/to/images/ -o /path/to/output/

  # With custom prompt (optional, overrides fabric detection)
  %(prog)s /path/to/image.jpg -p "custom object"

  # Verbose mode
  %(prog)s /path/to/images/ -v

Default prompts used for fabric detection:
  - "fabric sample, textile material, cloth piece, fabric swatch"
  - "rectangular fabric, square cloth, textile piece, fabric material"
  - "cloth material, woven fabric, textile sample, fabric sheet"
        """
    )

    # Positional argument for simple usage
    parser.add_argument("path", nargs="?", help="Input file or directory path")

    # Alternative input specification
    parser.add_argument("--input", "-i", help="Input file or directory path (alternative to positional)")
    parser.add_argument("--output", "-o", default=None, help="Output directory (default: ./fabric_crops)")
    parser.add_argument("--prompt", "-p", default=None,
                        help="Custom text prompt (optional - uses fabric detection by default)")
    parser.add_argument("--mode", "-m", choices=["single", "batch"], default=None,
                        help="Processing mode (default: auto-detect from input)")

    # Detection settings - optimized defaults for fabric
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="Detection threshold (default: 0.3, lower = more sensitive)")
    parser.add_argument("--max-objects", type=int, default=10,
                        help="Max fabric regions per image (default: 10)")
    parser.add_argument("--min-area", type=float, default=0.01,
                        help="Min fabric area ratio (default: 0.01)")
    parser.add_argument("--max-overlap", type=float, default=0.5,
                        help="Max IOU for duplicate removal (default: 0.5)")

    # Crop settings
    parser.add_argument("--padding", type=int, default=30,
                        help="Padding around fabric crops in pixels (default: 20)")
    parser.add_argument("--format", choices=["png", "jpg", "tiff"], default="png",
                        help="Output format (default: png)")
    parser.add_argument("--no-multi-prompt", action="store_true",
                        help="Don't try multiple prompts for fabric detection")
    parser.add_argument("--no-rectangular", action="store_true",
                        help="Don't force rectangular output crops")
    parser.add_argument("--save-masks", action="store_true", help="Save mask images (disabled by default)")
    parser.add_argument("--no-overlays", action="store_true", help="Don't save overlay images")
    parser.add_argument("--no-metadata", action="store_true", help="Don't save metadata JSON")

    # Precise cropping settings
    parser.add_argument("--precise", action="store_true", default=True,
                        help="Enable precise cropping (rectangle stays WITHIN fabric) - enabled by default")
    parser.add_argument("--no-precise", action="store_true",
                        help="Disable precise cropping (allow rectangle to extend beyond fabric with padding)")
    parser.add_argument("--inward-margin", type=int, default=5,
                        help="Inward safety margin in pixels for precise cropping (default: 5)")
    parser.add_argument("--min-coverage", type=float, default=0.85,
                        help="Minimum fabric coverage ratio for precise crops (default: 0.85)")
    parser.add_argument("--no-contour-fitting", action="store_true",
                        help="Disable contour fitting, use simpler eroded bbox for precise cropping")

    # Small region filtering settings
    parser.add_argument("--min-crop-width", type=int, default=100,
                        help="Minimum crop width in pixels (default: 100)")
    parser.add_argument("--min-crop-height", type=int, default=100,
                        help="Minimum crop height in pixels (default: 100)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Disable mask cleanup (don't remove small islands)")
    parser.add_argument("--min-component-area", type=int, default=500,
                        help="Minimum connected component area in pixels (default: 500)")

    # Perspective correction settings
    parser.add_argument("--no-perspective", action="store_true",
                        help="Disable perspective correction (don't straighten angled fabric)")
    parser.add_argument("--perspective-threshold", type=float, default=0.95,
                        help="Apply perspective transform only if fabric coverage below this ratio (default: 0.95)")

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    # Get input path from either positional or --input argument
    input_path = args.path or args.input
    if not input_path:
        parser.print_help()
        print("\nError: Please provide an input file or directory path", file=sys.stderr)
        return 1

    # Validate input
    if not os.path.exists(input_path):
        print(f"Error: Input path does not exist: {input_path}", file=sys.stderr)
        return 1

    # Check SAM3 availability
    if not HAS_SAM3:
        print("Error: SAM3 not available. Install from: https://github.com/facebookresearch/sam3", file=sys.stderr)
        return 1

    # Determine precise cropping setting (--no-precise overrides --precise)
    precise_crop_enabled = args.precise and not args.no_precise

    # Create config optimized for fabric detection
    config = SAM3Config(
        threshold=args.threshold,
        max_objects=args.max_objects,
        min_area_ratio=args.min_area,
        max_overlap_iou=args.max_overlap,
        padding=args.padding,
        output_format=args.format,
        save_masks=args.save_masks,
        save_overlays=not args.no_overlays,
        save_metadata=not args.no_metadata,
        use_multi_prompt=not args.no_multi_prompt,
        force_rectangular=not args.no_rectangular,
        # Precise cropping settings
        precise_crop=precise_crop_enabled,
        inward_margin=args.inward_margin,
        use_contour_fitting=not args.no_contour_fitting,
        min_coverage_ratio=args.min_coverage,
        # Small region filtering settings
        min_crop_width=args.min_crop_width,
        min_crop_height=args.min_crop_height,
        cleanup_mask=not args.no_cleanup,
        min_component_area=args.min_component_area,
        # Perspective correction settings
        perspective_correct=not args.no_perspective,
        perspective_threshold=args.perspective_threshold,
    )

    # Set output directory
    if args.output:
        output_dir = args.output
    else:
        if os.path.isdir(input_path):
            input_dir = input_path
        else:
            input_dir = os.path.dirname(input_path)

        # fallback: if image is in current directory
        if input_dir == "":
            input_dir = "."

        output_dir = os.path.join(input_dir, "crops")
        os.makedirs(output_dir, exist_ok=True)
        
    # Determine mode
    is_dir = os.path.isdir(input_path)
    if args.mode is None:
        mode = "batch" if is_dir else "single"
    else:
        mode = args.mode

    # Print startup info
    print(f"=" * 60)
    print(f"Fabric Auto-Crop v{__version__}")
    print(f"=" * 60)
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    print(f"Mode: {mode}")
    if args.prompt:
        print(f"Prompt: {args.prompt} (custom)")
    else:
        print(f"Prompt: Fabric detection (automatic)")
    print(f"Device: {config.device}")
    print(f"Threshold: {args.threshold}")
    print(f"Rectangular crops: {config.force_rectangular}")
    print(f"Multi-prompt: {config.use_multi_prompt}")
    print(f"Precise cropping: {config.precise_crop} (rectangle stays WITHIN fabric)")
    if config.precise_crop:
        print(f"  Inward margin: {config.inward_margin}px")
        print(f"  Min coverage: {config.min_coverage_ratio:.0%}")
        print(f"  Contour fitting: {config.use_contour_fitting}")
    print(f"Small region filtering:")
    print(f"  Min crop size: {config.min_crop_width}x{config.min_crop_height}px")
    print(f"  Mask cleanup: {config.cleanup_mask}")
    if config.cleanup_mask:
        print(f"  Min component area: {config.min_component_area}px")
    print(f"Perspective correction: {config.perspective_correct}")
    if config.perspective_correct:
        print(f"  Threshold: {config.perspective_threshold:.0%} (apply if fabric coverage below this)")
    print()

    # Initialize cropper
    try:
        cropper = SAM3AutoCropper(config)
    except Exception as e:
        print(f"Error loading SAM3 model: {e}", file=sys.stderr)
        return 1

    # Process
    if mode == "single":
        if is_dir:
            print("Error: --mode single requires a file, not directory", file=sys.stderr)
            return 2

        results = [cropper.process_image(input_path, output_dir, args.prompt)]
    else:
        if not is_dir:
            print("Error: --mode batch requires a directory", file=sys.stderr)
            return 2

        results = cropper.process_directory(input_path, output_dir, args.prompt)

    # Print results
    print()
    print(f"=" * 60)
    print("Results")
    print(f"=" * 60)

    success_count = 0
    fail_count = 0
    total_fabrics = 0

    for result in results:
        if result.success:
            success_count += 1
            total_fabrics += result.num_objects
            if args.verbose:
                print(f"✓ {result.input_path}")
                print(f"  Fabric regions: {result.num_objects}")
                if result.output_paths:
                    for path in result.output_paths:
                        print(f"    → {path}")
                print()
            else:
                status = "✓" if result.num_objects > 0 else "○"
                print(f"{status} {os.path.basename(result.input_path)}: {result.num_objects} fabric(s)")
        else:
            fail_count += 1
            print(f"✗ {os.path.basename(result.input_path)}: {result.message}")

    # Summary
    print()
    print(f"=" * 60)
    print("Summary")
    print(f"=" * 60)
    print(f"Total images processed: {len(results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total fabric regions detected: {total_fabrics}")
    print(f"Output directory: {output_dir}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
