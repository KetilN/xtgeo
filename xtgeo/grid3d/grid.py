# -*- coding: utf-8 -*-
"""Module/class for 3D grids with XTGeo."""

from __future__ import print_function, absolute_import

import sys
import inspect
import numpy as np

import errno
import os
import os.path
import logging

import cxtgeo.cxtgeo as _cxtgeo

import re
from tempfile import mkstemp
from xtgeo.common import XTGeoDialog

import xtgeo
from .grid3d import Grid3D
from .grid_property import GridProperty
from .grid_properties import GridProperties

from xtgeo.grid3d import _hybridgrid
from xtgeo.grid3d import _grid_export
from xtgeo.grid3d import _refinegrid


class Grid(Grid3D):
    """Class for a 3D grid geometry (corner point) with optionally props.

    I.e. the geometric grid cells and active cell indicator.

    The grid geometry class instances are normally created when
    importing a grid from file, as it is (currently) too complex to create from
    scratch.

    See also the :class:`.GridProperty` and the :class:`.GridProperties`
    classes.

    Example::

        geo = Grid()
        geo.from_file('myfile.roff')
        #
        # alternative (make instance directly from file):
        geo = Grid('myfile.roff')

    """

    def __init__(self, *args, **kwargs):

        self._xtg = XTGeoDialog()

        clsname = '{}.{}'.format(type(self).__module__, type(self).__name__)
        self.logger = self._xtg.functionlogger(clsname)

        self._ncol = 4
        self._nrow = 3
        self._nlay = 5
        self._nsubs = 0
        self._p_coord_v = None       # carray swig pointer to coords vector
        self._p_zcorn_v = None       # carray swig pointer to zcorns vector
        self._p_actnum_v = None      # carray swig pointer to actnum vector
        self._nactive = -999         # Number of active cells
        self._actnum_indices = None  # Index numpy array for active cells

        self._props = []  # List of 'attached' property objects

        # perhaps undef should be a class variable, not an instance variables?
        self._undef = _cxtgeo.UNDEF
        self._undef_limit = _cxtgeo.UNDEF_LIMIT

        if len(args) == 1:
            # make an instance directly through import of a file
            fformat = kwargs.get('fformat', 'guess')
            initprops = kwargs.get('initprops', None)
            restartprops = kwargs.get('restartprops', None)
            restartdates = kwargs.get('restartdates', None)
            self.from_file(args[0], fformat=fformat, initprops=initprops,
                           restartprops=restartprops,
                           restartdates=restartdates)

    # =========================================================================
    # Properties:
    # =========================================================================

    @property
    def nactive(self):
        """Returns the number of active cells."""
        return self._nactive

    @property
    def actnum_indices(self):
        """Returns the ndarray which holds the indices for active cells"""
        if self._actnum_indices is None:
            actnum = self.get_actnum()
            self._actnum_indices = np.flatnonzero(actnum.values)

        return self._actnum_indices

    @property
    def ntotal(self):
        """Returns the total number of cells."""
        return self._ncol * self._nrow * self._nlay

    @property
    def props(self):
        """Returns or sets a list of property objects.

        When setting, the dimension of the property object is checked,
        and will raise an IndexError if it does not match the grid.

        """
        return self._props

    @props.setter
    def props(self, list):
        for l in list:
            if l.ncol != self._ncol or l.nrow != self._nrow or\
               l.nlay != self._nlay:
                raise IndexError('Property NX NY NZ <{}> does not match grid!'
                                 .format(l.name))

        self._props = list

    @property
    def propnames(self):
        """Returns a list of property names that are hooked to a grid."""

        plist = []
        for obj in self._props:
            plist.append(obj.name)

        return plist

    @property
    def undef(self):
        """Get the undef value for floats or ints numpy arrays."""
        return self._undef

    @property
    def undef_limit(self):
        """Returns the undef limit number - slightly less than the undef value.

        Hence for numerical precision, one can force undef values
        to a given number, e.g.::

           x[x<x.undef_limit]=999

        Undef limit values cannot be changed.
        """

        return self._undef_limit

    # =========================================================================
    # Other setters and getters as _functions_
    # =========================================================================

    def get_prop_by_name(self, name):
        """Gets a property object by name lookup, return None if not present.
        """
        for obj in self.props:
            if obj.name == name:
                return obj

        return None

