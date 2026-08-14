import glob
import numpy as np
import os
import colour
import matplotlib.pyplot as plt
import cv2
import sys
from colour.characterisation import ColourChecker
from colour_checker_detection import detect_colour_checkers_segmentation

checker_path='/srv/ashish/backend/media/e500g60s50/color'
image_path='/srv/ashish/backend/media/e500g60s50/color'
COLOUR_CHECKER_PATHS = glob.glob(
    os.path.join(checker_path, '*segment_0_color*')) 

IMAGE_PATHS=glob.glob(
    os.path.join(image_path, '*segment_0_color*'))

COLOUR_CHECKER_IMAGES = [colour.io.read_image(path)
    for path in COLOUR_CHECKER_PATHS]

IMAGES= [colour.io.read_image(path)
    for path in IMAGE_PATHS]

if not IMAGE_PATHS or not COLOUR_CHECKER_IMAGES:
    print(f'Images not loaded. IMAGE_PATHS: {IMAGE_PATHS}, COLOUR_CHECKER_PATHS: {COLOUR_CHECKER_PATHS}')
    sys.exit(1)

SWATCHES = []
for image in COLOUR_CHECKER_IMAGES:
    for colour_checker_data in detect_colour_checkers_segmentation(
        image, additional_data=True):

        if colour_checker_data is None:
            print('No colour checker detected!')
            continue
        swatch_colours, swatch_masks, colour_checker_image ,_= (
            colour_checker_data.values)
        masks_i = np.zeros(colour_checker_image.shape)
        for i, mask in enumerate(swatch_masks):
            masks_i[mask[0]:mask[1], mask[2]:mask[3], ...] = 1

        # colour.plotting.plot_image(
        #     np.clip(colour_checker_image+ masks_i * 0.25, 0, 1));
    SWATCHES.append(swatch_colours)

def flip_colour_checker(colour_checker, flip_axis='horizontal'):
    
    swatch_names = list(colour_checker.data.keys())
    swatch_values = list(colour_checker.data.values())
    rows = colour_checker.rows
    columns = colour_checker.columns  

    # Reshape into grids
    swatch_array = np.array(swatch_values).reshape(rows, columns, 3)
    name_array = np.array(swatch_names).reshape(rows, columns)

    # Flip both names and values
    if flip_axis == 'horizontal':
        name_array[0]= name_array[0][::-1]
        name_array[2]= name_array[2][::-1]
        swatch_array[0]= swatch_array[0][::-1]
        swatch_array[2]= swatch_array[2][::-1]

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

D65 = colour.CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer']['D65']
REFERENCE_COLOUR_CHECKER = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014']
REFERENCE_COLOUR_CHECKER = flip_colour_checker(REFERENCE_COLOUR_CHECKER, flip_axis='horizontal')

colour_checker_rows = REFERENCE_COLOUR_CHECKER.rows
colour_checker_columns = REFERENCE_COLOUR_CHECKER.columns

# NOTE: The reference swatches values as produced by the "colour.XYZ_to_RGB"
# definition are linear by default.
# See https://github.com/colour-science/colour-checker-detection/discussions/59
# for more information.
REFERENCE_SWATCHES = colour.XYZ_to_RGB(
        colour.xyY_to_XYZ(list(REFERENCE_COLOUR_CHECKER.data.values())),
        'sRGB', REFERENCE_COLOUR_CHECKER.illuminant)

for i, swatches in enumerate(SWATCHES):
    swatches_xyY = colour.XYZ_to_xyY(colour.RGB_to_XYZ(
        swatches, 'sRGB', D65))

    colour_checker = colour.characterisation.ColourChecker(
        os.path.basename(COLOUR_CHECKER_PATHS[i]),
        dict(zip(REFERENCE_COLOUR_CHECKER.data.keys(), swatches_xyY)),
        D65, colour_checker_rows, colour_checker_columns)
    
    # colour.plotting.plot_multi_colour_checkers(
    #     [REFERENCE_COLOUR_CHECKER, colour_checker])
    
    swatches_f = colour.colour_correction(swatches, swatches, REFERENCE_SWATCHES)
    swatches_f_xyY = colour.XYZ_to_xyY(colour.RGB_to_XYZ(
        swatches_f, 'sRGB', D65))
    colour_checker = colour.characterisation.ColourChecker(
        '{0} - CC'.format(os.path.basename(COLOUR_CHECKER_PATHS[i])),
        dict(zip(REFERENCE_COLOUR_CHECKER.data.keys(), swatches_f_xyY)),
        D65, colour_checker_rows, colour_checker_columns)
    
    
    # colour.plotting.plot_multi_colour_checkers(
    #     [ REFERENCE_COLOUR_CHECKER,colour_checker])

    corrected_image = colour.colour_correction(
        IMAGES[i], swatches, REFERENCE_SWATCHES)
    corrected_image_16bit = np.clip(colour.cctf_encoding(corrected_image), 0, 1)
    corrected_image_16bit = (corrected_image_16bit * 65535).astype(np.uint16)

    # colour.plotting.plot_image(colour.cctf_encoding(corrected_image));
    # print(f"Corrected image shape: {corrected_image.shape}")
    output_path = os.path.join(image_path, 'corrected')
    os.makedirs(output_path, exist_ok=True)
    output_filename = os.path.join(
        output_path, f"{os.path.splitext(os.path.basename(IMAGE_PATHS[i]))[0]}_corrected.png"
    )
    print(f"Saving corrected image to {output_filename}")

    try:
        # Use cv2.imwrite instead of colour.io.write_image to avoid Imageio issues
        corrected_image_bgr = cv2.cvtColor(corrected_image_16bit, cv2.COLOR_RGB2BGR)
        cv2.imwrite(output_filename, corrected_image_bgr)
        print(f"Saved corrected image: {output_filename}")
    except Exception as e:
        print(f"Error saving {output_filename}: {e}")
    print(f"Processed {os.path.basename(IMAGE_PATHS[i])}")
