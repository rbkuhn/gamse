import logging

logger = logging.getLogger(__name__)

import os
import time
import math
import numpy as np
from numpy.polynomial import Chebyshev
import astropy.io.fits   as fits
import scipy.interpolate as intp
import scipy.signal      as sg
import scipy.optimize    as opt
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.ticker as tck

from ..utils.onedarray import pairwise, derivative

class ApertureLocation(object):
    '''
    Location of an echelle order.

    Attributes:
        direction (integer): 0 if along Y axis; 1 if along X axis.
        position (:class:`numpy.polynomial`): Polynomial of aperture location.
        
    '''
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

        self.__update_attr()

    def set_nodes(self, key, xdata, ydata):
        '''
        Set nodes for center, lower, or upper lines.
        
        Args:
            key (str): Keyword.
            xdata (list): List of x coordinates [*x*:sub:`1`, *x*:sub:`2`,
                *x*:sub:`3`, ...].
            ydata (list): List of y coordinates [*y*:sub:`1`, *y*:sub:`2`,
                *y*:sub:`3`, ...].

        '''
        # filter the None values in (xdata, ydata)
        xydata = [(x,y) for x, y in zip(xdata, ydata)
                  if x is not None and y is not None]
        xnodes, ynodes = zip(*xydata)

        # sort the nodes according to x coordinates
        xnodes, ynodes = np.array(xnodes), np.array(ynodes)
        if self.direction == 0:
            # order is along y axis
            xnodes = xnodes[ynodes.argsort()]
            ynodes = np.sort(ynodes)
        elif self.direction == 1:
            # order is along x axis
            ynodes = ynodes[xnodes.argsort()]
            xnodes = np.sort(xnodes)

        xydata = [(x, y) for x, y in zip(xnodes, ynodes)]

        setattr(self, 'nodes_%s'%key, xydata)

    def fit_nodes(self, key, degree, clipping, maxiter):
        '''
        Fit the polynomial iteratively with sigma-clipping method and get the
        coefficients.

        Args:
            key (string): Either 'center', 'upper', or 'lowr'.
            degree (integer): Degree of polynomial used to fit the position.
            clipping (float): Upper and lower threshold in the sigma-clipping
                method.
            maxiter (integer): Maximum number of iteration of the polynomial
                fitting.
        '''

        h, w = self.shape
        nodes = getattr(self, 'nodes_%s'%key)
        xnodes, ynodes = zip(*nodes)
        
        # normalize to [0, 1)
        xfit = np.array(xnodes, dtype=np.float32)/w
        yfit = np.array(ynodes, dtype=np.float32)/h

        if self.direct == 0:
            # order is along y axis
            xfit, yfit = yfit, xfit
        elif self.direct == 1:
            # order is along x axis
            xfit, yfit = xfit, yfit

        # initialize mask
        mask = np.ones_like(xfit, dtype=np.bool)
        for niter in range(maxiter):
            # determine the appropriate degree of polynomial
            npoints = mask.sum()
            if npoints <= 1:
                # if there's only one point in this order, then skip
                continue
            else:
                deg = min(npoints-1, degree)

            coeff = np.polyfit(xfit[mask], yfit[mask], deg=deg)
            res = yfit - np.polyval(coeff, xfit)
            mean = res[mask].mean()
            std  = res[mask].std(ddof=1)
            m1 = res < mean + clipping*std
            m2 = res > mean - clipping*std
            new_mask = m1*m2
            if new_mask.sum() == mask.sum():
                break
            mask = new_mask

        # put the coefficients into the order location instance
        setattr(self, 'coeff_%s'%key, coeff)

        info = {
                'xnodes':    xfit*w,
                'ynodes':    yfit*h,
                'residuals': res,
                'sigma':     std,
                'mask':      mask,
                }

        return info

    def set_position(self, poly):
        setattr(self, 'position', poly)

    def get_center(self):
        '''Get coordinate of the center pixel.

        Args:
            No args
        Returns:
            float: coordinate of the center pixel.
        '''
        h, w = self.shape
        if self.direct == 0:
            # aperture along Y direction
            center = self.position(h/2.)
        elif self.direct == 1:
            # aperture along X direction
            center = self.position(w/2.)
        else:
            print('Cannot recognize direction: '+self.direct)
        return center

    def __str__(self):
        h, w = self.shape
        if self.direct == 0:
            # aperture along Y direction
            axis = 'y'
            centerpix = self.position(h/2.)
            coord = (centerpix, h/2.)
        elif self.direct == 1:
            # aperture along X direction
            axis = 'x'
            centerpix = self.position(w/2.)
            coord = (w/2., centerpix)
        return 'Echelle aperture centered at (%4d, %4d) along %s axis'%(
                coord[0], coord[1], axis)

    def to_string(self):
        '''Convert Aperture information to string.
        '''

        string  = '%8s = %d'%('direct', self.direct)+os.linesep
        string += '%8s = %s'%('shape',  str(self.shape))+os.linesep

        strlst = ['%+15.10e'%c for c in self.position.coef]
        string += 'position = [%s]'%(', '.join(strlst))+os.linesep

        # write domain of polynomial
        domain = self.position.domain
        string += '  domain = [%f, %f]'%(domain[0], domain[1])+os.linesep

        # find nodes
        for key in ['lower', 'center', 'upper']:
            key1 = 'nodes_%s'%key
            if hasattr(self, key1):
                nodes = getattr(self, key1)
                strlst = ['(%g, %g)'%(x,y) for x, y in nodes]
                string += '%6s = [%s]%s'%(key1, ', '.join(strlst), os.linesep)

        # find coefficients
        for key in ['lower', 'center', 'upper']:
            key1 = 'coeff_%s'%key
            if hasattr(self, key1):
                coeff = getattr(self, key1)
                strlst = ['%+15.10e'%c for c in coeff]
                string += '%6s = [%s]%s'%(key1, ', '.join(strlst), os.linesep)

        for key in ['nsat','mean','median','max']:
            if hasattr(self, key):
                value = getattr(self, key)
                string += '%8s = %g'%(key, value)+os.linesep

        return string

    def __update_attr(self):
        '''Update attributes'''

        # udpate direction attribute
        if hasattr(self, 'direct'):
            if self.direct in ['x','X']:
                self.direct = 1
            elif self.direct in ['y','Y']:
                self.direct = 0

    def get_distance(self, aperloc):
        '''Calculate the distance to another :class:`ApertureLocation` instance.
        
        Args:
            aperloc (:class:`ApertureLocation`): Another
                :class:`ApertureLocation` instance.
        Returns:
            float: The distance between the centeral positions.

        '''
        if self.direct != aperloc.direct:
            print('ApertureLocations have different directions')
            return None
        return self.get_center() - aperloc.get_center()