# =========================================================================
# Import and export
# =========================================================================

    def from_file(self, gfile,
                  fformat='guess',
                  initprops=None,
                  restartprops=None,
                  restartdates=None):

        """Import grid geometry from file, and makes an instance of this class.

        If file extension is missing, then the extension is guessed by fformat
        key, e.g. fformat egrid will be guessed if '.EGRID'. The 'eclipserun'
        will try to input INIT and UNRST file in addition the grid in 'one go'.

        Arguments:
            gfile (str): File name to be imported
            fformat (str): File format egrid/grid/roff/grdecl/eclipse_run
                (roff is default)
            initprops (str list): Optional, if given, and file format
                is 'eclipse_run', then list the names of the properties here.
            restartprops (str list): Optional, see initprops
            restartdates (int list): Optional, required if restartprops

        Example::

            >>> myfile = ../../testdata/Zone/gullfaks.roff
            >>> xg = Grid()
            >>> xg.from_file(myfile, fformat='roff')
            >>> # or shorter:
            >>> xg = Grid(myfile)  # will guess the file format

        Raises:
            OSError: if file is not found etc
        """

        fflist = ['egrid', 'grid', 'grdecl', 'roff', 'eclipserun', 'guess']
        if fformat not in fflist:
            raise ValueError('Invalid fformat: <{}>, options are {}'.
                             format(fformat, fflist))

        # work on file extension
        froot, fext = os.path.splitext(gfile)
        fext = fext.replace('.', '')
        fext = fext.lower()

        self.logger.info('Format is {}'.format(fformat))
        if fformat == 'guess':
            self.logger.info('Format is <guess>')
            fflist = ['egrid', 'grid', 'grdecl', 'roff', 'eclipserun']
            if fext and fext in fflist:
                fformat = fext

        if not fext:
            # file extension is missing, guess from format
            self.logger.info('File extension missing; guessing...')
            useext = ''
            if fformat == 'egrid':
                useext = '.EGRID'
            elif fformat == 'grid':
                useext = '.GRID'
            elif fformat == 'grdecl':
                useext = '.grdecl'
            elif fformat == 'roff':
                useext = '.roff'
            elif fformat == 'guess':
                raise ValueError('Cannot guess format without file extension')

            gfile = froot + useext

        self.logger.info('File name to be used is {}'.format(gfile))

        test_gfile = gfile
        if fformat == 'eclipserun':
            test_gfile = gfile + '.EGRID'

        if os.path.isfile(test_gfile):
            self.logger.info('File {} exists OK'.format(test_gfile))
        else:
            self.logger.critical('No such file: {}'.format(test_gfile))
            raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), gfile)

        if (fformat == 'roff'):
            self._import_roff(gfile)
        elif (fformat == 'grid'):
            self._import_ecl_output(gfile, 0)
        elif (fformat == 'egrid'):
            self._import_ecl_output(gfile, 2)
        elif (fformat == 'eclipserun'):
            self._import_ecl_run(gfile, initprops=initprops,
                                 restartprops=restartprops,
                                 restartdates=restartdates,
                                 )
        elif (fformat == 'grdecl'):
            self._import_ecl_grdecl(gfile)
        else:
            self.logger.warning('Invalid file format')
            sys.exit(1)

        return self

    def to_file(self, gfile, fformat='roff'):
        """
        Export grid geometry to file (roff binary supported).

        Example::

            g.to_file('myfile.roff')
        """

        if fformat == 'roff' or fformat == 'roff_binary':
            _grid_export.export_roff(self, gfile, 0)
        elif fformat == 'roff_ascii':
            _grid_export.export_roff(self, gfile, 1)
        elif fformat == 'grdecl':
            _grid_export.export_grdecl(self, gfile)

