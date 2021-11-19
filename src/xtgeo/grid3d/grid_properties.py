# -*- coding: utf-8 -*-

"""Module for Grid Properties."""


import hashlib
import warnings
from typing import Optional

import xtgeo
from xtgeo.common import XTGDescription, XTGeoDialog

from . import _grid3d_utils as utils
from . import _grid_etc1, _gridprops_etc, _gridprops_import_eclrun
from ._grid3d import _Grid3D
from .grid_property import GridProperty

xtg = XTGeoDialog()
logger = xtg.functionlogger(__name__)


# --------------------------------------------------------------------------------------
# Comment on 'asmasked' vs 'activeonly:
#
# 'asmasked'=True will return a np.ma array, while 'asmasked' = False will
# return a np.ndarray
#
# The 'activeonly' will filter out masked entries, or use None or np.nan
# if 'activeonly' is False.
#
# Use word 'zerobased' for a bool regrading startcell basis is 1 or 0
#
# For functions with mask=... ,they should be replaced with asmasked=...
# --------------------------------------------------------------------------------------


class GridProperties(_Grid3D):
    """Class for a collection of 3D grid props, belonging to the same grid topology.

    See Also:
        The :class:`GridProperty` class.
    """

    def __init__(
        self,
        ncol: Optional[int] = 4,
        nrow: Optional[int] = 3,
        nlay: Optional[int] = 5,
    ):
        """Instantiating.

        Args:
            ncol: Number of columns
            nrow: Number of rows
            nlay: Number of layers

        """
        super().__init__()

        self._ncol = ncol
        self._nrow = nrow
        self._nlay = nlay

        self._props = []  # list of GridProperty objects
        self._names = []  # list of GridProperty names
        self._dates = []  # list of dates (_after_ import) YYYYDDMM

    def __repr__(self):  # noqa: D105
        myrp = (
            "{0.__class__.__name__} (id={1}) ncol={0._ncol!r}, "
            "nrow={0._nrow!r}, nlay={0._nlay!r}, "
            "filesrc={0._names!r}".format(self, id(self))
        )
        return myrp

    def __str__(self):
        """str: User friendly print."""
        return self.describe(flush=False)

    def __contains__(self, name):
        """bool: Emulate 'if "PORO" in props'."""
        prop = self.get_prop_by_name(name, raiseserror=False)
        if prop:
            return True

        return False

    def __getitem__(self, name):  # noqa: D105
        prop = self.get_prop_by_name(name, raiseserror=False)
        if prop is None:
            raise KeyError(f"Key {name} does not exist")

        return prop

    def __iter__(self):  # noqa: D105
        return iter(self._props)

    # ----------------------------------------------------------------------------------
    # Properties:

    @property
    def names(self):
        """Returns or sets a list of property names.

        Example::

            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> props = GridProperties()
            >>> props.from_file(
            ...     reek_dir + "/REEK.INIT",
            ...     fformat="init",
            ...     names=["PERMX"],
            ...     grid=grid,
            ... )

            >>> namelist = props.names
            >>> for name in namelist:
            ...     print ('Property name is {}'.format(name))
            Property name is PERMX

            >>> # when setting names, an empty string 'trick'
            >>> # will make the namelist to be defaulted as
            >>> # each individual property name

            >>> props.names = ""

        """
        return self._names

    @names.setter
    def names(self, nameslist):
        if not nameslist and self._props:
            # try the get the names from each individual property automatic
            for prop in self._props:
                self._names.append(prop.name)
                return

        if len(nameslist) != len(self._props):
            raise ValueError("Number of names does not match number of properties")

        # look for duplicates
        if len(nameslist) > len(set(nameslist)):
            raise ValueError("List of names contains duplicates; names must be unique")

        self._names = nameslist

    @property
    def props(self):
        """Returns a list of XTGeo GridProperty objects, None if empty.

        Example::

            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> myprops = GridProperties()
            >>> myprops.from_file(
            ...     reek_dir + "/REEK.INIT",
            ...     fformat="init",
            ...     names=["PERMX"],
            ...     grid=grid,
            ... )

            >>> proplist = myprops.props
            >>> for prop in proplist:
            ...     print ('Property object name is {}'.format(prop.name))
            Property object name is PERMX

            >>> # adding a property, e.g. get ACTNUM as a property from the grid
            >>> actn = grid.get_actnum()  # this will get actn as a GridProperty
            >>> myprops.append_props([actn])
        """
        if not self._props:
            return None

        return self._props

    @props.setter
    def props(self, propslist):
        self._props = propslist

    @property
    def dates(self):
        """Returns a list of valid (found) dates after import.

        Returns None if no dates present

        Note:
            See also :meth:`GridProperties.scan_dates` for scanning available dates
            in advance

        Example::

            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> props = GridProperties()
            >>> props.from_file(
            ...     reek_dir + "/REEK.INIT",
            ...     fformat="init",
            ...     names=["PERMX"],
            ...     grid=grid,
            ... )

            >>> datelist = props.dates
            >>> for date in datelist:
            ...     print ('Date applied is {}'.format(date))
            Date applied is 19991201

        """
        if not self._dates:
            return None

        return self._dates

    # Copy, and etc aka setters and getters

    def copy(self):
        """Copy a GridProperties instance to a new unique instance.

        Note that the GridProperty instances will also be unique.
        """
        new = GridProperties()

        new._ncol = self._ncol
        new._nrow = self._nrow
        new._nlay = self._nlay

        for prp in self._props:
            newprp = prp.copy()
            new._props.append(newprp)

        for name in self._names:
            new._names.append(name)

        for date in self._dates:
            new._dates.append(date)

        return new

    def describe(self, flush=True):
        """Describe an instance by printing to stdout."""
        dsc = XTGDescription()

        dsc.title("Description of GridProperties instance")
        dsc.txt("Object ID", id(self))
        dsc.txt("Shape: NCOL, NROW, NLAY", self.ncol, self.nrow, self.nlay)
        dsc.txt("Attached grid props objects (names)", self._names)

        if flush:
            dsc.flush()
            return None
        return dsc.astext()

    def generate_hash(self):
        """str: Return a unique hash ID for current gridproperties instance.

        .. versionadded:: 2.10
        """
        mhash = hashlib.sha256()

        hashinput = ""
        for prop in self._props:
            gid = "{}{}{}{}{}{}".format(
                prop.ncol,
                prop.nrow,
                prop.nlay,
                prop.values.mean(),
                prop.values.min(),
                prop.values.max(),
            )
            hashinput += gid

        mhash.update(hashinput.encode())
        return mhash.hexdigest()

    def get_prop_by_name(self, name, raiseserror=True):
        """Find and return a property object (GridProperty) by name.

        Args:
            name (str): Name of property to look for
            raiseserror (bool): If True, raises a ValueError if not found, otherwise
                return None

        """
        for prop in self._props:
            logger.debug("Look for %s, actual is %s", name, prop.name)
            if prop.name == name:
                logger.debug(repr(prop))
                return prop

        if raiseserror:
            raise ValueError("Cannot find property with name <{}>".format(name))

        return None

    def append_props(self, proplist):
        """Add a list of GridProperty objects to current GridProperties instance."""
        for prop in proplist:
            if isinstance(prop, GridProperty):
                # an prop instance can only occur once
                if prop not in self._props:

                    self._props.append(prop)
                    self._names.append(prop.name)
                    self._dates.append(prop.date)
                    self._ncol = prop.ncol
                    self._nrow = prop.nrow
                    self._nlay = prop.nlay
                else:
                    logger.info("Not added. GridProperty instance already present")
            else:
                raise ValueError("Input property is not a valid GridProperty " "object")

    def get_ijk(
        self, names=("IX", "JY", "KZ"), zerobased=False, asmasked=False, mask=None
    ):
        """Returns 3 xtgeo.grid3d.GridProperty objects: I counter, J counter, K counter.

        Args:
            names: a 3 x tuple of names per property (default IX, JY, KZ).
            asmasked: If True, then active cells only.
            mask: If True, then active cells only (deprecated).
            zerobased: If True, counter start from 0, otherwise 1 (default=1).
        """
        if mask is not None:
            xtg.warndeprecated(
                "The mask option is deprecated,"
                "and will be removed in version 4.0. Use asmasked instead."
            )
            asmasked = super()._evaluate_mask(mask)

        # resuse method from grid
        ixc, jyc, kzc = _grid_etc1.get_ijk(
            self, names=names, zerobased=zerobased, asmasked=asmasked
        )

        # return the objects
        return ixc, jyc, kzc

    def get_actnum(self, name="ACTNUM", asmasked=False, mask=None):
        """Return an ACTNUM GridProperty object.

        Args:
            name (str): name of property in the XTGeo GridProperty object.
            asmasked (bool): ACTNUM is returned with all cells
                as default. Use asmasked=True to make 0 entries masked.
            mask (bool): Deprecated, use asmasked instead.

        Example::

            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> myprops = GridProperties()
            >>> myprops.from_file(
            ...     reek_dir + "/REEK.INIT",
            ...     fformat="init",
            ...     names=["PERMX"],
            ...     grid=grid,
            ... )
            >>> act = myprops.get_actnum()
            >>> print('{}% of cells are active'.format(act.values.mean() * 100))
            99.99...% of cells are active

        Returns:
            A GridProperty instance of ACTNUM, or None if no props present.
        """
        if mask is not None:
            xtg.warndeprecated(
                "The mask option is deprecated,"
                "and will be removed in version 4.0. Use asmasked instead."
            )
            asmasked = super()._evaluate_mask(mask)

        # borrow function from GridProperty class:
        if self._props:
            return self._props[0].get_actnum(name=name, asmasked=asmasked)

        warnings.warn("No gridproperty in list", UserWarning)
        return None

    # Import and export
    # This class can importies several properties in one go, which is efficient
    # for some file types such as Eclipse INIT and UNRST, and Roff

    def from_file(
        self,
        pfile,
        fformat="roff",
        names=None,
        dates=None,
        grid=None,
        namestyle=0,
        strict=(True, False),
    ):
        """Import grid properties from file in one go.

        This class is particulary useful for Eclipse INIT and RESTART files.

        In case of names='all' then all vectors which have a valid length
        (number of total or active cells in the grid) will be read

        Args:
            pfile (str or Path): Name of file with properties
            fformat (str): roff/init/unrst
            names: list of property names, e.g. ['PORO', 'PERMX'] or 'all'
            dates: list of dates on YYYYMMDD format, for restart files, or 'all'
            grid (obj): The grid geometry object (optional if ROFF)
            namestyle (int): 0 (default) for style SWAT_20110223,
                1 for SWAT--2011_02_23 (applies to restart only)
            strict (tuple of (bool, bool)): If (True, False) (default) then an
                Error is raised if keyword name is not found, or a key-date combination
                is not found. However, the dates will processed so that non-valid dates
                are skipped (still, invalid key-date combinations may occur!).
                If (True, True) all keywords and dates are tried, while (False, False)
                means that that only valid entries are imported, more or less silently.
                Saturations keywords SWAT/SOIL/SGAS are not evaluated as they may be
                derived.

        Example::
            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> props = GridProperties()
            >>> props.from_file(
            ...     reek_dir + "/REEK.INIT",
            ...     fformat="init",
            ...     names=["PERMX"],
            ...     grid=grid,
            ... )


        Raises:
            FileNotFoundError: if input file is not found
            DateNotFoundError: The date is not found
            KeywordNotFoundError: The keyword is not found
            KeywordFoundDateNotFoundError: The keyword but not date found

        .. versionadded:: 2.13 Added strict key
        """
        pfile = xtgeo._XTGeoFile(pfile, mode="rb")

        # work on file extension
        froot, fext = pfile.splitext(lower=True)
        if not fext:
            # file extension is missing, guess from format
            logger.info("File extension missing; guessing...")

            useext = ""
            if fformat == "init":
                useext = ".INIT"
            elif fformat == "unrst":
                useext = ".UNRST"
            elif fformat == "roff":
                useext = ".roff"

            pfile = froot + useext

        logger.info("File name to be used is %s", pfile)

        pfile.check_file(raiseerror=OSError)

        if fformat.lower() == "roff":
            properties = [
                GridProperty(pfile, fformat="roff", name=name) for name in names
            ]

        elif fformat.lower() == "init":
            properties = _gridprops_import_eclrun.import_ecl_init_gridproperties(
                pfile,
                grid=grid,
                names=names,
                strict=strict[0],
            )
        elif fformat.lower() == "unrst":
            properties = _gridprops_import_eclrun.import_ecl_restart_gridproperties(
                pfile,
                dates=dates,
                grid=grid,
                names=names,
                namestyle=namestyle,
                strict=strict,
            )
        else:
            raise OSError("Invalid file format")

        self.append_props(properties)

    def get_dataframe(
        self, activeonly=False, ijk=False, xyz=False, doubleformat=False, grid=None
    ):
        """Returns a Pandas dataframe table for the properties.

        Args:
            activeonly (bool): If True, return only active cells, NB!
                If True, will require a grid instance (see grid key)
            ijk (bool): If True, show cell indices, IX JY KZ columns
            xyz (bool): If True, show cell center coordinates (needs grid).
            doubleformat (bool): If True, floats are 64 bit, otherwise 32 bit.
                Note that coordinates (if xyz=True) is always 64 bit floats.
            grid (Grid): The grid geometry object. This is required for the
                xyz option.

        Returns:
            Pandas dataframe object

        Examples::

            >>> import xtgeo
            >>> grid = xtgeo.grid_from_file(reek_dir + "/REEK.EGRID")
            >>> props = GridProperties()
            >>> props.from_file(
            ...     reek_dir + "/REEK.UNRST",
            ...     fformat="unrst",
            ...     names=['SOIL', 'SWAT', 'PRESSURE'],
            ...     dates=[19991201],
            ...     grid=grid,
            ... )
            >>> df = props.dataframe(activeonly=False, ijk=True, xyz=True, grid=grid)
            >>> print(df)
                   ACTNUM  IX  JY  ...  SOIL_19991201  SWAT_19991201  PRESSURE_19991201
            0           1   1   1  ...            0.0            1.0         341.694183
            1           1   1   1  ...            0.0            1.0         342.097107
            2           1   1   1  ...            0.0            1.0         342.500061
            3           1   1   1  ...            0.0            1.0         342.902954
            4           1   1   1  ...            0.0            1.0         343.305908
            ...

        """
        dfr = _gridprops_etc.dataframe(
            self,
            activeonly=activeonly,
            ijk=ijk,
            xyz=xyz,
            doubleformat=doubleformat,
            grid=grid,
        )

        return dfr

    dataframe = get_dataframe  # for compatibility, but deprecated

    # Static methods (scans etc)
    # Don't make a GridProperties instance inside other XTGeo classes
    # as it make cyclic imports. I.e. use only these functions in clients
    # if needed...

    @staticmethod
    def scan_keywords(
        pfile, fformat="xecl", maxkeys=100000, dataframe=False, dates=False
    ):
        """Quick scan of keywords in Eclipse binary files, or ROFF binary files.

        For Eclipse files:
        Returns a list of tuples (or dataframe), e.g. ('PRESSURE',
        'REAL', 355299, 3582700), where (keyword, type, no_of_values,
        byteposition_in_file)

        For ROFF files
        Returns a list of tuples (or dataframe), e.g.
        ('translate!xoffset', 'float', 1, 3582700),
        where (keyword, type, no_of_values, byteposition_in_file).

        For Eclipse, the byteposition is to the KEYWORD, while for ROFF
        the byte position is to the beginning of the actual data.

        Args:
            pfile (str): Name or a filehandle to file with properties
            fformat (str): xecl (Eclipse INIT, RESTART, ...) or roff for
                ROFF binary,
            maxkeys (int): Maximum number of keys
            dataframe (bool): If True, return a Pandas dataframe instead
            dates (bool): if True, the date is the last column (only
                menaingful for restart files). Default is False.

        Return:
            A list of tuples or dataframe with keyword info

        Example::
            >>> dlist = GridProperties.scan_keywords(reek_dir + "/REEK.UNRST")

        """
        pfile = xtgeo._XTGeoFile(pfile)

        dlist = utils.scan_keywords(
            pfile, fformat=fformat, maxkeys=maxkeys, dataframe=dataframe, dates=dates
        )

        return dlist

    @staticmethod
    def scan_dates(
        pfile, fformat="unrst", maxdates=1000, dataframe=False, datesonly=False
    ):
        """Quick scan dates in a simulation restart file.

        Args:
            pfile (str): Name of file or file handle with properties
            fformat (str): unrst (so far)
            maxdates (int): Maximum number of dates to collect
            dataframe (bool): If True, return a Pandas dataframe instead
            datesonly (bool): If True, SEQNUM is skipped,

        Return:
            A list of tuples or a dataframe with (seqno, date),
            date is on YYYYMMDD form. If datesonly is True and dataframe is False,
            the returning list will be a simple list of dates.

        Example::
            >>> dlist = GridProperties.scan_dates(reek_dir + "/REEK.UNRST")
            >>> #or getting all dates a simple list:
            >>> dlist = GridProperties.scan_dates(
            ... reek_dir + "/REEK.UNRST",
            ... datesonly=True)

        .. versionchanged:: 2.13 Added datesonly keyword
        """
        pfile = xtgeo._XTGeoFile(pfile)

        logger.info("Format supported as default is %s", fformat)

        dlist = utils.scan_dates(pfile, maxdates=maxdates, dataframe=dataframe)

        if datesonly and dataframe:
            dlist.drop("SEQNUM", axis=1, inplace=True)

        if datesonly and not dataframe:
            dlist = [date for (_, date) in dlist]

        return dlist
