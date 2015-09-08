# -*- coding: utf-8 -*-
# ############# version ##################
from pkg_resources import get_distribution, DistributionNotFound
import os.path
import subprocess
try:
    _dist = get_distribution('hydrachain')
    # Normalize case for Windows systems
    dist_loc = os.path.normcase(_dist.location)
    here = os.path.normcase(__file__)
    if not here.startswith(os.path.join(dist_loc, 'hydrachain')):
        # not installed, but there is another version that *is*
        raise DistributionNotFound
except DistributionNotFound:
    __version__ = None
else:
    __version__ = _dist.version
if not __version__:
    try:
        # try to parse from setup.py
        for l in open(os.path.join(__path__[0], '..', 'setup.py')):
            if l.startswith("version = '"):
                __version__ = l.split("'")[1]
                break
    except:
        pass
    finally:
        if not __version__:
            __version__ = 'undefined'
    # add git revision and commit status
    try:
        rev = subprocess.check_output(['git', 'rev-parse', 'HEAD'])
        is_dirty = len(subprocess.check_output(['git', 'diff', '--shortstat']).strip())
        __version__ += '-' + rev[:4] + '-dirty' if is_dirty else ''
    except:
        pass
# ########### endversion ##################
