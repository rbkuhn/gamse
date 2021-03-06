import os
import logging

logger = logging.getLogger(__name__)

import numpy as np
import astropy.io.fits as fits
import scipy.interpolate as intp
import scipy.signal

def combine_images(data,
        mode       = 'mean',  # mode = ['mean'|'sum'|'median']
        upper_clip = None,
        lower_clip = None,
        maxiter    = None,
        mask       = None,
        ):
    """Combine multiple FITS images.

    Args:
        data (:class:`numpy.ndarray`): Datacube of input images.
        mode (str): Combine mode. Either "mean" or "sum".
        upper_clip (float): Upper threshold of the sigma-clipping. Default is
            *None*.
        lower_clip (float): Lower threshold of the sigma-clipping. Default is
            *None*.
        maxiter (int): Maximum number of iterations.
        mask (str or :class:`numpy.ndarray`): Initial mask.

    Returns:
        :class:`numpy.ndarray`: Combined image array.

    Raises:
        TypeError: Dimension of **data** not equal to 3.
        ValueError: Unknown **mode**.

    """

    if data.ndim != 3:
        raise ValueError

    # if anyone of upper_clip and lower_clip is not None, then clip is True
    clip = (upper_clip is not None) or (lower_clip is not None)

    nimage, h, w = data.shape

    if clip:
        # perform sigma-clipping algorithm
        # initialize the final result array
        final_array = np.zeros((h, w))

        # split the image into small segmentations
        if h>4000 and h%4==0:   dy = h//4
        elif h>2000 and h%2==0: dy = h//2
        else:                   dy = h

        if w>4000 and w%4==0:   dx = w//4
        elif w>2000 and w%2==0: dx = w//2
        else:                   dx = w

        # segmentation loop starts here
        for y1 in np.arange(0, h, dy):
            y2 = y1 + dy
            for x1 in np.arange(0, w, dx):
                x2 = x1 + dx

                small_data = data[:,y1:y2,x1:x2]
                nz, ny, nx = small_data.shape
                # generate a mask containing the positions of maximum pixel
                # along the first dimension
                if mask is None:
                    small_mask = np.zeros_like(small_data, dtype=np.bool)
                elif isinstance(mask, str):
                    if mask == 'max':
                        small_mask = (np.mgrid[0:nz,0:ny,0:nx][0]
                                      == small_data.argmax(axis=0))
                    elif mask == 'min':
                        small_mask = (np.mgrid[0:nz,0:ny,0:nx][0]
                                      == small_data.argmin(axis=0))
                    else:
                        pass
                else:
                    pass
                
                for niter in range(maxiter):
                    mdata = np.ma.masked_array(small_data, mask=small_mask)
                    mean = mdata.mean(axis=0, dtype=np.float64).data
                    std  = mdata.std(axis=0, dtype=np.float64).data
                    new_small_mask = np.ones_like(small_mask, dtype=np.bool)
                    for i in np.arange(nimage):
                        chunk = small_data[i,:,:]
                
                        # parse upper clipping
                        if upper_clip is None:
                            # mask1 = [False....]
                            mask1 = np.zeros_like(chunk, dtype=np.bool)
                        else:
                            mask1 = chunk > mean + abs(upper_clip)*std
                
                        # parse lower clipping
                        if lower_clip is None:
                            # mask2 = [False....]
                            mask2 = np.zeros_like(chunk, dtype=np.bool)
                        else:
                            mask2 = chunk < mean - abs(lower_clip)*std
                
                        new_small_mask[i,:,:] = np.logical_or(mask1, mask2)

                    if new_small_mask.sum() == small_mask.sum():
                        break
                    small_mask = new_small_mask
                
                mdata = np.ma.masked_array(small_data, mask=small_mask)
                
                if mode == 'mean':
                    mean = mdata.mean(axis=0).data
                    final_array[y1:y2,x1:x2] = mean
                elif mode == 'sum':
                    mean = mdata.mean(axis=0).data
                    final_array[y1:y2,x1:x2] = mean*nimage
                elif mode == 'median':
                    final_array[y1:y2,x1:x2] = np.median(mdata, axis=0).data
                else:
                    raise ValueError
        # segmentation loop ends here
        return final_array
    else:
        if mode == 'mean':
            return data.mean(axis=0)
        elif mode == 'sum':
            return data.sum(axis=0)
        elif mode == 'median':
            return np.median(data, axis=0)
        else:
            raise ValueError
            return None

def make_mask():
    """
    Generate a mask
    1: pixel does not covered by read out region of the detector
    2: bad pixel
    3: flux saturated
    4: cosmic ray
    """
    pass


