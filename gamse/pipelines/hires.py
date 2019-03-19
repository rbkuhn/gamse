import os
import re
import logging
logger = logging.getLogger(__name__)
import configparser

import numpy as np
from scipy.ndimage.filters import gaussian_filter
import astropy.io.fits as fits
from astropy.io import registry as io_registry
from astropy.table import Table
from astropy.time  import Time

from ..echelle.imageproc import combine_images
from ..utils.obslog import read_obslog
from ..utils import obslog
from .common import FormattedInfo

all_columns = [
        ('frameid',  'int',   '{:^7s}',  '{0[frameid]:7d}'),
        ('fileid',   'str',   '{:^17s}', '{0[fileid]:17s}'),
        ('imgtype',  'str',   '{:^7s}',  '{0[imgtype]:^7s}'),
        ('object',   'str',   '{:^20s}', '{0[object]:20s}'),
        ('i2cell',   'bool',  '{:^6s}',  '{0[i2cell]!s: <6}'),
        ('exptime',  'float', '{:^7s}',  '{0[exptime]:7g}'),
        ('obsdate',  'time',  '{:^23s}', '{0[obsdate]:}'),
        ('deckname', 'str',   '{:^8s}',  '{0[deckname]:^8s}'),
        ('filter1',  'str',   '{:^7s}',  '{0[filter1]:^7s}'),
        ('filter2',  'str',   '{:^7s}',  '{0[filter2]:^7s}'),
        ('nsat_1',   'int',   '{:^8s}',  '{0[nsat_1]:8d}'),
        ('nsat_2',   'int',   '{:^8s}',  '{0[nsat_2]:8d}'),
        ('nsat_3',   'int',   '{:^8s}',  '{0[nsat_3]:8d}'),
        ('q95_1',    'int',   '{:^8s}',  '{0[q95_1]:8d}'),
        ('q95_2',    'int',   '{:^8s}',  '{0[q95_2]:8d}'),
        ('q95_3',    'int',   '{:^8s}',  '{0[q95_3]:8d}'),
        ]

def get_datasection(hdu_lst):
    """Get data section
    """
    # get bin
    tmp = hdu_lst[0].header['CCDSUM'].split()
    binx, biny = int(tmp[0]), int(tmp[1])
    dataset_lst = {(2, 1): ('[7:1030,1:4096]', (6, 1024), (0, 4096)),
                   (2, 2): ('[7:1030,1:2048]', (6, 1024), (0, 2048)),
                   }
    datasec, (x1, x2), (y1, y2) = dataset_lst[(binx, biny)]
    data_lst = (hdu_lst[i+1].data[y1:y2, x1:x2] for i in range(3)
                if hdu_lst[i+1].header['DATASEC']==datasec)
    return data_lst

