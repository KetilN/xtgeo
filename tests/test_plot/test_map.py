import os
import sys
import logging
import pytest
import matplotlib.pyplot as plt

from xtgeo.plot import Map
from xtgeo.surface import RegularSurface
from xtgeo.xyz import Polygons
from xtgeo.common import XTGeoDialog

xtg = XTGeoDialog()
logger = xtg.basiclogger(__name__)

if not xtg.testsetup():
    sys.exit(-9)

td = xtg.tmpdir
testpath = xtg.testpath

skiplargetest = pytest.mark.skipif(xtg.bigtest is False,
                                   reason="Big tests skip")

# =========================================================================
# Do tests
# =========================================================================


def test_very_basic_to_file():
    """Just test that matplotlib works, to a file."""
    plt.title('Hello world')
    plt.savefig('TMP/verysimple.png')


def test_simple_plot():
    """Test as simple map plot only making an instance++ and plot."""

    mysurf = RegularSurface()
    mysurf.from_file('../xtgeo-testdata/surfaces/gfb/1/'
                     'gullfaks_top.irapbin')

    # just make the instance, with a lot of defaults behind the scene
    myplot = Map()
    myplot.canvas(title='My o my')
    myplot.set_colortable('gist_ncar')
    myplot.plot_surface(mysurf)

    myplot.savefig('TMP/map_simple.png')


def test_more_features_plot():
    """Map with some more features added, such as label rotation."""

    mysurf = RegularSurface()
    mysurf.from_file('../xtgeo-testdata/surfaces/gfb/1/'
                     'gullfaks_top.irapbin')

    myfaults = Polygons('../xtgeo-testdata/polygons/gfb/'
                        'faults_zone10.zmap', fformat='zmap')

    # just make the instance, with a lot of defaults behind the scene
    myplot = Map()
    myplot.canvas(title='Label rotation')
    myplot.set_colortable('gist_rainbow_r')
    myplot.plot_surface(mysurf, minvalue=1250, maxvalue=2200,
                        xlabelrotation=45)

    myplot.plot_faults(myfaults)

    myplot.savefig(td + '/map_more1.png')


def test_perm_logarithmic_map():
    """Map with PERM, log scale."""

    mysurf = RegularSurface('../xtgeo-testdata/surfaces/reek/'
                            '1/reek_perm_lay1.gri')

    myplot = Map()
    myplot.canvas(title='PERMX normal scale')
    myplot.set_colortable('gist_rainbow_r')
    myplot.plot_surface(mysurf, minvalue=0, maxvalue=6000,
                        xlabelrotation=45, logarithmic=True)

    myplot.savefig(td + '/permx_normal.png')