def savitzky_golay_2d(z, window_length, order, mode='reflect', cval=None,
        derivative=None):
    """Savitzky-Golay 2D filter, with different window size and order along *x*
    and *y* directions.

    Args:
        z (:class:`numpy.ndarray`): Input 2-d array.
        window_length (int, tuple, or list): Window size in pixel.
        order (int, tuple, or list): Degree of polynomial.
        mode (str): Edge Mode.
        derivative (str): *None*, *col*, *row*, or *both*.

    Returns:
        :class:`numpy.ndarray` or tuple: Output 2-d array, or a tuple containing
            derivative arries along *x*- and *y*-axes, respetively, if
            derivative = "both".
        
    """
    if isinstance(window_length, int):
        ywin, xwin = window_length, window_length
    elif isinstance(window_length, (tuple, list)):
        ywin, xwin = window_length[0], window_length[1]
    else:
        raise ValueError
    if xwin%2==0 or ywin%2==0:
        raise ValueError('window_length must be odd')

    if isinstance(order, int):
        yorder, xorder = order, order
    elif isinstance(order, (tuple, list)):
        yorder, xorder = order[0], order[1]
    else:
        raise ValueError

    # half of the window size
    yhalf = ywin//2
    xhalf = xwin//2

    # exponents of the polynomial. 
    # p(x,y) = a0 + a1*x + a2*y + a3*x^2 + a4*y^2 + a5*x*y + ...
    # this line gives a list of two item tuple. Each tuple contains
    # the exponents of the k-th term. First element of tuple is for x
    # second element for y.
    # Ex. exps = [(0,0), (1,0), (0,1), (2,0), (1,1), (0,2), ...]
    maxorder = max(xorder, yorder)
    exps = [(k-n, n) for k in range(max(xorder, yorder)+1) for n in range(k+1)
            if k-n <= xorder and n <= yorder]

    # coordinates of points
    xind = np.arange(-xhalf, xhalf+1, dtype=np.float64)
    yind = np.arange(-yhalf, yhalf+1, dtype=np.float64)
    dx = np.repeat(xind, ywin)
    dy = np.tile(yind, [xwin, 1]).reshape(xwin*ywin,)

    # build matrix of system of equation
    A = np.empty(((xwin*ywin), len(exps)))
    for i, exp in enumerate(exps):
        A[:, i] = (dx**exp[0])*(dy**exp[1])

    Z = expand_2darray(z, (yhalf, xhalf), mode=mode, cval=cval)

    # solve system and convolve
    if derivative is None:
        m = np.linalg.pinv(A)[0].reshape((ywin, xwin))
        return scipy.signal.fftconvolve(Z, m, mode='valid')
    elif derivative == 'col':
        c = np.linalg.pinv(A)[1].reshape((ywin, xwin))
        return scipy.signal.fftconvolve(Z, -c, mode='valid')
    elif derivative == 'row':
        r = np.linalg.pinv(A)[2].rehsape((ywin, xwin))
        return scipy.signal.fftconvolve(Z, -r, mode='valid')
    elif derivative == 'both':
        c = np.linalg.pinv(A)[1].reshape((ywin, xwin))
        r = np.linalg.pinv(A)[2].rehsape((ywin, xwin))
        return (scipy.signal.fftconvolve(Z, -r, mode='valid'),
                scipy.signal.fftconvolve(Z, -c, mode='valid'))
    else:
        return None

def array_to_table(array):
    """Convert the non-zeros elements of a Numpy array to a stuctured array.

    Args:
        array (:class:`numpy.ndarray`): Input Numpy array.

    Returns:
        :class:`numpy.dtype`: Numpy stuctured array.

    See also:
        :func:`table_to_array`

    Examples:
        Below shows an example of converting a numpy 2-d array `a` to a
        structured array `t`.
        The first few coloumns (`axis_0`, `axis_1`, ... `axis_n-1`) in `t`
        correspond to the coordinates of the *n*-dimensional input array, and
        the last column (`value`) are the elements of the input array.
        The reverse process is :func:`table_to_array`

        .. code-block:: python

            >>> import numpy as np
            >>> from edrs.echelle.imageproc import array_to_table

            >>> a = np.arange(12).reshape(3,4)
            >>> a
            array([[ 0,  1,  2,  3],
                   [ 4,  5,  6,  7],
                   [ 8,  9, 10, 11]])
            >>> t = array_to_table(a)
            >>> t
            array([(0, 1,  1), (0, 2,  2), (0, 3,  3), (1, 0,  4), (1, 1,  5),
                   (1, 2,  6), (1, 3,  7), (2, 0,  8), (2, 1,  9), (2, 2, 10),
                   (2, 3, 11)], 
                  dtype=[('axis_0', '<i2'), ('axis_1', '<i2'), ('value', '<i8')])

    """
    dimension = len(array.shape)
    types = [('axis_%d'%i, np.int16) for i in range(dimension)]
    types.append(('value', array.dtype.type))
    names, formats = list(zip(*types))
    custom = np.dtype({'names': names, 'formats': formats})
    
    table = []
    ind = np.nonzero(array)
    for coord, value in zip(zip(*ind), array[ind]):
        row = list(coord)
        row.append(value)
        row = np.array(tuple(row), dtype=custom)
        table.append(row)
    table = np.array(table, dtype=custom)
    return(table)