def make_obslog(path):
    """Scan the raw data, and generated a log file containing the detail
    information for each frame.

    An ascii file will be generated after running. The name of the ascii file is
    `YYYY-MM-DD.log`.

    Args:
        path (str): Path to the raw FITS files.

    """
    name_pattern = '^HI\.\d{8}\.\d{5}\.fits$'

    # scan the raw files
    fname_lst = sorted(os.listdir(path))

    # prepare logtable
    logtable = Table(dtype=[
        ('frameid', 'i2'),   ('fileid', 'S17'),   ('imgtype', 'S3'),
        ('object',  'S20'),  ('i2cell', 'bool'),  ('exptime', 'f4'),
        ('obsdate',  Time),
        ('deckname', 'S2'),  ('filter1', 'S5'),   ('filter2', 'S5'),
        ('nsat_1',   'i4'),  ('nsat_2',  'i4'),   ('nsat_3',  'i4'),
        ('q95_1',    'i4'),  ('q95_2',   'i4'),   ('q95_3',   'i4'),
        ])

    # prepare infomation to print
    pinfo = FormattedInfo(all_columns,
            ['frameid', 'fileid', 'imgtype', 'object', 'i2cell', 'exptime',
            'obsdate', 'deckname', 'nsat_2', 'q95_2'])

    print(pinfo.get_title())
    print(pinfo.get_separator())

    # start scanning the raw files
    prev_frameid = -1
    for fname in fname_lst:
        if not re.match(name_pattern, fname):
            continue
        fileid = fname[0:17]
        filename = os.path.join(path, fname)
        hdu_lst = fits.open(filename)
        head0 = hdu_lst[0].header

        frameid = prev_frameid + 1

        # get obsdate in 'YYYY-MM-DDTHH:MM:SS' format
        date = head0.get('DATE-OBS')
        utc  = head0.get('UTC', head0.get('UT'))
        obsdate = Time('%sT%s'%(date, utc))

        exptime    = head0.get('ELAPTIME')
        i2in       = head0.get('IODIN', False)
        i2out      = head0.get('IODOUT', True)
        i2cell     = i2in
        imagetyp   = head0.get('IMAGETYP')
        targname   = head0.get('TARGNAME', '')
        lampname   = head0.get('LAMPNAME', '')

        if imagetyp == 'object':
            # science frame
            imgtype    = 'sci'
            objectname = targname
        elif imagetyp == 'flatlamp':
            # flat
            imgtype    = 'cal'
            objectname = '{} ({})'.format(imagetyp, lampname)
        elif imagetyp == 'arclamp':
            # arc lamp
            imgtype    = 'cal'
            objectname = '{} ({})'.format(imagetyp, lampname)
        elif imagetyp == 'bias':
            imgtype    = 'cal'
            objectname = 'bias'
        else:
            print('Unknown IMAGETYP:', imagetyp)


        # get deck and filter information
        deckname = head0.get('DECKNAME', '')
        filter1  = head0.get('FIL1NAME', '')
        filter2  = head0.get('FIL2NAME', '')

        data1, data2, data3 = get_datasection(hdu_lst)

        # determine the total number of saturated pixels
        nsat_1 = (data1==0).sum()
        nsat_2 = (data2==0).sum()
        nsat_3 = (data3==0).sum()

        # find the 95% quantile
        q95_1 = np.sort(data1.flatten())[int(data1.size*0.95)]
        q95_2 = np.sort(data2.flatten())[int(data2.size*0.95)]
        q95_3 = np.sort(data3.flatten())[int(data3.size*0.95)]

        hdu_lst.close()

        item = [frameid, fileid, imgtype, objectname, i2cell, exptime, obsdate,
                deckname, filter1, filter2,
                nsat_1, nsat_2, nsat_3, q95_1, q95_2, q95_3]

        logtable.add_row(item)
        # get table Row object. (not elegant!)
        item = logtable[-1]

        print(pinfo.get_format().format(item))

        prev_frameid = frameid

    print(pinfo.get_separator())

    # sort by obsdate
    #logtable.sort('obsdate')

    # determine filename of logtable.
    # use the obsdate of the LAST frame.
    obsdate = logtable[-1]['obsdate'].iso[0:10]
    outname = '{}.obslog'.format(obsdate)
    if os.path.exists(outname):
        i = 0
        while(True):
            i += 1
            outname = '{}.{}.obslog'.format(obsdate, i)
            if not os.path.exists(outname):
                outfilename = outname
                break
    else:
        outfilename = outname

    # save the logtable
    loginfo = FormattedInfo(all_columns)
    outfile = open(outfilename, 'w')
    outfile.write(loginfo.get_title()+os.linesep)
    outfile.write(loginfo.get_dtype()+os.linesep)
    outfile.write(loginfo.get_separator()+os.linesep)
    for row in logtable:
        outfile.write(loginfo.get_format().format(row)+os.linesep)
    outfile.close()