class ApertureSet(object):
    '''
    ApertureSet is a group of :class:`ApertureLocation` instances.

    Attributes:
        _dict (dict): Dict containing aperture numbers and
            :class:`ApertureLocation` instances.
    '''
    def __init__(self, *args, **kwargs):
        self._dict = {}
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getitem__(self, key):
        return self._dict[key]

    def __setitem__(self, key, value):
        self._dict[key] = value

    def __len__(self):
        return len(self._dict)

    def __contains__(self, key):
        return key in self._dict

    def items(self):
        return self._dict.items()

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def __str__(self):
        string = ''
        for aper, aper_loc in sorted(self._dict.items()):
            string += 'APERTURE LOCATION %d%s'%(aper, os.linesep)
            string += aper_loc.to_string()
        return string

    def add_aperture(self, aperture_loc):
        '''Add an :class:`ApertureLocation` instance into this set.

        Args:
            aperture_loc (:class:`ApertureLocation`): An
                :class:`ApertureLocation` instance to be added.
        Returns:
            No returns.
        '''
        n = len(self._dict)
        if n == 0:
            self._dict[0] = aperture_loc
        else:
            maxi = max(self._dict.keys())
            self._dict[maxi+1] = aperture_loc

    def sort(self):
        '''Sort the apertures according to their positions inside this instance.
        '''
        aperloc_lst = sorted([aper_loc for aper, aper_loc in self._dict.items()],
                              key=lambda aper_loc: aper_loc.get_center())
        for i in range(len(aperloc_lst)):
            self._dict[i] = aperloc_lst[i]

    def save_txt(self, filename):
        '''
        Save the aperture set into an ascii file.
        
        Args:
            filename (string): Name of the output ascii file.
        '''
        outfile = open(filename, 'w')
        outfile.write(str(self))
        outfile.close()

    def save_reg(self, filename, color='green', channel=None):
        '''
        Save the aperture set into a reg file that can be loaded in SAO-DS9.

        Args:
            filename (string): Name of the output reg file.
            color (string): Color of the lines.
            channel (string): Write the channel name if not *None*.

        Returns:
            No returns.
        '''
        outfile = open(filename, 'w')
        outfile.write('# Region file format: DS9 version 4.1'+os.linesep)
        outfile.write('global color=%s dashlist=8 3 width=1 '%color)
        outfile.write('font="helvetica 10 normal roman" select=1 highlite=1 ')
        outfile.write('dash=0 fixed=0 edit=1 move=1 delete=1 include=1 ')
        outfile.write('source=1'+os.linesep)
        outfile.write('physical'+os.linesep)

        for aper, aper_loc in sorted(self.items()):

            domain = aper_loc.position.domain
            d1, d2 = int(domain[0]), int(domain[1])+1

            outfile.write('# aperture %3d'%aper + os.linesep)

            if aper_loc.direct == 1:
                # write text in the left edge
                x = d1-6
                y = aper_loc.position(x)
                text = '# text(%7.2f, %7.2f) text={%3d} '%(x+1, y+1, aper)
                outfile.write(text+os.linesep)

                # write text in the right edge
                x = d2-1+6
                y = aper_loc.position(x)
                text = '# text(%7.2f, %7.2f) text={%3d} '%(x+1, y+1, aper)
                outfile.write(text+os.linesep)

                # write text in the center
                x = (d1+d2)/2.
                y = aper_loc.position(x)
                if channel is None:
                    text = '# text(%7.2f, %7.2f) text={Aperture %3d} '%(x+1, y+1+5, aper)
                else:
                    text = '# text(%7.2f, %7.2f) text={Channel %s, Aperture %3d} '%(x+1, y+1+5, channel, aper)
                outfile.write(text+os.linesep)

                # draw lines
                x = np.linspace(d1, d2, 50)
                y = aper_loc.position(x)
                for (x1,x2), (y1, y2) in zip(pairwise(x), pairwise(y)):
                    text = 'line(%7.2f,%7.2f,%7.2f,%7.2f)'%(x1+1, y1+1, x2+1, y2+1)
                    outfile.write(text+os.linesep)

        outfile.close()

    def to_fitsheader(self, header, channel=None):
        prefix = 'HIERARCH EDRS TRACE'
        if channel is not None:
            prefix += ' CHANNLE %s'%channel

        for aper, aper_loc in sorted(self._dict.items()):
            header[prefix+' APERTURE %d DIRECT'%aper]  = aper_loc.direct
            header[prefix+' APERTURE %d SHAPE0'%aper]  = aper_loc.shape[0]
            header[prefix+' APERTURE %d SHAPE1'%aper]  = aper_loc.shape[1]
            for ic, c in enumerate(aper_loc.position.coef):
                header[prefix+' APERTURE %d COEFF %d'%(aper, ic)] = c
            header[prefix+' APERTURE %d DOMAIN0'%aper] = aper_loc.position.domain[0]
            header[prefix+' APERTURE %d DOMAIN1'%aper] = aper_loc.position.domain[1]
            header[prefix+' APERTURE %d NSAT'%aper]    = aper_loc.nsat
            header[prefix+' APERTURE %d MEAN'%aper]    = aper_loc.mean
            header[prefix+' APERTURE %d MEDIAN'%aper]  = aper_loc.median
            header[prefix+' APERTURE %d MAX'%aper]     = aper_loc.max

        return header

    def __iter__(self):
        return _ApertureSetIterator(self._dict)

    def get_local_seperation(self, aper):
        '''
        Get the local seperation in pixels per aperture number in the center
        of the aperture set.

        Args:
            aper (integer): Aperture number.
        Returns:
            float: Local seperation in pixels per aperture number.
        '''

        aper_lst, center_lst = [], []
        for _aper, _aper_loc in sorted(self.items()):
            aper_lst.append(_aper)
            center_lst.append(_aper_loc.get_center())

        seperation_lst = derivative(aper_lst, center_lst)
        i = aper_lst.index(aper)
        return seperation_lst[i]


    def find_aper_offset(self, aperset):
        '''
        Find the aperture offset between this instance and the input
        :class:`ApertureSet` instance.
        
        The offset means that the Aperture *n* aperture of this
        :class:`ApertureSet` almost has the same position as the Aperture
        *n* + *offset* in the input :class:`ApertureSet`.
        '''
        # fint the smalleset common aper number.
        for aper in self:
            if aper in aperset:
                break

        # calculate the approximate distance between these two common apertures
        diff_cen = self[aper].get_center() - aperset[aper].get_center()
        # calculate the approximate aperture difference
        sep1 = self.get_local_seperation(aper)
        sep2 = aperset.get_local_seperation(aper)

        sep = (sep1 + sep2)/2.
        offset0 = int(round(diff_cen/sep))

        # find the offset list
        o1 = -offset0
        o2 = 3*offset0
        # in case o1 > o2, exchange o1 and o2
        o1, o2 = min(o1,o2), max(o1, o2)
        # the minimum search offset is -3, and the maximum search offset is 3
        o1, o2 = min(o1, -3), max(o2, 3)
        offset_lst = range(o1, o2)

        # find the center dict for every aperture for both this aperset and the
        # input aperset
        center_lst1 = {_aper: _aper_loc.get_center()
                        for _aper, _aper_loc in self.items()}
        center_lst2 = {_aper: _aper_loc.get_center()
                        for _aper, _aper_loc in aperset.items()}

        # search the offset
        median_diff_lst = []
        for offset in offset_lst:
            diff_lst = []
            for aper in sorted(center_lst1):
                if aper in center_lst1 and aper+offset in center_lst2:
                    diff = center_lst1[aper] - center_lst2[aper+offset]
                    diff_lst.append(diff)
            # use the median value of the diff_lst
            median_diff = np.median(diff_lst)
            median_diff_lst.append(median_diff)

        # find the offset with least absolute value of median diff
        i = np.abs(median_diff_lst).argmin()
        return offset_lst[i]

    def shift_aperture(self, offset):
        '''Shift the aperture number by offset.

        Args:
            offset (integer): Offset to shift.
        Returns:
            No returns
        '''

        new_dict = {}
        for _aper, _aper_loc in self.items():
            new_dict[_aper+offset] = _aper_loc
        self._dict = new_dict

    def get_positions(self, x):
        '''Get central positions of all chelle orders.

        Args:
            x (integer or :class:`numpy.array`): Input *X* coordiantes of the
                central positions to calculate.
        Returns:
            dict: A dict of `{aperture: y}` containing cetral positions of
                all orders.
            
        '''
        return {aper: aperloc.position(x) for aper,aperloc in self.items()}

    def get_boundaries(self, x):
        '''Get upper and lower boundaries of all echelle orders.
        
        Args:
            x (integer or :class:`numpy.array`): Input *X* coordiantes of the
                boundaries to calculate.
        Returns:
            dict: A dict of `{aperture: (lower, upper)}`, where `lower` and
                `upper` are boundary arries.
        '''
        lower_bounds = {}
        upper_bounds = {}
        prev_aper     = None
        prev_position = None
        for aper, aperloc in sorted(self.items()):
            position = aperloc.position(x)
            if prev_aper is not None:
                mid = (position + prev_position)/2
                lower_bounds[aper]      = mid
                upper_bounds[prev_aper] = mid
            prev_position = position
            prev_aper     = aper

        # find the lower bound for the first aperture
        minaper = min(self.keys())
        position = self[minaper].position(x)
        dist = upper_bounds[minaper] - position
        lower_bounds[minaper] = position - dist
 
        # find the upper bound for the last aperture
        maxaper = max(self.keys())
        position = self[maxaper].position(x)
        dist = position - lower_bounds[maxaper]
        upper_bounds[maxaper] = position + dist

        return {aper: (lower_bounds[aper], upper_bounds[aper])
                for aper in self.keys()}

