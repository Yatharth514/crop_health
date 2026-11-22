from pathlib import Path

import numpy as np
from PIL import Image


IMAGE_SIZE = (128, 128)
HISTOGRAM_BINS = 16


def rgb_to_hsv(rgb):
    """
    Convert an RGB image to HSV.

    Input: RGB float array in range [0, 1].
    Output: HSV array, H in [0, 1], S and V in [0, 1].
    """

    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    maximum = np.max(rgb, axis=-1)
    minimum = np.min(rgb, axis=-1)
    delta = maximum - minimum

    hue = np.zeros_like(maximum)

    mask = delta > 0

    r_mask = mask & (maximum == r)
    g_mask = mask & (maximum == g)
    b_mask = mask & (maximum == b)

    hue[r_mask] = ((g[r_mask] - b[r_mask]) / delta[r_mask]) % 6
    hue[g_mask] = ((b[g_mask] - r[g_mask]) / delta[g_mask]) + 2
    hue[b_mask] = ((r[b_mask] - g[b_mask]) / delta[b_mask]) + 4

    hue /= 6

    saturation = np.zeros_like(maximum)

    np.divide(
        delta,
        maximum,
        out=saturation,
        where=maximum > 0
    )

    return np.stack(
        [hue, saturation, maximum],
        axis=-1
    )


def extract_lbp(gray):
    """
    Calculate a basic 8-neighbour Local Binary Pattern.
    Returns a normalized 256-bin histogram.
    """

    center = gray[1:-1, 1:-1]

    neighbours = [
        gray[:-2, :-2],
        gray[:-2, 1:-1],
        gray[:-2, 2:],
        gray[1:-1, 2:],
        gray[2:, 2:],
        gray[2:, 1:-1],
        gray[2:, :-2],
        gray[1:-1, :-2],
    ]

    lbp = np.zeros(center.shape, dtype=np.uint8)

    for bit, neighbour in enumerate(neighbours):
        lbp |= ((neighbour >= center).astype(np.uint8) << bit)

    histogram = np.bincount(
        lbp.ravel(),
        minlength=256
    ).astype(np.float32)

    histogram /= max(histogram.sum(), 1)

    return histogram


def extract_features(image_path):
    """
    Extract handcrafted colour and texture features
    from a tomato leaf image.
    """

    image_path = Path(image_path)

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image = image.resize(IMAGE_SIZE)

    rgb = np.asarray(image, dtype=np.float32) / 255.0

    hsv = rgb_to_hsv(rgb)

    features = []

    # 1. RGB and HSV statistics
    for color_space in (rgb, hsv):
        features.extend(color_space.mean(axis=(0, 1)))
        features.extend(color_space.std(axis=(0, 1)))

    # 2. RGB and HSV histograms
    for color_space in (rgb, hsv):
        for channel in range(3):

            histogram, _ = np.histogram(
                color_space[..., channel],
                bins=HISTOGRAM_BINS,
                range=(0, 1),
                density=False
            )

            histogram = histogram.astype(np.float32)
            histogram /= histogram.sum()

            features.extend(histogram)

    # 3. Approximate colour ratios
    hue = hsv[..., 0]
    saturation = hsv[..., 1]
    value = hsv[..., 2]

    green = (
        (hue >= 0.18) &
        (hue <= 0.45) &
        (saturation > 0.2)
    )

    yellow = (
        (hue >= 0.12) &
        (hue < 0.18) &
        (saturation > 0.2)
    )

    brown = (
        (hue >= 0.03) &
        (hue < 0.12) &
        (saturation > 0.2) &
        (value < 0.75)
    )

    features.extend([
        green.mean(),
        yellow.mean(),
        brown.mean()
    ])

    # 4. Grayscale statistics
    gray = (
        0.299 * rgb[..., 0] +
        0.587 * rgb[..., 1] +
        0.114 * rgb[..., 2]
    )

    features.extend([
        gray.mean(),
        gray.std()
    ])

    # 5. Local Binary Pattern texture histogram
    features.extend(extract_lbp(gray))

    return np.asarray(features, dtype=np.float32)