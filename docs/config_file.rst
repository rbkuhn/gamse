Configuration File
==================
`GAMSE` uses configuration files to control the input parameters and the
procedures performed during the data reduction.
A configuration file is a plain text file with the name of ``XXX.cfg``.
It follows the `RFC 822 <https://tools.ietf.org/html/rfc822.html>`_ format
and is similiar to ``.INI`` files in Microsoft Windows systems.
Briefly, it consists of a series of sections led by headers like ``[XXX]``, and
each section contains some entries like ``name: value`` or ``name=value``.
Comments prefixed by hash (``#``) or semicolons (``;``) symbols are supported,
for example:
::
    [data]
    telescope   = Fraunhofer
    instrument  = FOCES
    rawdata     = rawdata   # path to raw data
    statime_key = FRAME     # key of starting time of exposure in FITS header
    exptime_key = EXPOSURE  # key of exposure time in FITS header

    [reduce]
    midproc     = midproc   # path to mid process files
    report      = report    # path to reports
    result      = onedspec  # path to one dimensional spectra
    mode        = normal
    fig_format  = png

    [reduce.bias]
    bias_file     = ${reduce:midproc}/bias.fits
    cosmic_clip   = 10      # upper clip threshold
    maxiter       = 5       # maximum iteration number

    [reduce.trace]
    minimum    = 8
    scan_step  = 100
    separation = 500:26, 1500:15
    filling    = 0.3
    align_deg  = 2
    display    = no
    degree     = 3
    ... ...

``GAMSE`` includes built-in configuration files for some spectrographs.
Therefore, users do not have to find these values their own.
The above example is the content of the built-in configuration file for FOCES
spectrograph.

Sometimes, one may want to change the values of a few entries.
In these cases, users can create a new ``.cfg`` file in the working directory
and write these entries together with their section names in.
Only the entries in the new configuration files are overridden during the data
reduction.

For example, a user-created ``.cfg`` file with:
::
    [data]
    telescope   = Fraunhofer
    instrument  = FOCES
    rawdata     = rawdata

    [reduce]
    fig_format  = pdf

will only override the value of ``fig_format`` in the ``reduce`` section in the
built-in configuration files.