def table_to_array(table, shape):
    """Convert a structured array to Numpy array.

    This is the reverse process of :func:`array_to_table`.
    For the elements of which coordinates are not listed in the table, zeros are
    filled.

    Args:
        table (:class:`numpy.dtype`): Numpy structured array.
        shape (tuple): Shape of output array.

    Returns:
        :class:`numpy.ndarray`: Mask image array.

    See also:
        :func:`array_to_table`

    Examples:
        Below shows an example of converting a numpy 2-d array `a` to a
        structured array `t` using :func:`array_to_table`, and then converting
        `t` back to `a` using :func:`table_to_array`.

        .. code-block:: python

            >>> import numpy as np
            >>> from edrs.echelle.imageproc import array_to_table

            >>> a = np.arange(12).reshape(3,4)
            >>> a
            array([[ 0,  1,  2,  3],
                   [ 4,  5,  6,  7],
                   [ 8,  9, 10, 11]])
            >>> t = array_to_table(a)
            >>> t
            array([(0, 1,  1), (0, 2,  2), (0, 3,  3), (1, 0,  4), (1, 1,  5),
                   (1, 2,  6), (1, 3,  7), (2, 0,  8), (2, 1,  9), (2, 2, 10),
                   (2, 3, 11)], 
                  dtype=[('axis_0', '<i2'), ('axis_1', '<i2'), ('value', '<i8')])
            >>> a = table_to_array(a, (3,4))
            >>> a
            array([[ 0,  1,  2,  3],
                   [ 4,  5,  6,  7],
                   [ 8,  9, 10, 11]])

    """

    array = np.zeros(shape, dtype=table.dtype[-1].type)
    coords = tuple(table[col] for col in table.dtype.names[0:-1])
    array[coords] = table['value']

    return array


def fix_pixels(data, mask, direction, method):
    """Fix specific pixels of the CCD image by interpolating surrounding pixels.

    Args:
        data (:class:`numpy.ndarray`): Input image as a 2-D array.
        mask (:class:`numpy.ndarray`): Mask of pixels to be fixed. This array
            shall has the same shape as **data**.
        direction (str or int): Interpolate along which axis (*X* = 1,
            *Y* = 0).
        method (str): Interpolationg method ('linear' means linear
            interpolation, and 'cubic' means cubic spline interpolation).

    Returns:
        :class:`numpy.ndarray`: The fixed image as a 2-D array.
    """
    # make a new copy of the input data
    newdata = np.copy(data)

    # determine the axis
    if isinstance(direction, str):
        direction = {'x':1, 'y':0}[direction.lower()]

    # find the rows or columns to interpolate
    masklist = mask.sum(axis=direction)

    # determine interpolation method
    k = {'linear':1, 'cubic':3}[method]

    if direction == 0:
        # fix along Y axis
        x = np.arange(data.shape[0])
        cols = np.nonzero(masklist)[0]
        for col in cols:
            m = mask[:,col]
            rm = ~m
            y = data[:,col]
            f = intp.InterpolatedUnivariateSpline(x[rm],y[rm],k=k)
            newdata[:,col][m] = f(x[m])
    elif direction == 1:
        # fix along X axis
        x = np.arange(data.shape[1])
        rows = np.nonzero(masklist)[0]
        for row in rows:
            m = mask[row,:]
            rm = ~m
            y = data[row,:]
            f = intp.InterpolatedUnivariateSpline(x[rm],y[rm],k=k)
            newdata[row,:][m] = f(x[m])
    else:
        print('direction must be 0 or 1')
        raise ValueError

    return newdata