class _ApertureSetIterator(object):
    '''
    Interator class for :class:`ApertureSet`.
    '''
    def __init__(self, item_dict):
        self.item_dict = item_dict
        self.n = len(self.item_dict)
        self.i = 0
    def __iter__(self):
        return self
    def __next__(self):
        if self.i < self.n:
            i = self.i
            self.i += 1
            return list(self.item_dict.keys())[i]
        else:
            raise StopIteration()

def find_apertures(data, mask, scan_step=50, minimum=1e-3, seperation=20,
        sep_der=0.0, filling=0.3, degree=3, display=True, filename=None,
        fig_file=None, trace_file=None, reg_file=None):
    '''
    Find the positions of apertures on a CCD image.

    Args:
        data (:class:`numpy.array`): Image data.
        mask (:class:`numpy.array`): Saturation mask with the same shape as
            **data**. The saturated pixels are marke as 1.
        scan_step (integer): Steps of pixels used to scan along the main
            dispersion direction.
        minimum (float): Minimum value to filter the input image.
        seperation (float): Estimated order seperations (in pixel)
            along the cross-dispersion.
        sep_der (float): Estimated differential order seperations per 1000
            pixels. The real order seperations are estimated by **seperation**
            + **sep_der** × *pixel* / 1000
        filling (float): Fraction of detected pixels to total step of scanning.
        degree (integer): Degree of polynomials to fit aperture locations.
        display (bool): If *True*, display a figure on the screen.
        filename (string): Name of the input file. Only used to display the
            title in the figure.
        fig_file (string): Path to the output figure.
        trace_file (string): Path to the output ascii file.
        reg_file (string): Name of region file that can be loaded in SAO-DS9.

    Returns:
        :class:`ApertureSet`: An :class:`ApertureSet` instance containing the
            aperture locations.

    '''
    from ..utils.onedarray import get_local_minima, derivative

    sat_mask = mask

    h, w = data.shape

    # filter the pixels smaller than the input "minimum" value
    logdata = np.log10(np.maximum(data, minimum))

    # initialize the color list
    colors = 'rgbcmyk'

    # create a background image
    fig = plt.figure(figsize=(20,10),dpi=150)
    ax1 = fig.add_axes([0.05,0.06,0.43,0.86])
    ax2 = fig.add_axes([0.54,0.06,0.43,0.86])
    ax1.imshow(logdata,cmap='gray',interpolation='none')
    # create a colormap for saturation mask
    sat_cmap = mcolors.LinearSegmentedColormap.from_list('TransRed',
               [(1,0,0,0), (1,0,0,0.8)], N=2)
    ax1.imshow(sat_mask, interpolation='none',cmap=sat_cmap)
    ax1.set_xlim(0,w-1)
    ax1.set_ylim(h-1,0)
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')

    plot_paper_fig = False

    if plot_paper_fig:
        # create an image shown in paper
        fig1p = plt.figure(figsize=(7,6.7), dpi=150)
        ax1p = fig1p.add_axes([0.13, 0.10, 0.85, 0.87])
        ax1m = fig1p.add_axes([0.53, 0.10, 0.45, 0.45])
        ax1p.imshow(logdata,cmap='gray',interpolation='none')
        ax1m.imshow(logdata,cmap='gray',interpolation='none', vmin=0.9, vmax=2.2)
        ax1p.imshow(sat_mask, interpolation='none',cmap=sat_cmap)

        fig2p = plt.figure(figsize=(7,4), dpi=150)
        ax2p = fig2p.add_axes([0.13, 0.16, 0.84, 0.80])


    # define a scroll function, which is used for mouse manipulation on pop-up
    # window
    def on_scroll(event):
        if event.inaxes == ax1:
            x1, x2 = ax1.get_xlim()
            y1, y2 = ax1.get_ylim()
            x1 = event.xdata - (1-event.step*0.1)*(event.xdata - x1)
            x2 = event.xdata + (1-event.step*0.1)*(x2 - event.xdata)
            y1 = event.ydata - (1-event.step*0.1)*(event.ydata - y1)
            y2 = event.ydata + (1-event.step*0.1)*(y2 - event.ydata)
            ax1.set_xlim(x1, x2)
            ax1.set_ylim(y1, y2)
            fig.canvas.draw()
    if filename is not None:
        fig.suptitle('Trace for %s'%os.path.basename(filename))
    fig.canvas.mpl_connect('scroll_event',on_scroll)
    fig.canvas.draw()
    if display:
        plt.show(block=False)

    x0 = w//2
    x_lst = {-1:[], 1:[]}
    x1 = x0
    direction = -1
    density = 10
    icol = 0
    peak_lst = []

    # the starting and ending index of stacked cross-section
    # eg. if h = 1000. then from -500 to 1500
    # so 0-th index in stacked cross-section corresponds to "csec_i1" in the
    # image coordinate
    csec_i1 = -h//2
    csec_i2 = h + h//2

    csec_lst    = np.zeros(csec_i2 - csec_i1)
    csec_nlst   = np.zeros(csec_i2 - csec_i1, dtype=np.int32)
    csec_maxlst = np.zeros(csec_i2 - csec_i1)

    # two-direction slope and shift list
    slope_lst = {-1:[], 1:[]}
    shift_lst = {-1:[], 1:[]}
    nodes_lst = {}

    def fitfunc(p, interfunc, n):
        slope, shift, zoom = p
        return interfunc(np.arange(n)*slope+shift) + zoom
    def resfunc(p, interfunc, flux0, mask=None):
        res_lst = flux0 - fitfunc(p, interfunc, flux0.size)
        if mask is None:
            mask = np.ones_like(flux0, dtype=np.bool)
        return res_lst[mask]
    def find_shift(flux0, flux1):
        p0 = [1.0, 0.0, 0.0]
        interfunc = intp.InterpolatedUnivariateSpline(
                    np.arange(flux1.size), flux1, k=3)
        mask = np.ones_like(flux0, dtype=np.bool)
        clipping = 5.
        for i in range(10):
            p, _ = opt.leastsq(resfunc, p0, args=(interfunc, flux0, mask))
            res_lst = resfunc(p, interfunc, flux0)
            mean = res_lst.mean()
            std  = res_lst.std()
            new_mask = (res_lst < mean + clipping*std)*(res_lst > mean - clipping*std)
            if new_mask.sum() == mask.sum():
                break
            mask = new_mask
        return p, mask

    def find_local_peak(xdata, ydata, mask):

        if mask.sum()>=2:
            core = np.hanning(min(5, ydata.size))
            # length of core should not be smaller than length of ydata
            # otherwise the length of ydata after convolution is reduced
            ydata = np.convolve(ydata, core, mode='same')

        argmax = ydata.argmax()
        xmax = xdata[argmax]
        if argmax<2 or argmax>ydata.size-2:
            return xdata[xdata.size//2]
        coeff = np.polyfit(xdata[argmax-1:argmax+2], ydata[argmax-1:argmax+2],deg=2)
        a, b,c = coeff
        ypeak = -b/2/a
        return ypeak


    # generate a window list according to seperation and sep_der
    dense_y = np.linspace(0, h-1, (h-1)*density+1)
    seperation_lst = seperation + dense_y/1000.*sep_der
    seperation_lst = np.int32(np.round(seperation_lst))
    window = 2*seperation_lst*density+1

    # convolution core for the cross-sections. used to eliminate the "flat" tops
    # of the saturated orders
    core = np.hanning(int(seperation))
    core /= core.sum()

    message = ['Finding flat curves for "%s"'%filename,
                '   x    slope    offset    zoom']
    while(True):
        # scan the image along X axis starting from the middle column
        nodes_lst[x1] = []
        flux1 = logdata[:,x1]
        #linflux1 = data[:,x1]
        linflux1 = np.median(data[:,x1-2:x1+3], axis=1)
        #flux1 = sg.savgol_filter(flux1, window_length=5, polyorder=2)
        flux1 = np.convolve(flux1, core, mode='same')
        if icol == 0:
            # will be used when changing the direction
            flux1_center = flux1

        # find peaks with Y precision of 1./density pixels
        f = intp.InterpolatedUnivariateSpline(np.arange(flux1.size), flux1, k=3)
        flux2 = f(dense_y)
        imax, fmax = get_local_minima(-flux2, window=window)
        ymax = dense_y[imax]
        fmax = -fmax

        #message2 = ['Detected peaks for column %4d in "%s"'%(x1, filename),
        #           'Y']
        #for _y in ymax:
        #    message2.append('%8.3f'%_y)
        #logger.debug((os.linesep+' '*3).join(message2))

        if icol == 0:
            # the middle column
            for y,f in zip(ymax,fmax):
                peak_lst.append((y,f))
                nodes_lst[x1].append(y)
            # convert to the stacked cross-section coordinate
            i1 = 0 - csec_i1
            i2 = h - csec_i1
            # stack the linear flux to the stacked cross-section
            csec_lst[i1:i2] += linflux1
            csec_nlst[i1:i2] += 1
            csec_maxlst[i1:i2] = np.maximum(csec_maxlst[i1:i2],linflux1)
        else:
            # aperture alignment of each selected column, described by
            # (slope, shift)
            (slope, shift, zoom), mask = find_shift(flux0, flux1)
            message.append('%4d  %8.5f  %8.5f  %8.5f'%(x1, slope, shift, zoom))
            slope_lst[direction].append(slope)
            shift_lst[direction].append(shift)
            for y, f in zip(ymax, fmax):
                ystep = y
                for slope, shift in zip(slope_lst[direction][::-1],
                                        shift_lst[direction][::-1]):
                    ystep = (ystep - shift)/slope
                peak_lst.append((ystep,f))
                nodes_lst[x1].append(y)

            # find ysta & yend, the start and point pixel after aperture
            # alignment
            ysta, yend = 0., h-1.
            for slope, shift in zip(slope_lst[direction][::-1],
                                    shift_lst[direction][::-1]):
                ysta = (ysta - shift)/slope
                yend = (yend - shift)/slope
            # interplote the new csection, from ysta to yend
            ynew = np.linspace(ysta, yend, h)
            interfunc = intp.InterpolatedUnivariateSpline(ynew, linflux1, k=3)
            # find the starting and ending indices for the new csection
            ysta_int = int(round(ysta))
            yend_int = int(round(yend))
            fnew = interfunc(np.arange(ysta_int, yend_int+1))
            # stack the new cross-section into the stacked cross-section
            # first, conver to the stacked cross-section coordinate
            i1 = ysta_int - csec_i1
            i2 = yend_int + 1 - csec_i1
            # then, stack the cross-sections
            csec_lst[i1:i2] += fnew
            csec_nlst[i1:i2] += 1
            csec_maxlst[i1:i2] = np.maximum(csec_maxlst[i1:i2],fnew)
            # for debug purpose
            #ax2.plot(np.arange(ysta_int, yend_int+1), fnew, 'y-', alpha=0.2)

        nodes_lst[x1] = np.array(nodes_lst[x1])

        x1 += direction*scan_step
        if x1 <= 10:
        #if x1 <= scan_step:
            # turn to the other direction
            direction = +1
            x1 = x0 + direction*scan_step
            x_lst[direction].append(x1)
            flux0 = flux1_center
            icol += 1
            continue
        elif x1 >= w - 10:
        #elif x1 >= w - scan_step:
            # scan ends
            break
        else:
            x_lst[direction].append(x1)
            flux0 = flux1
            icol += 1
            continue

    logger.debug((os.linesep+' '*4).join(message))

    # filter the consecutive zero elements at the beginning and the end
    i_nonzero = np.nonzero(csec_nlst)[0]
    istart, iend = i_nonzero[0], i_nonzero[-1]
    csec_ylst = np.arange(csec_lst.size) + csec_i1
    # now csec_ylst starts from -h//2

    # set the zero elements to 1, preparing for the division
    csec_nlst = np.maximum(csec_nlst, 1)
    csec_lst /= csec_nlst
    # convolve csec_lst (optional)
    #smcore = np.hanning(seperation*2+1)
    #smcore /= smcore.sum()
    #csec_conv_lst = np.convolve(csec_lst, smcore, mode='same')


    # find aperture positions
    # first, generate a window list
    csec_seperation_lst = seperation + np.arange(csec_i1, csec_i2)/1000.*sep_der
    csec_seperation_lst = np.int32(np.round(csec_seperation_lst))
    csec_win = 2*csec_seperation_lst + 1
    # detect peaks in stacked cross-sections
    peaky, _ = get_local_minima(-csec_lst[istart:iend],
                                window=csec_win[istart:iend])
    # convert back to stacked cross-section coordinate
    peaky += istart

    message = ['Detected peaks in stacked cross-section for "%s"'%filename,
               'peak  window']
    for _peak in peaky:
        message.append('%4d %4d'%(_peak + csec_i1, csec_win[_peak]))
    logger.debug((os.linesep+' '*3).join(message))

    ax2.plot(csec_ylst[istart:iend], csec_lst[istart:iend], '-', color='C0')
    ax2.set_yscale('log')
    ax2.set_xlabel('Y')
    ax2.set_ylabel('Count')
    ax2.set_xlim(csec_ylst[istart], csec_ylst[iend])

    if plot_paper_fig:
        # plot the stacked cross-section in paper figure
        ax2p.plot(csec_ylst[istart:iend], csec_lst[istart:iend], '-', color='C0', lw=1)

    #for x1,y_lst in nodes_lst.items():
    #    ax1.scatter(np.repeat(x1, y_lst.size), y_lst, c='b', s=5, lw=0)

    # parse peaks
    # cutx, cuty, cutn are the stacked peak list
    peak_lst = np.array(peak_lst)
    peak_ylst = peak_lst[:,0]
    peak_flst = peak_lst[:,1]
    peak_yintlst = np.int32(np.round(peak_ylst))
    cutf = np.zeros_like(csec_lst)
    cutn = np.zeros_like(csec_lst, dtype=np.int32)
    for y,f in zip(peak_yintlst,peak_flst):
        cutn[y-csec_i1] += 1
        cutf[y-csec_i1] += f
        # for debug purpose
        #ax2.axvline(csec_ylst[y-csec_i1], color='y', ls='--', alpha=0.2)
    # remove those element equal to one
    onemask = cutn == 1
    cutf[onemask] = 0
    cutn[onemask] = 0
    cuty = np.arange(cutn.size) + csec_i1

    #ax2.plot(cuty[istart:iend], cutn[istart:iend],'r-',alpha=1.)
    ax2.fill_between(cuty[istart:iend], cutn[istart:iend],step='mid',color='C1')
    if plot_paper_fig:
        # plot stacked peaks with yello in paper figure
        ax2p.fill_between(cuty[istart:iend], cutn[istart:iend],step='mid',color='C1')

    # find central positions along Y axis for all apertures
    message = ['Aperture Detection Information for "%s"'%filename,
               'y, ymax, i1, i2, n, n_xsec, select?, peak']
    mid_lst = []
    for y in peaky:
        f = csec_lst[y]
        # find the local seperation
        sep = csec_seperation_lst[y]
        # search for the maximum value of cutn around y
        i1, i2 = y-int(sep/2), y+int(sep/2)
        ymax = cutn[i1:i2].argmax() + i1

        #i1, i2 = ymax, ymax
        #while(cutn[i1]>0):
        #    i1 -= 1
        #while(cutn[i2]>0):
        #    i2 += 1
        #ii1 = max(i1,ymax-int(sep/2))
        #ii2 = min(i2,ymax+int(sep/2))

        ii1 = y-int(sep/3)
        ii2 = y+int(sep/3)
        n = cutn[ii1:ii2].sum()

        if n > csec_nlst[y]*filling:
            mid_lst.append(csec_ylst[y])
            select = 'yes'
        else:
            select = 'no'

        # debug information in running log
        info = {
                    'y'     : csec_ylst[y],
                    'ymax'  : csec_ylst[ymax],
                    'i1'    : csec_ylst[ii1],
                    'i2'    : csec_ylst[ii2],
                    'n'     : n,
                    'n_xsec': csec_nlst[y],
                    'select': select,
                    'peak'  : csec_ylst[y],
                }

        message.append(
            '{y:5d} {ymax:5d} {i1:5d} {i2:5d} {n:4d} {n_xsec:4d} {select:>5s} {peak:5d}'.format(**info)
            )

        # for debug purpose
        #ax2.axvline(csec_ylst[y], color='k', ls='--')

    # write debug information
    logger.debug((os.linesep+' '*4).join(message))

    # check the first and last peak. If the seperation is larger than 2x of 
    # the local seperation, remove them
    # check the last peak
    while(len(mid_lst)>3):
        sep = seperation + mid_lst[-1]*sep_der/1000.
        if mid_lst[-1] - mid_lst[-2] > 2*sep:
            logger.info('Remove the last aperture at %d for "%s" (distance=%d > 2 x %d)'%(
                        mid_lst[-1], filename, mid_lst[-1]-mid_lst[-2], sep))
            mid_lst.pop(-1)
        else:
            break

    # check the first peak
    while(len(mid_lst)>3):
        sep = seperation + mid_lst[0]*sep_der/1000.
        print(sep, mid_lst[0], mid_lst[1])
        if mid_lst[1] - mid_lst[0] > 2*sep:
            logger.info('Remove the first aperture at %d for "%s" (distance=%d > 2 x %d)'%(
                        mid_lst[0], filename, mid_lst[1]-mid_lst[0], sep))
            mid_lst.pop(0)
        else:
            break


    # plot the aperture positions
    f1, f2 = ax2.get_ylim()
    for mid in mid_lst:
        f = csec_lst[mid-csec_i1]
        ax2.plot([mid, mid], [f*(f2/f1)**0.01, f*(f2/f1)**0.03], 'k-', alpha=1)
        if plot_paper_fig:
            ax2p.plot([mid, mid], [f*(f2/f1)**0.01, f*(f2/f1)**0.03], 'k-', alpha=1, lw=1)

    # set tickers for ax2
    ax2.xaxis.set_major_locator(tck.MultipleLocator(500))
    ax2.xaxis.set_minor_locator(tck.MultipleLocator(100))


    aperture_set = ApertureSet(shape=(h,w))

    # generate a 2-D mesh grid
    yy, xx = np.mgrid[:h:,:w:]

    for aperture, mid in enumerate(mid_lst):
        xfit, yfit = [x0], [mid]
        for direction in [-1,1]:
            ystep = mid
            for ix, (slope, shift) in enumerate(zip(slope_lst[direction],
                                                    shift_lst[direction])):
                # use (slope, shift) as nodes for polynomial
                ystep = ystep*slope + shift
                x1 = x_lst[direction][ix]
                y_lst = nodes_lst[x1]
                # now ystep is the calculated approximate position of peak along
                # column x1
                option = 2
                # option 1: use (x1, ystep)
                # option 2: find peak by parabola fitting of the 3 points near
                #           the maximum pixel
                # option 3: use the closet point in y_lst as nodes
                if option == 1:
                    xfit.append(x1)
                    yfit.append(ystep)
                elif option == 2:
                    local_sep = ystep/1000*sep_der + seperation
                    y1 = max(0, int(ystep-local_sep/2))
                    y2 = min(h, int(ystep+local_sep/2))
                    if y2 - y1 <= 5:
                        # number of points is not enough to get a local peak
                        continue
                    xdata = np.arange(y1, y2)
                    ydata = data[y1:y2, x1]
                    m = sat_mask[y1:y2, x1]
                    ypeak = find_local_peak(xdata, ydata, m)
                    xfit.append(x1)
                    yfit.append(ypeak)
                elif option == 3:
                    diff = np.abs(y_lst - ystep)
                    dmin = diff.min()
                    imin = diff.argmin()
                    if dmin < 2:
                        xfit.append(x1)
                        yfit.append(y_lst[imin])
                else:
                    xfit.append(x1)
                    yfit.append(ystep)

        # sort xfit and yfit
        xfit, yfit = np.array(xfit), np.array(yfit)
        argsort = xfit.argsort()
        xfit, yfit = xfit[argsort], yfit[argsort]
        #ax1.plot(xfit, yfit, 'ro-',lw=0.5,alpha=0.6)

        # fit chebyshev polynomial
        # determine the left and right domain
        if xfit[0] <= scan_step + 10:
            left_domain = 0
        else:
            left_domain = xfit[0] - scan_step

        if xfit[-1] >= w - scan_step - 10:
            right_domain = w-1
        else:
            right_domain = xfit[-1] + scan_step

        domain = (left_domain, right_domain)

        poly = Chebyshev.fit(xfit, yfit, domain=domain, deg=3)

        # generate a curve using for plot
        newx, newy = poly.linspace()
        ax1.plot(newx, newy, '-',lw=0.8, alpha=1, color='C0')

        if plot_paper_fig:
            # plot the order in paper figure and the mini-figure
            ax1p.plot(newx, newy, '-',lw=0.7, alpha=1, color='C0')
            ax1m.plot(newx, newy, '-',lw=1.0, alpha=1, color='C0')

        # initialize aperture position instance
        aperture_loc = ApertureLocation(direct='x', shape=(h,w))
        aperture_loc.set_position(poly)

        # generate a curve using for find saturation pixels
        center_line = aperture_loc.position(np.arange(w))

        # find approximate lower and upper boundaries of this order
        lower_bound = center_line - 3
        upper_bound = center_line + 3

        aperture_mask = (yy > lower_bound)*(yy < upper_bound)
        # find saturation mask
        aperture_sat = (np.int16(sat_mask)*aperture_mask).sum(axis=0)
        # find 1d mask of saturation pixels for this aperture
        sat_mask_1d = aperture_sat > 0
        # find how many saturated pixels in this aperture
        nsat = sat_mask_1d.sum()
        aperture_loc.nsat = nsat

        # get peak flux for this flat
        peak_flux = (data*aperture_mask).max(axis=0)

        aperture_loc.mean   = peak_flux.mean()
        aperture_loc.median = np.median(peak_flux)
        aperture_loc.max    = peak_flux.max()

        aperture_set[aperture] = aperture_loc

    # write the order set into ascii and reg file
    if trace_file is not None:
        aperture_set.save_txt(trace_file)
    if reg_file is not None:
        aperture_set.save_reg(reg_file)

    fig.canvas.draw()
    if fig_file is not None:
        fig.savefig(fig_file)
    
    if plot_paper_fig:
        # adjust figure 1 in paper
        ax1p.xaxis.set_major_locator(tck.MultipleLocator(500))
        ax1p.xaxis.set_minor_locator(tck.MultipleLocator(100))
        ax1p.yaxis.set_major_locator(tck.MultipleLocator(500))
        ax1p.yaxis.set_minor_locator(tck.MultipleLocator(100))
        for tick in ax1p.xaxis.get_major_ticks():
            tick.label1.set_fontsize(13)
        for tick in ax1p.yaxis.get_major_ticks():
            tick.label1.set_fontsize(13)
        ax1p.set_xlim(0,w-1)
        ax1p.set_ylim(h-1,0)
        ax1p.set_xlabel('X', fontsize=18)
        ax1p.set_ylabel('Y', fontsize=18)
        ax1m.set_xlim(1600, w-1)
        ax1m.set_ylim(h-1, 1600)
        ax1m.set_xticks([])
        ax1m.set_yticks([])
        fig1p.savefig(fig_file+'.pdf')

        # adjust figure 2 in paper
        ax2p.xaxis.set_major_locator(tck.MultipleLocator(500))
        ax2p.xaxis.set_minor_locator(tck.MultipleLocator(100))
        for tick in ax2p.xaxis.get_major_ticks():
            tick.label1.set_fontsize(13)
        for tick in ax2p.yaxis.get_major_ticks():
            tick.label1.set_fontsize(13)
        ax2p.set_yscale('log')
        ax2p.set_xlabel('Y', fontsize=18)
        ax2p.set_ylabel('Count', fontsize=18)
        ax2p.set_xlim(csec_ylst[istart], csec_ylst[iend])
        fig2p.savefig(fig_file+'_2.pdf')
        plt.close(fig1p)
        plt.close(fig2p)

    # for debug purpose
    #ax2.set_xlim(3400, 3500)
    #ax2.xaxis.set_major_locator(tck.MultipleLocator(100))
    #ax2.xaxis.set_minor_locator(tck.MultipleLocator(10))
    #fig.savefig(fig_file[0:-4]+'-debug.png')

    plt.close(fig)

    # plot the order seperation information
    # for debug purpose
    fig2 = plt.figure(dpi=150)
    ax2 = fig2.gca()
    center_lst = [aper_loc.get_center()
                  for aper, aper_loc in sorted(aperture_set.items())]
    ax2.plot(center_lst, derivative(center_lst), 'bo', alpha=0.6)
    ax2.plot(np.arange(h), np.arange(h)/1000*sep_der+seperation, 'r-')
    ax2.set_xlim(0, h-1)
    if fig_file is not None:
        fig2.savefig(fig_file[0:-4]+'-order_sep.png')
    plt.close(fig2)

    return aperture_set

def load_aperture_set(filename):
    '''
    Reads an ApertureSet instance from an Ascii file.

    Args:
        filename (string): Name of the ASCII file.
    Returns:
        :class:`ApertureSet`: An :class:`ApertureSet` instance.
    '''

    aperture_set = ApertureSet()

    magic = 'APERTURE LOCATION'

    # read input file
    infile = open(filename)
    aperture = None
    for row in infile:
        row = row.strip()
        if len(row)==0 or row[0] in '#!;':
            continue
        elif len(row)>len(magic) and row[0:len(magic)]==magic:
            aperture = int(row[len(magic):])
            aperture_set[aperture] = ApertureLocation()
        elif aperture is not None and '=' in row:
            g = row.split('=')
            key   = g[0].strip()
            value = g[1].strip()
            if key == 'position':
                value = eval(value)
                aperture_loc = aperture_set[aperture]
                n = aperture_loc.shape[aperture_loc.direct]
                poly = Chebyshev(coef=value, domain=[0, n-1])
                aperture_loc.set_position(poly)
            elif key == 'domain':
                aperture_loc.position.domain = eval(value)
            else:
                setattr(aperture_set[aperture], key, eval(value))
    infile.close()

    return aperture_set

def load_aperture_set_from_header(header, channel=None):
    prefix = 'EDRS TRACE'
    if channel is not None:
        prefix += ' CHANNEL %s'%channel
    
    aperture_set = ApertureSet()
    coeff = []
    prev_aper = None
    has_aperture = False
    for key, value in header.items():
        if key[0:len(prefix)] == prefix:
            has_aperture = True
            g = key[len(prefix):].strip().split()
            aperture = int(g[1])
            if prev_aper is not None and aperture != prev_aper:
                # at the end of aperture
                aperture_set[prev_aper] = ApertureLocation(
                                            direct = direct,
                                            shape  = shape,
                                            )
                poly = Chebyshev(coef=coeff, domain=domain)
                aperture_set[prev_aper].set_position(poly)
                aperture_set[prev_aper].nsat   = nsat
                aperture_set[prev_aper].mean   = mean
                aperture_set[prev_aper].median = median
                aperture_set[prev_aper].max    = maxv
                # reset parameters
                coeff = []
            if g[2] == 'COEFF':
                coeff.append(value)
            elif g[2] == 'DIRECT':
                direct = value
            elif g[2] == 'SHAPE':
                shape = eval(value)
            elif g[2] == 'SHAPE0':
                shape0 = value
            elif g[2] == 'SHAPE1':
                shape1 = value
                shape = (shape0, shape1)
            elif g[2] == 'DOMAIN':
                domain = eval(value)
            elif g[2] == 'DOMAIN0':
                domain0 = value
            elif g[2] == 'DOMAIN1':
                domain1 = value
                domain = (domain0, domain1)
            elif g[2] == 'NSAT':
                nsat = value
            elif g[2] == 'MEAN':
                mean = value
            elif g[2] == 'MEDIAN':
                median = value
            elif g[2] == 'MAX':
                maxv = value
            else:
                pass
            prev_aper = aperture

    # pack the last aperture
    if has_aperture:
        aperture_set[aperture] = ApertureLocation(direct=direct, shape=shape)
        poly = Chebyshev(coef=coeff, domain=domain)
        aperture_set[aperture].set_position(poly)
        aperture_set[prev_aper].nsat   = nsat
        aperture_set[prev_aper].mean   = mean
        aperture_set[prev_aper].median = median
        aperture_set[prev_aper].max    = maxv

    return aperture_set



def gaussian_bkg(A, center, fwhm, bkg, x):
    '''Gaussian + background function.

    Args:
        A (float):
        center (float):
        fwhm (float):
        bkg (float):
        x (float or :class:`numpy.array`):
    Returns:
        :class:`numpy.array`: Output function values.
        
    '''
    s = fwhm/2./math.sqrt(2*math.log(2))
    return A*np.exp(-(x-center)**2/2./s**2) + bkg

def errfunc(p, x, y, fitfunc):
    '''Error function used in fitting.
    '''
    return y - fitfunc(p, x)

def fitfunc(p, x):
    '''Fitting function used in the least-square fitting.
    Args:
        p (list):
    '''
    return gaussian_bkg(p[0], p[1], p[2], p[3], x)