# =========================================================================
# Get some grid basics
# =========================================================================
    def get_cactnum(self):
        """
        Returns the C pointer to the ACTNUM array, to be used as input for
        reading INIT and RESTART.
        """
        return self._p_actnum_v  # the SWIG pointer to the C structure

    def get_indices(self, names=('I', 'J', 'K')):
        """Return 3 GridProperty objects for column, row, and layer index,

        Note that the indexes starts with 1, not zero (i.e. upper
        cell layer is K=1)

        Args:
            names (tuple): Names of the columns (as property names)

        Examples::

            i_index, j_index, k_index = grd.get_indices()

        """

        grd = np.indices((self.ncol, self.nrow, self.nlay))

        ilist = []
        for axis in range(3):
            index = grd[axis]
            index = index.flatten(order='F')
            index = index + 1
            index.astype(np.int32)

            idx = GridProperty(ncol=self._ncol, nrow=self._nrow,
                               nlay=self._nlay,
                               values=index,
                               name=names[axis], discrete=True)
            codes = {}
            ncodes = 0
            for i in range(index.min(), index.max() + 1):
                codes[i] = str(i)
                ncodes = ncodes + 1

            idx._codes = codes
            idx._ncodes = ncodes
            idx._grid = self
            ilist.append(idx)

        return ilist

    def get_actnum(self, name='ACTNUM'):
        """
        Return an ACTNUM GridProperty object

        Arguments:
            name: name of property in the XTGeo GridProperty object

        Example::

            act = mygrid.get_actnum()
            print('{}% cells are active'.format(act.values.mean() * 100))
        """

        ntot = self._ncol * self._nrow * self._nlay
        act = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                           values=np.zeros(ntot, dtype=np.int32),
                           name=name, discrete=True)

        act._cvalues = self._p_actnum_v  # the SWIG pointer to the C structure
        act._update_values()
        act._codes = {0: '0', 1: '1'}
        act._ncodes = 2
        act._grid = self

        # return the object
        return act

    def get_dz(self, name='dZ', flip=True, mask=True):
        """
        Return the dZ as GridProperty object.

        The dZ is computed as an average height of the vertical pillars in
        each cell, projected to vertical dimension.

        Args:
            name (str): name of property
            flip (bool): Use False for Petrel grids (experimental)
            mask (bool): True if only for active cells, False for all cells

        Returns:
            A xtgeo GridProperty object
        """

        ntot = self._ncol * self._nrow * self._nlay
        dz = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                          values=np.zeros(ntot, dtype=np.float64),
                          name=name, discrete=False)

        ptr_dz_v = _cxtgeo.new_doublearray(self.ntotal)

        nflip = 1
        if not flip:
            nflip = -1

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        option = 0
        if mask:
            option = 1

        _cxtgeo.grd3d_calc_dz(
            self._ncol, self._nrow, self._nlay, self._p_zcorn_v,
            self._p_actnum_v, ptr_dz_v, nflip, option,
            xtg_verbose_level)

        dz._cvalues = ptr_dz_v
        dz._update_values()

        # return the property object
        return dz

    def get_dxdy(self, names=('dX', 'dY')):
        """
        Return the dX and dY as GridProperty object.

        The values lengths are projected to a constant Z

        Args:
            name (tuple): names of properties

        Returns:
            Two XTGeo GridProperty objects
        """

        ntot = self._ncol * self._nrow * self._nlay
        dx = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                          values=np.zeros(ntot, dtype=np.float64),
                          name=names[0], discrete=False)
        dy = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                          values=np.zeros(ntot, dtype=np.float64),
                          name=names[1], discrete=False)

        ptr_dx_v = _cxtgeo.new_doublearray(self.ntotal)
        ptr_dy_v = _cxtgeo.new_doublearray(self.ntotal)

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        option1 = 0
        option2 = 0

        _cxtgeo.grd3d_calc_dxdy(
            self._ncol, self._nrow, self._nlay, self._p_coord_v,
            self._p_zcorn_v, self._p_actnum_v, ptr_dx_v, ptr_dy_v,
            option1, option2, xtg_verbose_level)

        dx._cvalues = ptr_dx_v
        dx._update_values()

        dy._cvalues = ptr_dy_v
        dy._update_values()

        # return the property object
        return dx, dy

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Get X Y Z as properties
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def get_xyz(self, names=['X', 'Y', 'Z'], mask=True):
        """Return 3 GridProperty objects: x coordinate, ycoordinate,
        zcoordinate.

        The values are mid cell values. Note that ACTNUM is
        ignored, so these is also extracted for UNDEF cells (which may have
        weird coordinates). However, the option mask=True will mask the numpies
        for undef cells.

        Arguments:
            names: a list of names per property
            mask: If True, then only active cells
        """

        ntot = self.ntotal

        x = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                         values=np.zeros(ntot, dtype=np.float64),
                         name=names[0], discrete=False)

        y = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                         values=np.zeros(ntot, dtype=np.float64),
                         name=names[1], discrete=False)

        z = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                         values=np.zeros(ntot, dtype=np.float64),
                         name=names[2], discrete=False)

        ptr_x_v = _cxtgeo.new_doublearray(self.ntotal)
        ptr_y_v = _cxtgeo.new_doublearray(self.ntotal)
        ptr_z_v = _cxtgeo.new_doublearray(self.ntotal)

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        option = 0
        if mask:
            option = 1

        _cxtgeo.grd3d_calc_xyz(self._ncol, self._nrow, self._nlay,
                               self._p_coord_v, self._p_zcorn_v,
                               self._p_actnum_v, ptr_x_v, ptr_y_v, ptr_z_v,
                               option, xtg_verbose_level)

        x._cvalues = ptr_x_v
        y._cvalues = ptr_y_v
        z._cvalues = ptr_z_v

        x._update_values()
        y._update_values()
        z._update_values()

        # return the objects
        return x, y, z

    def get_xyz_cell_corners(self, ijk=(1, 1, 1), mask=True):
        """Return a 8 * 3 list x, y, z for each corner.

        .. code-block:: none

           3       4
           !~~~~~~~!
           !  top  !
           !~~~~~~~!    Note that numbers starts from 1
           1       2

           7       8
           !~~~~~~~!
           !  base !
           !~~~~~~~!
           5       6

        Args:
            ijk (tuple): A tuple of I J K (cell counting starts from 1)
            mask (bool): Skip undef cells if set to True.

        Returns:
            A tuple with 24 elements (x1, y1, z1, ... x8, y8, z8)
                for 8 corners. None if cell is inactive and mask=True.

        Example::

            >>> grid = Grid()
            >>> grid.from_file('gullfaks2.roff')
            >>> xyzlist = grid.get_xyz_corners_cell(ijk=(45,13,2))

        Raises:
            RuntimeWarning if spesification is invalid.
        """

        i, j, k = ijk

        if mask is True:
            actnum = self.get_actnum()
            iact = actnum.values3d[i - 1, j - 1, k - 1]
            if iact == 0:
                return None

        pcorners = _cxtgeo.new_doublearray(24)

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        _cxtgeo.grd3d_corners(i, j, k,
                              self.ncol, self.nrow, self.nlay,
                              self._p_coord_v, self._p_zcorn_v,
                              pcorners, xtg_verbose_level)

        cornerlist = []
        for i in range(24):
            cornerlist.append(_cxtgeo.doublearray_getitem(pcorners, i))

        clist = tuple(cornerlist)
        return clist

    def get_xyz_corners(self, names=['X', 'Y', 'Z']):
        """Return 8*3 GridProperty objects, x, y, z for each corner.

        The values are cell corner values. Note that ACTNUM is
        ignored, so these is also extracted for UNDEF cells (which may have
        weird coordinates).

        .. code-block:: none

           2       3
           !~~~~~~~!
           !  top  !
           !~~~~~~~!    Listing corners with Python index (0 base)
           0       1

           6       7
           !~~~~~~~!
           !  base !
           !~~~~~~~!
           4       5

        Args:
            names (list): Generic name of the properties, will have a
                number added, e.g. X0, X1, etc.

        Example::

            >>> grid = Grid()
            >>> grid.from_file('gullfaks2.roff')
            >>> clist = grid.get_xyz_corners()


        Raises:
            RunetimeError if corners has wrong spesification
        """

        ntot = self.ntotal

        grid_props = []

        for i in range(0, 8):
            xname = names[0] + str(i)
            yname = names[1] + str(i)
            zname = names[2] + str(i)
            x = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                             values=np.zeros(ntot, dtype=np.float64),
                             name=xname, discrete=False)

            y = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                             values=np.zeros(ntot, dtype=np.float64),
                             name=yname, discrete=False)

            z = GridProperty(ncol=self._ncol, nrow=self._nrow, nlay=self._nlay,
                             values=np.zeros(ntot, dtype=np.float64),
                             name=zname, discrete=False)

            grid_props.append(x)
            grid_props.append(y)
            grid_props.append(z)

        ptr_coord = []
        for i in range(24):
            some = _cxtgeo.new_doublearray(self.ntotal)
            ptr_coord.append(some)

        for i, v in enumerate(ptr_coord):
            self.logger.debug('SWIG object {}   {}'.format(i, v))

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        option = 0

        # note, fool the argument list to unpack ptr_coord with * ...
        _cxtgeo.grd3d_get_all_corners(self._ncol, self._nrow, self._nlay,
                                      self._p_coord_v,
                                      self._p_zcorn_v, self._p_actnum_v,
                                      *(ptr_coord + [option] +
                                        [xtg_verbose_level]))

        for i in range(0, 24, 3):
            grid_props[i]._cvalues = ptr_coord[i]
            grid_props[i + 1]._cvalues = ptr_coord[i + 1]
            grid_props[i + 2]._cvalues = ptr_coord[i + 2]

            grid_props[i]._update_values()
            grid_props[i + 1]._update_values()
            grid_props[i + 2]._update_values()

        # return the 24 objects (x1, y1, z1, ... x8, y8, z8)
        return grid_props

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Get grid geometrics
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def get_geometrics(self, allcells=False, cellcenter=True,
                       return_dict=False):
        """Get a list of grid geometrics such as origin, min, max, etc.

        This return list is (xori, yori, zori, xmin, xmax, ymin, ymax, zmin,
        zmax, avg_rotation, avg_dx, avg_dy, avg_dz, grid_regularity_flag)

        If a dictionary is returned, the keys are as in the list above

        Args:
            allcells (bool): If True, return also for inactive cells
            cellcenter (bool): If True, use cell center, otherwise corner
                coords
            return_dict (bool): If True, return a dictionary instead of a
                list, which is usually more convinient.

        Raises: Nothing

        Example::

            mygrid = Grid('gullfaks.roff')
            gstuff = mygrid.get_geometrics(return_dict=True)
            print('X min/max is {} {}'.format(gstuff['xmin', gstuff['xmax']))

        """

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        ptr_x = []
        for i in range(13):
            ptr_x.append(_cxtgeo.new_doublepointer())

        option1 = 1
        if allcells:
            option1 = 0

        option2 = 1
        if not cellcenter:
            option2 = 0

        quality = _cxtgeo.grd3d_geometrics(self._ncol, self._nrow, self._nlay,
                                           self._p_coord_v, self._p_zcorn_v,
                                           self._p_actnum_v, ptr_x[0],
                                           ptr_x[1], ptr_x[2], ptr_x[3],
                                           ptr_x[4], ptr_x[5], ptr_x[6],
                                           ptr_x[7], ptr_x[8], ptr_x[9],
                                           ptr_x[10], ptr_x[11], ptr_x[12],
                                           option1, option2,
                                           xtg_verbose_level)

        glist = []
        for i in range(13):
            glist.append(_cxtgeo.doublepointer_value(ptr_x[i]))

        glist.append(quality)

        self.logger.info('Cell geometrics done')

        if return_dict:
            gdict = {}
            gkeys = ['xori', 'yori', 'zori', 'xmin', 'xmax', 'ymin', 'ymax',
                     'zmin', 'zmax', 'avg_rotation', 'avg_dx', 'avg_dy',
                     'avg_dz', 'grid_regularity_flag']
            for i, key in enumerate(gkeys):
                gdict[key] = glist[i]

            return gdict
        else:
            return glist

    # =========================================================================
    # Some more special operations that changes the grid or actnum
    # =========================================================================
    def inactivate_by_dz(self, threshold):
        """Inactivate cells thinner than a given threshold."""

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        if isinstance(threshold, int):
            threshold = float(threshold)

        if not isinstance(threshold, float):
            raise ValueError('The threshold is not a float or int')

        # assumption (unless somebody finds a Petrel made grid):
        nflip = 1

        _cxtgeo.grd3d_inact_by_dz(self.ncol, self.nrow, self.nlay,
                                  self._p_zcorn_v, self._p_actnum_v,
                                  threshold, nflip, xtg_verbose_level)

    def inactivate_inside(self, poly, layer_range=None, inside=True,
                          force_close=False):
        """Inacativate grid inside a polygon.

        The Polygons instance may consist of several polygons. If a polygon
        is open, then the flag force_close will close any that are not open
        when doing the operations in the grid.

        Args:
            poly(Polygons): A polygons object
            layer_range (tuple): A tuple of two ints, upper layer = 1, e.g.
                (1, 14)
            inside (bool): True if remove inside polygon

        Raises:
            RuntimeWarning: If a problems with one or more polygons.
        """

        if not isinstance(poly, xtgeo.xyz.Polygons):
            raise ValueError('Input polygon not a XTGeo Polygons instance')

        if layer_range is not None:
            k1, k2 = layer_range
        else:
            k1 = 1
            k2 = self.nlay

        method = 0
        if not inside:
            method = 1

        iforce = 0
        if force_close:
            iforce = 1

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        # get dataframe where each polygon is ended by a 999 value
        dfxyz = poly.get_xyz_dataframe()

        xc = dfxyz['X'].values
        yc = dfxyz['Y'].values

        ier = _cxtgeo.grd3d_inact_outside_pol(xc, yc, self.ncol,
                                              self.nrow,
                                              self.nlay, self._p_coord_v,
                                              self._p_zcorn_v,
                                              self._p_actnum_v, k1, k2,
                                              iforce, method,
                                              xtg_verbose_level)

        if ier == 1:
            raise RuntimeWarning('Problems with one or more polygons. '
                                 'Not closed?')

    def inactivate_outside(self, poly, layer_range=None):
        """Inacativate grid outside a polygon. (cf inactivate_inside)"""

        self.inactivate_inside(poly, layer_range=layer_range, inside=False)

    def collapse_inactive_cells(self):
        """ Collapse inactive layers where, for I J with other active cells."""

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        _cxtgeo.grd3d_collapse_inact(self.ncol, self.nrow, self.nlay,
                                     self._p_zcorn_v, self._p_actnum_v,
                                     xtg_verbose_level)

    def reduce_to_one_layer(self):
        """Reduce the grid to one single single layer.

        Example::

            >>> from xtgeo.grid3d import Grid
            >>> gf = Grid('gullfaks2.roff')
            >>> gf.nlay
            47
            >>> gf.reduce_to_one_layer()
            >>> gf.nlay
            1

        """

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        # need new pointers in C (not for coord)

        ptr_new_num_act = _cxtgeo.new_intpointer()
        ptr_new_zcorn_v = _cxtgeo.new_doublearray(
            self._ncol * self._nrow * (1 + 1) * 4)
        ptr_new_actnum_v = _cxtgeo.new_intarray(self._ncol * self._nrow * 1)

        _cxtgeo.grd3d_reduce_onelayer(self._ncol, self._nrow, self._nlay,
                                      self._p_zcorn_v,
                                      ptr_new_zcorn_v,
                                      self._p_actnum_v,
                                      ptr_new_actnum_v,
                                      ptr_new_num_act,
                                      0,
                                      xtg_verbose_level)

        self._nlay = 1
        self._p_zcorn_v = ptr_new_zcorn_v
        self._p_actnum_v = ptr_new_actnum_v
        self._nactive = _cxtgeo.intpointer_value(ptr_new_num_act)
        self._nsubs = 0
        self._props = []

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Translate coordinates
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def translate_coordinates(self, translate=(0, 0, 0), flip=(1, 1, 1)):
        """
        Translate (move) and/or flip grid coordinates in 3D.

        Inputs are tuples for (X Y Z). The flip must be 1 or -1.
        """

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        tx, ty, tz = translate
        fx, fy, fz = flip

        ier = _cxtgeo.grd3d_translate(self._ncol, self._nrow, self._nlay,
                                      fx, fy, fz, tx, ty, tz,
                                      self._p_coord_v, self._p_zcorn_v,
                                      xtg_verbose_level)
        if ier != 0:
            raise Exception('Something went wrong in translate')

        self.logger.info('Translation of coords done')