def expand_2darray(z, n, mode, cval=None):
    """Expand a two-dimensional array with given edge modes.

    Args:
        z (:class:`numpy.ndarray`): Input 2-D array.
        n (int, tuple, or list): Number of pixels to expand.
        mode (string): Edge mode.
        cval (int or float): Constant value to fill the array.

    Returns:
        :class:`numpy.ndarray`: The expanded array.


    """
    if isinstance(z, int):
        nt, nb, nl, nr = n, n, n, n
    if isinstance(n, (tuple, list)):
        if len(n) == 2:
            nt, nb = n[0], n[0]
            nl, nr = n[1], n[1]
        elif len(n) == 4:
            nt, nb, nl, nr = n[0], n[1], n[2], n[3]
        else:
            raise ValueError

    new_shape = (z.shape[0] + nt + nb, z.shape[1] + nl + nr)
    Z = np.zeros(new_shape)

    Z[nt:-nb, nl:-nr] = z

    # pad input array with appropriate values at the four borders
    if mode == 'reflect':
        # top, bottom, left, and right bands
        Z[:nt, nl:-nr]  = np.flipud(z[:nt, :])
        Z[-nb:, nl:-nr] = np.flipud(z[-nb:, :])
        Z[nt:-nb, :nl]  = np.fliplr(z[:, :nl])
        Z[nt:-nb, -nr:] = np.fliplr(z[:, -nr:])

        # top-left, top-right, bottom-left, and bottom-right corners
        Z[:nt, :nl]   = np.flipud(np.fliplr(z[:nt, :nl]))
        Z[:nt, -nr:]  = np.flipud(np.fliplr(z[:nt, -nr:]))
        Z[-nb:, :nl]  = np.flipud(np.fliplr(z[-nb:, :nl]))
        Z[-nb:, -nr:] = np.flipud(np.fliplr(z[-nb:, -nr:]))

    elif mode == 'mirror':
        # top, bottom, left, and right bands
        Z[:nt, nl:-nr]  = np.flipud(z[1:1+nt, :])
        Z[-nb:, nl:-nr] = np.flipud(z[-nb-1:-1, :])
        Z[nt:-nb, :nl]  = np.fliplr(z[:, 1:1+nl])
        Z[nt:-nb, -nr:] = np.fliplr(z[:, -nr-1:-1])

        # top-left, top-right, bottom-left, and bottom-right corners
        Z[:nt, :nl]   = np.flipud(np.fliplr(z[1:1+nt, 1:1+nl]))
        Z[:nt, -nr:]  = np.flipud(np.fliplr(z[1:1+nt, -nr-1:-1]))
        Z[-nb:, :nl]  = np.flipud(np.fliplr(z[-nb-1:-1, 1:1+nl]))
        Z[-nb:, -nr:] = np.flipud(np.fliplr(z[-nb-1:-1, -nr-1:-1]))

    elif mode == 'nearest':
        # top, bottom, left, and right bands
        Z[:nt, nl:-nr]  = z[0, :]
        Z[-nb:, nl:-nr] = z[-1, :]
        Z[nt:-nb, :nl]  = z[:, 0].reshape(-1,1)
        Z[nt:-nb, -nr:] = z[:, -1].reshape(-1,1)

        # top-left, top-right, bottom-left, and bottom-right corners
        Z[:nt, :nl]   = z[0, 0]
        Z[:nt, -nr:]  = z[0, -1]
        Z[-nb:, :nl]  = z[-1, 0]
        Z[-nb:, -nr:] = z[-1, -1]

    elif mode == 'constant':
        if cval is None:
            raise ValueError
        # top, bottom, left, and right bands
        Z[:nt, nl:-nr]  = cval
        Z[-nb:, nl:-nr] = cval
        Z[nt:-nb, :nl]  = cval
        Z[nt:-nb, -nr:] = cval

        # top-left, top-right, bottom-left, and bottom-right corners
        Z[:nt, :nl]   = cval
        Z[:nt, -nr:]  = cval
        Z[-nb:, :nl]  = cval
        Z[-nb:, -nr:] = cval

    elif mode == 'z-symmetry':
        # top, bottom, left, and right bands
        Z[:nt, nl:-nr]  = z[0, :] - (np.flipud(z[1:1+nt, :]) - z[0, :])
        Z[-nb:, nl:-nr] = z[-1, :] - (np.flipud(z[-nb-1:-1, :]) - z[-1, :])
        band = np.tile(z[:,0].reshape(-1,1), [1,nl])
        Z[nt:-nb, :nl] = band - (np.fliplr(z[:, 1:1+nl]) - band)
        band = np.tile(z[:,-1].reshape(-1,1), [1,nr])
        Z[nt:-nb, -nr:] = band - (np.fliplr(z[:, -nr-1:-1]) - band)

        # top-left, top-right, bottom-left, and bottom-right corners
        Z[:nt,:nl]   = z[0,0] - (np.flipud(np.fliplr(z[1:1+nt,1:1+nl])) - z[0,0])
        Z[:nt,-nr:]  = z[0,-1] - (np.flipud(np.fliplr(z[1:1+nt,-nr-1:-1])) - z[0,-1])
        Z[-nb:,:nl]  = z[-1,0] - (np.flipud(np.fliplr(z[-nb-1:-1,1:1+nl])) - z[-1,0])
        Z[-nb:,-nr:] = z[-1,-1] - (np.flipud(np.fliplr(z[-nb-1:-1,-nr-1:-1])) - z[-1,-1])

    else:
        raise ValueError

    return Z

