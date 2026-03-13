import numpy as np
from scipy.ndimage import gaussian_filter

def test_sample(row_index,column_index,y_size,x_size,pixel_size,dwell,y_center=None,x_center=None,full_line=True,full_image=False):
    resolution = 0.05
    frequency = 10.
    photon_flux = 1E6
    if x_center is None:
        x_center = x_size // 2 * pixel_size
    if y_center is None:
        y_center = y_size // 2 * pixel_size

    #calculate pixel distances and convert to angle
    y,x = np.indices((y_size,x_size)).astype('float') * pixel_size
    y -= -y_center + y_size // 2 * pixel_size
    x -= -x_center + x_size // 2 * pixel_size
    angles = np.arctan(y/x)
    pattern = gaussian_filter((np.cos(frequency*angles) > 0).astype('float'),sigma=resolution/pixel_size) * photon_flux * dwell / 1000.
    pattern = np.random.poisson(pattern)
    if full_image:
        return pattern
    elif full_line:
        return pattern[row_index]
    else:
        return pattern[row_index,column_index]