# =============================================================================
# Various methods
# =============================================================================

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Convert to hybrid
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def convert_to_hybrid(self, nhdiv=10, toplevel=1000, bottomlevel=1100,
                          region=None, region_number=None):

        self = _hybridgrid.make_hybridgrid(self, nhdiv=nhdiv,
                                           toplevel=toplevel,
                                           bottomlevel=bottomlevel,
                                           region=region,
                                           region_number=region_number)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Refine vertically
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def refine_vertically(self, rfactor):

        self = _refinegrid.refine_vertically(self, rfactor)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Report well to zone mismatch
    # This works together with a Well object
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def report_zone_mismatch(self, well=None, zonelogname='ZONELOG',
                             mode=0, zoneprop=None, onelayergrid=None,
                             zonelogrange=[0, 9999], zonelogshift=0,
                             depthrange=None, option=0, perflogname=None):
        """
        Reports mismatch between wells and a zone
        """
        this = inspect.currentframe().f_code.co_name

        # first do some trimming of the well dataframe
        if not well:
            self.logger.info('No well object in <{}>; return no result'.
                             format(this))
            return None

        # qperf = True
        if perflogname == 'None' or perflogname is None:
            # qperf = False
            pass
        else:
            if perflogname not in well.lognames:
                self.logger.info(
                    'Ask for perf log <{}> but no such in <{}> for well'
                    ' {}; return'.format(perflogname, this, well.wellname))
                return None

        self.logger.info('Process well object for {}...'.format(well.wellname))
        df = well.dataframe.copy()

        if depthrange:
            self.logger.info('Filter depth...')
            df = df[df.Z_TVDSS > depthrange[0]]
            df = df[df.Z_TVDSS < depthrange[1]]
            df = df.copy()
            self.logger.debug(df)

        self.logger.info('Adding zoneshift {}'.format(zonelogshift))
        if zonelogshift != 0:
            df[zonelogname] += zonelogshift

        self.logger.info('Filter ZONELOG...')
        df = df[df[zonelogname] > zonelogrange[0]]
        df = df[df[zonelogname] < zonelogrange[1]]
        df = df.copy()

        if perflogname:
            self.logger.info('Filter PERF...')
            df[perflogname].fillna(-999, inplace=True)
            df = df[df[perflogname] > 0]
            df = df.copy()

        df.reset_index(drop=True, inplace=True)
        well.dataframe = df

        self.logger.debug(df)

        _cxtgeo.xtg_verbose_file('NONE')
        xtg_verbose_level = self._xtg.syslevel

        # get the relevant well log C arrays...
        ptr_xc = well.get_carray('X_UTME')
        ptr_yc = well.get_carray('Y_UTMN')
        ptr_zc = well.get_carray('Z_TVDSS')
        ptr_zo = well.get_carray(zonelogname)

        nval = well.nrow

        ptr_results = _cxtgeo.new_doublearray(10)

        ptr_zprop = zoneprop.cvalues

        cstatus = _cxtgeo.grd3d_rpt_zlog_vs_zon(self._ncol, self._nrow,
                                                self._nlay, self._p_coord_v,
                                                self._p_zcorn_v,
                                                self._p_actnum_v, ptr_zprop,
                                                nval, ptr_xc, ptr_yc, ptr_zc,
                                                ptr_zo, zonelogrange[0],
                                                zonelogrange[1],
                                                onelayergrid._p_zcorn_v,
                                                onelayergrid._p_actnum_v,
                                                ptr_results, option,
                                                xtg_verbose_level)

        if cstatus == 0:
            self.logger.debug('OK well')
        elif cstatus == 2:
            self.logger.warn('Well {} have no zonation?'.format(well.wellname))
        else:
            self.logger.critical('Somthing si rotten with {}'.
                                 format(well.wellname))

        # extract the report
        perc = _cxtgeo.doublearray_getitem(ptr_results, 0)
        tpoi = _cxtgeo.doublearray_getitem(ptr_results, 1)
        mpoi = _cxtgeo.doublearray_getitem(ptr_results, 2)

        return [perc, tpoi, mpoi]

