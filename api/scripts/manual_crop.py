import numpy as np
import cv2
import os
from pathlib import Path

# Configuration
INPUT_FOLDER = "/srv/ashish/backend/media/MAJESTIC"
CROP_COORDINATES =((2893, 2448), (4232, 3926))
SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}
# Filter pattern - only process files containing this string (case-insensitive)
FILENAME_FILTER = "segment"


def get_cropped_image(img, coordinates):
    """Crop image using the given coordinates."""
    start_point, end_point = coordinates
    x1, y1 = start_point
    x2, y2 = end_point
    return img[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)]


def process_folder(input_folder, coordinates):
    """Process all images in a folder and save cropped versions to a subfolder."""
    input_path = Path(input_folder)
    output_path = input_path / "cropped"

    # Create output folder if it doesn't exist
    output_path.mkdir(exist_ok=True)

    # Get all image files (filtered by FILENAME_FILTER if set)
    image_files = [f for f in input_path.iterdir()
                   if f.is_file()
                   and f.suffix.lower() in SUPPORTED_EXTENSIONS
                   and (not FILENAME_FILTER or FILENAME_FILTER.lower() in f.name.lower())]

    if not image_files:
        print(f"No images found in {input_folder}")
        return

    print(f"Found {len(image_files)} images to process")

    processed = 0
    for image_file in image_files:
        try:
            # Read image
            img = cv2.imread(str(image_file))
            if img is None:
                print(f"  Skipping {image_file.name}: Could not read image")
                continue

            # Crop image
            cropped = get_cropped_image(img, coordinates)

            # Save cropped image
            output_file = output_path / image_file.name
            cv2.imwrite(str(output_file), cropped)

            processed += 1
            print(f"  Processed: {image_file.name}")

        except Exception as e:
            print(f"  Error processing {image_file.name}: {e}")

    print(f"\nDone! Processed {processed}/{len(image_files)} images")
    print(f"Cropped images saved to: {output_path}")


if __name__ == "__main__":
    process_folder(INPUT_FOLDER, CROP_COORDINATES)