def reduce():
    """2D to 1D pipeline for Keck/HIRES
    """

    # find obs log
    logname_lst = [fname for fname in os.listdir(os.curdir)
                        if fname[-7:]=='.obslog']
    if len(logname_lst)==0:
        print('No observation log found')
        exit()
    elif len(logname_lst)>1:
        print('Multiple observation log found:')
        for logname in sorted(logname_lst):
            print('  '+logname)
    else:
        pass

    # read obs log
    io_registry.register_reader('obslog', Table, read_obslog)
    logtable = Table.read(logname_lst[0], format='obslog')

    # load config files
    config_file_lst = []
    # find built-in config file
    config_path = os.path.join(os.path.dirname(__file__), '../data/config')
    config_file = os.path.join(config_path, 'HIRES.cfg')
    if os.path.exists(config_file):
        config_file_lst.append(config_file)

    # find local config file
    for fname in os.listdir(os.curdir):
        if fname[-4:]=='.cfg':
            config_file_lst.append(fname)

    # load both built-in and local config files
    config = configparser.ConfigParser(
                inline_comment_prefixes = (';','#'),
                interpolation           = configparser.ExtendedInterpolation(),
                )
    config.read(config_file_lst)

    # extract keywords from config file
    section     = config['data']
    rawdata     = section.get('rawdata')
    statime_key = section.get('statime_key')
    exptime_key = section.get('exptime_key')
    section     = config['reduce']
    midproc     = section.get('midproc')
    result      = section.get('result')
    report      = section.get('report')
    mode        = section.get('mode')
    fig_format = section.get('fig_format')

    # create folders if not exist
    if not os.path.exists(report):  os.mkdir(report)
    if not os.path.exists(result):  os.mkdir(result)
    if not os.path.exists(midproc): os.mkdir(midproc)

    # initialize printing infomation
    pinfo1 = PrintInfo(print_columns)

    nccd = 3

    ################################ parse bias ################################
    section = config['reduce.bias']
    bias_file = section['bias_file']

    if os.path.exists(bias_file):
        has_bias = True
        # load bias data from existing file
        hdu_lst = fits.open(bias_file)
        bias = [hdu_lst[iccd+1].data for iccd in range(nccd)]
        hdu_lst.close()
        message = 'Load bias from image: {}'.format(bias_file)
        logger.info(message)
        print(message)
    else:
        # read each individual CCD
        bias_data_lst = [[] for iccd in range(nccd)]

        for logitem in logtable:
            if logitem['object'].strip().lower()=='bias':
                filename = os.path.join(rawdata, logitem['fileid']+'.fits')
                hdu_lst = fits.open(filename)

                # print info
                if len(bias_data_lst[0]) == 0:
                    print('* Combine Bias Images: {}'.format(bias_file))
                    print(' '*2 + pinfo1.get_title())
                    print(' '*2 + pinfo1.get_separator())
                print(' '*2 + pinfo1.get_format().format(logitem))

                for iccd in range(nccd):
                    data = hdu_lst[iccd+1].data
                    bias_data_lst[iccd].append(data)
                hdu_lst.close()

        n_bias = len(bias_data_lst[0])      # number of bias images
        has_bias = n_bias > 0

        if has_bias:
            # there is bias frames
            print(' '*2 + pinfo1.get_separator())

            bias = []
            hdu_lst = fits.HDUList([fits.PrimaryHDU()])  # the final HDU list

            # scan for each ccd
            for iccd in range(nccd):
                ### 3 CCDs loop begins here ###
                bias_data_lst[iccd] = np.array(bias_data_lst[iccd])

                sub_bias = combine_images(bias_data_lst[iccd],
                           mode       = 'mean',
                           upper_clip = section.getfloat('cosmic_clip'),
                           maxiter    = section.getint('maxiter'),
                           mask       = (None, 'max')[n_bias>=3],
                           )

                head = fits.Header()
                head['HIERARCH GAMSE BIAS NFILE'] = n_bias

                ############## bias smooth ##################
                if section.getboolean('smooth'):
                    # bias needs to be smoothed
                    smooth_method = section.get('smooth_method')

                    h, w = sub_bias.shape
                    if smooth_method in ['gauss','gaussian']:
                        # perform 2D gaussian smoothing
                        smooth_sigma = section.getint('smooth_sigma')
                        smooth_mode  = section.get('smooth_mode')
                        
                        bias_smooth = gaussian_filter(sub_bias,
                                        sigma=smooth_sigma, mode=smooth_mode)

                        # write information to FITS header
                        head['HIERARCH EDRS BIAS SMOOTH']        = True
                        head['HIERARCH EDRS BIAS SMOOTH METHOD'] = 'GAUSSIAN'
                        head['HIERARCH EDRS BIAS SMOOTH SIGMA']  = smooth_sigma
                        head['HIERARCH EDRS BIAS SMOOTH MODE']   = smooth_mode
                    else:
                        print('Unknown smooth method: ', smooth_method)
                        pass

                    sub_bias = bias_smooth
                else:
                    # bias not smoothed
                    head['HIERARCH GAMSE BIAS SMOOTH'] = False

                bias.append(sub_bias)
                hdu_lst.append(fits.ImageHDU(data=sub_bias, header=head))
                ### 3 CCDs loop ends here ##

            hdu_lst.writeto(bias_file, overwrite=True)

        else:
            # no bias found
            pass

    ########################## find flat groups #########################

    print('*'*10 + 'Parsing Flat Fieldings' + '*'*10)
    # initialize flat_groups
    flat_groups = {}
    # flat_groups = {'flat_M': [fileid1, fileid2, ...],
    #                'flat_N': [fileid1, fileid2, ...]}