# =============================================================================
# PRIVATE METHODS
# should not be applied outside the class!
# =============================================================================

# -----------------------------------------------------------------------------
# Import methods for various formats
# -----------------------------------------------------------------------------

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # import roff binary
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def _import_roff(self, gfile):

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')

        xtg_verbose_level = self._xtg.syslevel

        self.logger.info('Working with file {}'.format(gfile))

        self.logger.info('Scanning...')
        ptr_ncol = _cxtgeo.new_intpointer()
        ptr_nrow = _cxtgeo.new_intpointer()
        ptr_nlay = _cxtgeo.new_intpointer()
        ptr_nsubs = _cxtgeo.new_intpointer()

        _cxtgeo.grd3d_scan_roff_bingrid(ptr_ncol, ptr_nrow, ptr_nlay,
                                        ptr_nsubs, gfile, xtg_verbose_level)

        self._ncol = _cxtgeo.intpointer_value(ptr_ncol)
        self._nrow = _cxtgeo.intpointer_value(ptr_nrow)
        self._nlay = _cxtgeo.intpointer_value(ptr_nlay)
        self._nsubs = _cxtgeo.intpointer_value(ptr_nsubs)

        ntot = self._ncol * self._nrow * self._nlay
        ncoord = (self._ncol + 1) * (self._nrow + 1) * 2 * 3
        nzcorn = self._ncol * self._nrow * (self._nlay + 1) * 4

        self.logger.info('NCOORD {}'.format(ncoord))
        self.logger.info('NZCORN {}'.format(nzcorn))
        self.logger.info('Reading...')

        ptr_num_act = _cxtgeo.new_intpointer()
        self._p_coord_v = _cxtgeo.new_doublearray(ncoord)
        self._p_zcorn_v = _cxtgeo.new_doublearray(nzcorn)
        self._p_actnum_v = _cxtgeo.new_intarray(ntot)
        self._p_subgrd_v = _cxtgeo.new_intarray(self._nsubs)

        _cxtgeo.grd3d_import_roff_grid(ptr_num_act, ptr_nsubs, self._p_coord_v,
                                       self._p_zcorn_v, self._p_actnum_v,
                                       self._p_subgrd_v, self._nsubs, gfile,
                                       xtg_verbose_level)

        self._nactive = _cxtgeo.intpointer_value(ptr_num_act)

        self.logger.info('Number of active cells: {}'.format(self.nactive))
        self.logger.info('Number of subgrids: {}'.format(self._nsubs))

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # import eclipse output .GRID
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def _import_ecl_output(self, gfile, gtype):

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')

        xtg_verbose_level = self._xtg.syslevel

        # gtype=0 GRID, gtype=1 FGRID, 2=EGRID, 3=FEGRID ...not all supported
        if gtype == 1 or gtype == 3:
            self.logger.error(
                'Other than GRID and EGRID format not supported'
                ' yet. Return')
            return

        self.logger.info('Working with file {}'.format(gfile))

        self.logger.info('Scanning...')
        ptr_ncol = _cxtgeo.new_intpointer()
        ptr_nrow = _cxtgeo.new_intpointer()
        ptr_nlay = _cxtgeo.new_intpointer()

        if gtype == 0:
            _cxtgeo.grd3d_scan_ecl_grid_hd(gtype, ptr_ncol, ptr_nrow, ptr_nlay,
                                           gfile, xtg_verbose_level)
        elif gtype == 2:
            _cxtgeo.grd3d_scan_ecl_egrid_hd(gtype, ptr_ncol, ptr_nrow,
                                            ptr_nlay, gfile, xtg_verbose_level)

        self._ncol = _cxtgeo.intpointer_value(ptr_ncol)
        self._nrow = _cxtgeo.intpointer_value(ptr_nrow)
        self._nlay = _cxtgeo.intpointer_value(ptr_nlay)

        self.logger.info('NX NY NZ {} {} {}'.format(self._ncol, self._nrow,
                                                    self._nlay))

        ntot = self._ncol * self._nrow * self._nlay
        ncoord = (self._ncol + 1) * (self._nrow + 1) * 2 * 3
        nzcorn = self._ncol * self._nrow * (self._nlay + 1) * 4

        self.logger.info('NTOT NCCORD NZCORN {} {} {}'.format(ntot, ncoord,
                                                              nzcorn))

        self.logger.info('Reading... ncoord is {}'.format(ncoord))

        ptr_num_act = _cxtgeo.new_intpointer()
        self._p_coord_v = _cxtgeo.new_doublearray(ncoord)
        self._p_zcorn_v = _cxtgeo.new_doublearray(nzcorn)
        self._p_actnum_v = _cxtgeo.new_intarray(ntot)

        if gtype == 0:
            # GRID
            _cxtgeo.grd3d_import_ecl_grid(0, ntot, ptr_num_act,
                                          self._p_coord_v, self._p_zcorn_v,
                                          self._p_actnum_v, gfile,
                                          xtg_verbose_level)
        elif gtype == 2:
            # EGRID
            _cxtgeo.grd3d_import_ecl_egrid(0, self._ncol, self._nrow,
                                           self._nlay, ptr_num_act,
                                           self._p_coord_v, self._p_zcorn_v,
                                           self._p_actnum_v, gfile,
                                           xtg_verbose_level)

        nact = _cxtgeo.intpointer_value(ptr_num_act)
        self._nactive = nact

        self.logger.info('Number of active cells: {}'.format(nact))
        self._nsubs = 0

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Import eclipse run suite: EGRID + properties from INIT and UNRST
    # For the INIT and UNRST, props dates shall be selected
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def _import_ecl_run(self, groot, initprops=None,
                        restartprops=None, restartdates=None):

        ecl_grid = groot + '.EGRID'
        ecl_init = groot + '.INIT'
        ecl_rsta = groot + '.UNRST'

        # import the grid
        self._import_ecl_output(ecl_grid, 2)

        # import the init properties unless list is empty
        if initprops:
            initprops = GridProperties()
            initprops.from_file(ecl_init, names=initprops, fformat='init',
                                date=None, grid=self)
            for p in initprops.props:
                self._props.append(p)

        # import the restart properties for dates unless lists are empty
        if restartprops and restartdates:
            restprops = GridProperties()
            restprops.from_file(ecl_rsta, names=restartprops,
                                fformat='unrst', dates=restartdates,
                                grid=self)
            for p in restprops.props:
                self._props.append(p)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # import eclipse input .GRDECL
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def _import_ecl_grdecl(self, gfile):

        # need to call the C function...
        _cxtgeo.xtg_verbose_file('NONE')

        xtg_verbose_level = self._xtg.syslevel

        # make a temporary file
        fd, tmpfile = mkstemp()
        # make a temporary

        with open(gfile) as oldfile, open(tmpfile, 'w') as newfile:
            for line in oldfile:
                if not (re.search(r'^--', line) or re.search(r'^\s+$', line)):
                    newfile.write(line)

        newfile.close()
        oldfile.close()

        # find ncol nrow nz
        mylist = []
        found = False
        with open(tmpfile) as xfile:
            for line in xfile:
                if (found):
                    self.logger.info(line)
                    mylist = line.split()
                    break
                if re.search(r'^SPECGRID', line):
                    found = True

        if not found:
            self.logger.error('SPECGRID not found. Nothing imported!')
            return
        xfile.close()

        self._ncol, self._nrow, self._nlay = \
            int(mylist[0]), int(mylist[1]), int(mylist[2])

        self.logger.info('NX NY NZ in grdecl file: {} {} {}'
                         .format(self._ncol, self._nrow, self._nlay))

        ntot = self._ncol * self._nrow * self._nlay
        ncoord = (self._ncol + 1) * (self._nrow + 1) * 2 * 3
        nzcorn = self._ncol * self._nrow * (self._nlay + 1) * 4

        self.logger.info('Reading...')

        ptr_num_act = _cxtgeo.new_intpointer()
        self._p_coord_v = _cxtgeo.new_doublearray(ncoord)
        self._p_zcorn_v = _cxtgeo.new_doublearray(nzcorn)
        self._p_actnum_v = _cxtgeo.new_intarray(ntot)

        _cxtgeo.grd3d_import_grdecl(self._ncol,
                                    self._nrow,
                                    self._nlay,
                                    self._p_coord_v,
                                    self._p_zcorn_v,
                                    self._p_actnum_v,
                                    ptr_num_act,
                                    tmpfile,
                                    xtg_verbose_level,
                                    )

        # remove tmpfile
        os.close(fd)
        os.remove(tmpfile)

        nact = _cxtgeo.intpointer_value(ptr_num_act)
        self._nactive = nact

        self.logger.info('Number of active cells: {}'.format(nact))
        self._nsubs = 0
