# -*- coding: utf-8 -*-
# Copyright (C) Duncan Macleod (2014)
#
# This file is part of GWpy.
#
# GWpy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# GWpy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with GWpy.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for :mod:`gwpy.segments`
"""

import os.path
import shutil
import tempfile
from ssl import SSLError

from six.moves.urllib.error import (URLError, HTTPError)

import pytest

from matplotlib import use, rc_context
use('agg')  # nopep8

from gwpy.plotter import (SegmentPlot, SegmentAxes)
from gwpy.segments import (Segment, SegmentList,
                           DataQualityFlag, DataQualityDict)
from gwpy.time import LIGOTimeGPS

import utils
import mocks
from mocks import mock

__author__ = 'Duncan Macleod <duncan.macleod@ligo.org>'


# -- veto definer fixture -----------------------------------------------------

VETO_DEFINER_FILE = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE LIGO_LW SYSTEM "http://ldas-sw.ligo.caltech.edu/doc/ligolwAPI/html/ligolw_dtd.txt">
<LIGO_LW>
	<Table Name="veto_definer:table">
		<Column Type="int_4s" Name="veto_definer:category"/>
		<Column Type="lstring" Name="veto_definer:comment"/>
		<Column Type="int_4s" Name="veto_definer:end_pad"/>
		<Column Type="ilwd:char" Name="veto_definer:process_id"/>
		<Column Type="lstring" Name="veto_definer:name"/>
		<Column Type="int_4s" Name="veto_definer:version"/>
		<Column Type="int_4s" Name="veto_definer:start_pad"/>
		<Column Type="int_4s" Name="veto_definer:start_time"/>
		<Column Type="lstring" Name="veto_definer:ifo"/>
		<Column Type="int_4s" Name="veto_definer:end_time"/>
		<Stream Delimiter="," Type="Local" Name="veto_definer:table">
			1,"Test flag 1",2,,"TEST-FLAG",1,-1,100,"X1",0,
			2,"Test flag 1",2,,"TEST-FLAG_2",1,1,100,"X1",200,
			2,"Test flag 1",2,,"TEST-FLAG_2",2,-2,200,"X1",0,
			2,"Test flag 1",2,,"TEST-FLAG_2",2,-2,100,"Y1",0,
		</Stream>
	</Table>
</LIGO_LW>
"""  # nopep8


@pytest.fixture(scope='module')
def veto_definer():
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w',
                                     delete=False) as f:
        f.write(VETO_DEFINER_FILE)
        f.seek(0)
        yield f.name
    if os.path.isfile(f.name):
        os.remove(f.name)


# -- test data ----------------------------------------------------------------

def _as_segmentlist(*segments):
    return SegmentList([Segment(a, b) for a, b in segments])


NAME = 'X1:TEST-FLAG_NAME:0'

# simple list of 'known' segments
KNOWN = _as_segmentlist(
    (0, 3), (6, 7))

# simple  list of 'active' segments
ACTIVE = _as_segmentlist(
    (1, 2), (3, 4), (5, 7))

# intersection of above 'known' and 'active' segments
KNOWNACTIVE = _as_segmentlist(
    (1, 2), (6, 7))

# 'active' set contracted by 0.1 seconds
ACTIVE_CONTRACTED = _as_segmentlist(
    (1.1, 1.9), (3.1, 3.9))

# 'active' seg protracted by 0.1 seconts
ACTIVE_PROTRACTED = _as_segmentlist(
    (.9, 2.1), (2.9, 4.1), (4.9, 7.1))

# some more segments
KNOWN2 = _as_segmentlist(
    (100, 150))

ACTIVE2 = _as_segmentlist(
    (100, 101), (110, 120))

# padding
PADDING = (-0.5, 1)

# padded version of above 'known' segments
KNOWNPAD = _as_segmentlist(
    (-.5, 4), (5.5, 8))

# padded version of above 'active' segments
ACTIVEPAD = _as_segmentlist(
    (.5, 3), (2.5, 5), (4.5, 8))

# padded, coalesed version of above 'active' segments
ACTIVEPADC = _as_segmentlist(
    (.5, 4), (5.5, 8))


# -- query helpers ------------------------------------------------------------

QUERY_FLAGS = ['X1:TEST-FLAG:1', 'Y1:TEST-FLAG2:4']

QUERY_RESULT = DataQualityDict()

QUERY_RESULT['X1:TEST-FLAG:1'] = DataQualityFlag(
    'X1:TEST-FLAG:1',
    known=[(0, 10)],
    active=[(0, 1), (1, 2), (3, 4), (6, 9)])

QUERY_RESULT['Y1:TEST-FLAG2:4'] = DataQualityFlag(
    'Y1:TEST-FLAG2:4',
    known=[(0, 5), (9, 10)],
    active=[])

QUERY_RESULTC = type(QUERY_RESULT)({x: y.copy().coalesce() for
                                    x, y in QUERY_RESULT.items()})


def query_segdb(query_func, *args, **kwargs):
    """Mock a query to an S6-style DB2 database
    """
    try:
        with mock.patch('glue.segmentdb.segmentdb_utils.setup_database'), \
             mock.patch('glue.segmentdb.segmentdb_utils.expand_version_number',
                        mocks.segdb_expand_version_number(1, 4)), \
             mock.patch('glue.segmentdb.segmentdb_utils.query_segments',
                        mocks.segdb_query_segments(QUERY_RESULT)):
            return query_func(*args, **kwargs)
    except ImportError as e:
        pytest.skip(str(e))


def query_dqsegdb(query_func, *args, **kwargs):
    """Mock a query to an aLIGO DQSEGDB database
    """
    try:
        with mock.patch('dqsegdb.apicalls.dqsegdbQueryTimes',
                        mocks.dqsegdb_query_times(QUERY_RESULT)), \
             mock.patch('dqsegdb.apicalls.dqsegdbCascadedQuery',
                        mocks.dqsegdb_cascaded_query(QUERY_RESULT)):
            return query_func(*args, **kwargs)
    except ImportError as e:
        pytest.skip(str(e))


# -----------------------------------------------------------------------------
#
# gwpy.segments.segments
#
# -----------------------------------------------------------------------------

# -- Segment ------------------------------------------------------------------

class TestSegment(object):
    TEST_CLASS = Segment

    @classmethod
    @pytest.fixture()
    def segment(cls):
        return cls.TEST_CLASS(1, 2)

    def test_start_end(self, segment):
        assert segment.start == 1.
        assert segment.end == 2.

    def test_repr(self, segment):
        assert repr(segment) == 'Segment(1, 2)'

    def test_str(self, segment):
        assert str(segment) == '[1 ... 2)'


# -- SegmentList --------------------------------------------------------------

class TestSegmentList(object):
    TEST_CLASS = SegmentList
    ENTRY_CLASS = Segment

    @classmethod
    def create(cls, *segments):
        return cls.TEST_CLASS([cls.ENTRY_CLASS(a, b) for a, b in segments])

    @classmethod
    @pytest.fixture()
    def segmentlist(cls):
        return cls.create((1, 2), (3, 4), (4, 6), (8, 10))

    # -- test methods ---------------------------

    def test_coalesce(self):
        segmentlist = self.create((1, 2), (3, 4), (4, 5))
        c = segmentlist.coalesce()
        assert c is segmentlist
        utils.assert_segmentlist_equal(c, [(1, 2), (3, 5)])
        assert isinstance(c[0], self.ENTRY_CLASS)

    # -- test I/O -------------------------------

    @utils.skip_missing_dependency('lal')
    def test_read_write_segwizard(self, segmentlist):
        with tempfile.NamedTemporaryFile(suffix='.txt', mode='w') as f:
            # check write/read returns the same list
            segmentlist.write(f.name)
            sl2 = self.TEST_CLASS.read(f.name, coalesce=False)
            utils.assert_segmentlist_equal(sl2, segmentlist)
            assert isinstance(sl2[0][0], LIGOTimeGPS)

            # check that coalesceing does what its supposed to
            c = type(segmentlist)(segmentlist).coalesce()
            sl2 = self.TEST_CLASS.read(f.name, coalesce=True)
            utils.assert_segmentlist_equal(sl2, c)

            # check gpstype kwarg
            sl2 = self.TEST_CLASS.read(f.name, gpstype=float)
            assert isinstance(sl2[0][0], float)

    @utils.skip_missing_dependency('h5py')
    @pytest.mark.parametrize('ext', ('.hdf5', '.h5'))
    def test_read_write_hdf5(self, segmentlist, ext):
        tempdir = tempfile.mkdtemp()
        try:
            fp = tempfile.mktemp(suffix=ext, dir=tempdir)

            # check basic write/read with auto-path discovery
            segmentlist.write(fp, 'test-segmentlist')
            sl2 = self.TEST_CLASS.read(fp)
            utils.assert_segmentlist_equal(sl2, segmentlist)
            assert isinstance(sl2[0][0], LIGOTimeGPS)

            sl2 = self.TEST_CLASS.read(fp, path='test-segmentlist')
            utils.assert_segmentlist_equal(sl2, segmentlist)

            # check overwrite kwarg
            with pytest.raises(IOError):
                segmentlist.write(fp, 'test-segmentlist')
            segmentlist.write(fp, 'test-segmentlist', overwrite=True)

            # check gpstype kwarg
            sl2 = self.TEST_CLASS.read(fp, gpstype=float)
            utils.assert_segmentlist_equal(sl2, segmentlist)
            assert isinstance(sl2[0][0], float)

        finally:
            if os.path.isdir(tempdir):
                shutil.rmtree(tempdir)


# -----------------------------------------------------------------------------
#
# gwpy.segments.flag
#
# -----------------------------------------------------------------------------

# -- DataQualityFlag ----------------------------------------------------------

class TestDataQualityFlag(object):
    TEST_CLASS = DataQualityFlag

    @classmethod
    def create(cls, name=NAME, known=KNOWN, active=ACTIVE, **kwargs):
        return cls.TEST_CLASS(name=name, known=known, active=active, **kwargs)

    @classmethod
    @pytest.fixture()
    def flag(cls):
        return cls.create()

    @classmethod
    @pytest.fixture()
    def empty(cls):
        return cls.TEST_CLASS()

    # -- test attributes ------------------------

    def test_name(self, empty, flag):
        assert empty.name is None

        assert flag.name == NAME
        assert flag.ifo == NAME.split(':')[0]
        assert flag.tag == NAME.split(':')[1]
        assert flag.version == int(NAME.split(':')[2])

    def test_known(self, empty, flag):
        assert isinstance(empty.known, SegmentList)
        assert empty.known == []

        utils.assert_segmentlist_equal(flag.known, KNOWN)

        new = self.TEST_CLASS()
        new.known = [(1, 2), (3, 4)]
        assert isinstance(empty.known, SegmentList)

    def test_active(self, empty, flag):
        assert isinstance(empty.active, SegmentList)
        assert empty.active == []

        utils.assert_segmentlist_equal(flag.active, ACTIVE)

        new = self.TEST_CLASS()
        new.active = [(1, 2), (3, 4)]
        assert isinstance(empty.active, SegmentList)

    def test_texname(self, empty, flag):
        assert empty.texname is None
        assert flag.texname == NAME.replace('_', r'\_')

    def test_extent(self, empty, flag):
        assert flag.extent == (KNOWN[0][0], KNOWN[-1][1])
        with pytest.raises(ValueError):
            empty.extent

    def test_livetime(self, empty, flag):
        assert empty.livetime == 0
        assert flag.livetime == abs(ACTIVE)

    def test_regular(self, empty, flag):
        assert empty.regular is True
        assert flag.regular is False

    def test_padding(self, flag):
        assert flag.padding == (0, 0)

        flag.padding = [-1, 2]
        assert isinstance(flag.padding, tuple)
        assert flag.padding == (-1, 2)

        flag.padding = None
        assert flag.padding == (0, 0)

        del flag.padding
        assert flag.padding == (0, 0)

    def test_deprecated_names(self):
        with pytest.warns(DeprecationWarning):
            flag = self.TEST_CLASS(NAME, valid=KNOWN)
        with pytest.raises(ValueError):
            flag = self.TEST_CLASS(NAME, valid=KNOWN, known=KNOWN)
        with pytest.warns(DeprecationWarning):
            flag.valid
        with pytest.warns(DeprecationWarning):
            flag.valid = flag.known
        with pytest.warns(DeprecationWarning):
            del flag.valid

    # -- test methods ---------------------------

    def test_parse_name(self):
        flag = self.TEST_CLASS(None)
        assert flag.name is None
        assert flag.ifo is None
        assert flag.tag is None
        assert flag.version is None

        flag = self.TEST_CLASS('test')
        assert flag.name == 'test'
        assert flag.ifo is None
        assert flag.tag is None
        assert flag.version is None

        flag = self.TEST_CLASS('L1:test')
        assert flag.name == 'L1:test'
        assert flag.ifo == 'L1'
        assert flag.tag == 'test'
        assert flag.version is None

        flag = self.TEST_CLASS('L1:test:1')
        assert flag.name == 'L1:test:1'
        assert flag.ifo == 'L1'
        assert flag.tag == 'test'
        assert isinstance(flag.version, int)
        assert flag.version == 1

        flag = self.TEST_CLASS('test:1')
        assert flag.name == 'test:1'
        assert flag.ifo is None
        assert flag.tag == 'test'
        assert flag.version == 1

    def test_plot(self, flag):
        flag.label = 'Test label'
        with rc_context(rc={'text.usetex': False}):
            plot = flag.plot(figsize=(6.4, 3.8))
            assert isinstance(plot, SegmentPlot)
            assert isinstance(plot.gca(), SegmentAxes)
            assert plot.gca().get_epoch() == flag.known[0][0]
            assert len(plot.gca().collections) == 2
            assert len(plot.gca().collections[0].get_paths()) == len(KNOWN)
            assert len(plot.gca().collections[1].get_paths()) == len(ACTIVE)
            assert plot.gca().collections[0].get_label() == flag.label

            with tempfile.NamedTemporaryFile(suffix='.png') as f:
                plot.save(f.name)
            plot.close()

        flag.label = None
        with rc_context(rc={'text.usetex': True}):
            plot = flag.plot(figsize=(6.4, 3.8))
            assert plot.gca().collections[0].get_label() == flag.texname
            plot.close()

    def test_math(self):
        a = self.TEST_CLASS(active=ACTIVE[:2], known=KNOWN)
        b = self.TEST_CLASS(active=ACTIVE[2:], known=KNOWN)

        # and
        x = a & b
        utils.assert_segmentlist_equal(x.active, a.active & b.active)
        utils.assert_segmentlist_equal(x.known, a.known & b.known)

        # sub
        x = a - b
        utils.assert_segmentlist_equal(x.active, a.active - b.active)
        utils.assert_segmentlist_equal(x.known, a.known & b.known)

        # or
        x = a | b
        utils.assert_segmentlist_equal(x.active, a.active | b.active)
        utils.assert_segmentlist_equal(x.known, a.known | b.known)

        # invert
        x = ~a
        utils.assert_segmentlist_equal(x.active, a.known & ~a.active)
        utils.assert_segmentlist_equal(x.known, a.known)

    def test_coalesce(self):
        flag = self.create()
        flag.coalesce()
        utils.assert_segmentlist_equal(flag.known, KNOWN)
        utils.assert_segmentlist_equal(flag.active, KNOWNACTIVE)
        assert flag.regular is True

    def test_contract(self):
        flag = self.create()
        flag.contract(.1)
        utils.assert_segmentlist_equal(flag.known, KNOWN)
        utils.assert_segmentlist_equal(flag.active, ACTIVE_CONTRACTED)

    def test_protract(self):
        flag = self.create(active=ACTIVE_CONTRACTED)
        flag.protract(.1)
        utils.assert_segmentlist_equal(flag.known, KNOWN)
        utils.assert_segmentlist_equal(flag.active, ACTIVE)

    @pytest.mark.parametrize('contract, active', [
        (False, ACTIVE_CONTRACTED),
        (True, ACTIVE_PROTRACTED),
    ])
    def test_round(self, contract, active):
        flag = self.create(active=active)
        r = flag.round(contract=contract)
        utils.assert_segmentlist_equal(r.known, KNOWN)
        utils.assert_segmentlist_equal(r.active, KNOWNACTIVE)

    def test_pad(self, flag):
        # test with no arguments (and no padding)
        padded = flag.pad()
        utils.assert_flag_equal(flag, padded)

        # test with padding
        flag.padding = PADDING
        padded = flag.pad()
        utils.assert_segmentlist_equal(padded.known, KNOWNPAD)
        utils.assert_segmentlist_equal(padded.active, ACTIVEPAD)

        # test with arguments
        flag.padding = None
        padded = flag.pad(*PADDING)
        utils.assert_segmentlist_equal(padded.known, KNOWNPAD)
        utils.assert_segmentlist_equal(padded.active, ACTIVEPAD)

        # test in-place
        padded = flag.pad(*PADDING)
        assert padded is not flag
        padded = flag.pad(*PADDING, inplace=True)
        assert padded is flag
        utils.assert_segmentlist_equal(flag.known, KNOWNPAD)
        utils.assert_segmentlist_equal(flag.active, ACTIVEPAD)

        # check that other keyword arguments get rejected appropriately
        with pytest.raises(TypeError):
            flag.pad(*PADDING, kwarg='test')

    @utils.skip_missing_dependency('glue.ligolw.lsctables')
    def test_from_veto_def(self):
        from glue.ligolw.lsctables import VetoDef

        def veto_def(ifo, name, version, **kwargs):
            vdef = VetoDef()
            kwargs['ifo'] = ifo
            kwargs['name'] = name
            kwargs['version'] = version
            for key in VetoDef.__slots__:
                setattr(vdef, key, kwargs.get(key, None))
            return vdef

        a = veto_def('X1', 'TEST-FLAG', 1, start_time=0, end_time=0,
                     start_pad=-2, end_pad=2, comment='Comment')
        f = self.TEST_CLASS.from_veto_def(a)
        assert f.name == 'X1:TEST-FLAG:1'
        assert f.category is None
        assert f.padding == (-2, 2)
        assert f.description == 'Comment'
        utils.assert_segmentlist_equal(f.known, [(0, float('inf'))])

        a = veto_def('X1', 'TEST-FLAG', None, start_time=0, end_time=1)
        f = self.TEST_CLASS.from_veto_def(a)
        assert f.name == 'X1:TEST-FLAG'
        assert f.version is None

    @utils.skip_missing_dependency('lal')
    @utils.skip_missing_dependency('dqsegdb')
    def test_populate(self):
        name = QUERY_FLAGS[0]
        flag = self.TEST_CLASS(name, known=QUERY_RESULT[name].known)

        with mock.patch('dqsegdb.apicalls.dqsegdbQueryTimes',
                        mocks.dqsegdb_query_times(QUERY_RESULT)):
            flag.populate()
        utils.assert_flag_equal(flag, QUERY_RESULTC[name])

    # -- test I/O -------------------------------

    @pytest.mark.parametrize('format, ext, rw_kwargs, simple', [
        ('ligolw', 'xml', {}, False),
        ('ligolw', 'xml.gz', {}, False),
        ('hdf5', 'hdf5', {'path': 'test-dqflag'}, False),
        ('hdf5', 'h5', {'path': 'test-dqflag'}, False),
        ('json', 'json', {}, True),
    ])
    def test_read_write(self, flag, format, ext, rw_kwargs, simple):
        # simplify calling read/write tester
        def _read_write(**kwargs):
            read_kw = rw_kwargs.copy()
            read_kw.update(kwargs.pop('read_kw', {}))
            write_kw = rw_kwargs.copy()
            write_kw.update(kwargs.pop('write_kw', {}))
            return utils.test_read_write(flag, format, extension=ext,
                                         assert_equal=utils.assert_flag_equal,
                                         read_kw=read_kw, write_kw=write_kw,
                                         **kwargs)

        # perform simple test
        if simple:
            _read_write()

        # perform complicated test
        else:
            try:
                _read_write(autoidentify=False)
            except ImportError as e:
                pytest.skip(str(e))
            with pytest.raises(IOError):
                _read_write(autoidentify=True)
            _read_write(autoidentify=True, write_kw={'overwrite': True})

    @utils.skip_missing_dependency('glue.ligolw.lsctables')
    def test_write_ligolw_attrs(self, flag):
        from gwpy.io.ligolw import read_table
        with tempfile.NamedTemporaryFile(suffix='.xml') as f:
            flag.write(f, format='ligolw',
                       attrs={'process_id': 'process:process_id:100'})
            segdeftab = read_table(f, 'segment_definer')
            assert str(segdeftab[0].process_id) == (
                'process:process_id:100')

    # -- test queries ---------------------------

    @pytest.mark.parametrize('api', ('dqsegdb', 'segdb'))
    def test_query(self, api):
        try:
            if api == 'dqsegdb':
                result = query_dqsegdb(self.TEST_CLASS.query, QUERY_FLAGS[0],
                                       0, 10)
                RESULT = QUERY_RESULT[QUERY_FLAGS[0]].copy().coalesce()
            else:
                result = query_segdb(self.TEST_CLASS.query, QUERY_FLAGS[0],
                                     0, 10,
                                     url='https://geosegdb.does.not.exist')
                RESULT = QUERY_RESULT[QUERY_FLAGS[0]]
        except ImportError as e:
            pytest.skip(str(e))

        assert isinstance(result, self.TEST_CLASS)
        utils.assert_segmentlist_equal(result.known, RESULT.known)
        utils.assert_segmentlist_equal(result.active, RESULT.active)

    def test_query_segdb(self):
        result = query_segdb(self.TEST_CLASS.query_segdb,
                             QUERY_FLAGS[0], 0, 10)
        RESULT = QUERY_RESULT[QUERY_FLAGS[0]]

        assert isinstance(result, self.TEST_CLASS)
        utils.assert_segmentlist_equal(result.known, RESULT.known)
        utils.assert_segmentlist_equal(result.active, RESULT.active)

        result2 = query_segdb(self.TEST_CLASS.query_segdb,
                              QUERY_FLAGS[0], (0, 10))
        utils.assert_flag_equal(result, result2)

        result2 = query_segdb(self.TEST_CLASS.query_segdb,
                              QUERY_FLAGS[0], SegmentList([(0, 10)]))
        utils.assert_flag_equal(result, result2)

        with pytest.raises(TypeError):
            self.TEST_CLASS.query_segdb(QUERY_FLAGS[0], 1, 2, 3)
        with pytest.raises(TypeError):
            self.TEST_CLASS.query_segdb(QUERY_FLAGS[0], (1, 2, 3))

    @pytest.mark.parametrize('name, flag', [
        (QUERY_FLAGS[0], QUERY_FLAGS[0]),  # regular query
        (QUERY_FLAGS[0].rsplit(':', 1)[0], QUERY_FLAGS[0]),  # versionless
    ])
    def test_query_dqsegdb(self, name, flag):
        result = query_dqsegdb(self.TEST_CLASS.query_dqsegdb, name, 0, 10)
        RESULT = QUERY_RESULTC[flag]

        assert isinstance(result, self.TEST_CLASS)
        utils.assert_segmentlist_equal(result.known, RESULT.known)
        utils.assert_segmentlist_equal(result.active, RESULT.active)

        result2 = query_dqsegdb(self.TEST_CLASS.query_dqsegdb, name, (0, 10))
        utils.assert_flag_equal(result, result2)

        result2 = query_dqsegdb(self.TEST_CLASS.query_dqsegdb,
                                name, SegmentList([(0, 10)]))
        utils.assert_flag_equal(result, result2)

        with pytest.raises(ValueError):
            query_dqsegdb(self.TEST_CLASS.query_dqsegdb, 'BAD-FLAG_NAME',
                          SegmentList([(0, 10)]))

        with pytest.raises(HTTPError) as exc:
            query_dqsegdb(self.TEST_CLASS.query_dqsegdb,
                          'X1:GWPY-TEST:0', 0, 10)
        assert str(exc.value) == 'HTTP Error 404: Not found [X1:GWPY-TEST:0]'

        with pytest.raises(TypeError):
            self.TEST_CLASS.query_dqsegdb(QUERY_FLAGS[0], 1, 2, 3)
        with pytest.raises(TypeError):
            self.TEST_CLASS.query_dqsegdb(QUERY_FLAGS[0], (1, 2, 3))

    def test_query_dqsegdb_multi(self):
        segs = SegmentList([Segment(0, 2), Segment(8, 10)])
        result = query_dqsegdb(self.TEST_CLASS.query_dqsegdb,
                               QUERY_FLAGS[0], segs)
        RESULT = QUERY_RESULTC[QUERY_FLAGS[0]]

        assert isinstance(result, self.TEST_CLASS)
        utils.assert_segmentlist_equal(result.known, RESULT.known & segs)
        utils.assert_segmentlist_equal(result.active, RESULT.active & segs)

    def test_fetch_open_data(self):
        try:
            segs = self.TEST_CLASS.fetch_open_data(
                'H1_DATA', 946339215, 946368015)
        except (URLError, SSLError) as exc:
            pytest.skip(str(e))
        assert segs.ifo == 'H1'
        assert segs.name == 'H1:DATA'
        assert segs.label == 'H1_DATA'
        utils.assert_segmentlist_equal(segs.known, [(946339215, 946368015)])
        utils.assert_segmentlist_equal(segs.active, [
            (946340946, 946351799),
            (946356479, 946360619),
            (946362652, 946368015),
        ])


# -- DataQualityDict ----------------------------------------------------------

class TestDataQualityDict(object):
    TEST_CLASS = DataQualityDict
    ENTRY_CLASS = DataQualityFlag

    @classmethod
    def create(cls):
        flgd = cls.TEST_CLASS()
        flgd['X1:TEST-FLAG:1'] = cls.ENTRY_CLASS(name='X1:TEST-FLAG:1',
                                                 active=ACTIVE, known=KNOWN)
        flgd['Y1:TEST-FLAG:2'] = cls.ENTRY_CLASS(name='Y1:TEST-FLAG:2',
                                                 active=ACTIVE2, known=KNOWN2)
        return flgd

    @classmethod
    @pytest.fixture()
    def instance(cls):
        return cls.create()

    @classmethod
    @pytest.fixture()
    def reverse(cls):
        inst = cls.create()
        rev = type(inst)()
        keys = list(inst.keys())
        rev[keys[0]] = inst[keys[1]]
        rev[keys[1]] = inst[keys[0]]
        return rev

    # -- test logic -----------------------------

    def test_iand(self, instance, reverse):
        a = instance.copy()
        a &= reverse
        keys = list(a.keys())
        utils.assert_flag_equal(a[keys[0]],
                                instance[keys[0]] & reverse[keys[1]])

    def test_and(self, instance, reverse):
        a = instance.copy()
        a &= reverse
        utils.assert_dict_equal(a, instance & reverse, utils.assert_flag_equal)

    def test_ior(self, instance, reverse):
        a = instance.copy()
        a |= reverse
        keys = list(a.keys())
        utils.assert_flag_equal(a[keys[0]],
                                instance[keys[0]] | reverse[keys[1]])

    def test_or(self, instance, reverse):
        a = instance.copy()
        a |= reverse
        utils.assert_dict_equal(a, instance | reverse, utils.assert_flag_equal)

    def test_isub(self, instance, reverse):
        a = instance.copy()
        a -= reverse
        keys = list(a.keys())
        utils.assert_flag_equal(a[keys[0]],
                                instance[keys[0]] - reverse[keys[1]])

    def test_sub(self, instance, reverse):
        a = instance.copy(deep=True)
        a -= reverse
        utils.assert_dict_equal(a, instance - reverse, utils.assert_flag_equal)

    def test_xor(self, instance, reverse):
        a = instance.copy(deep=True)
        a ^= reverse
        utils.assert_dict_equal(a, instance ^ reverse, utils.assert_flag_equal)

    def test_invert(self, instance):
        inverse = type(instance)()
        for key in instance:
            inverse[key] = ~instance[key]
        utils.assert_dict_equal(~instance, inverse, utils.assert_flag_equal)

    # -- test methods ---------------------------

    def test_union(self, instance):
        union = instance.union()
        assert isinstance(union, self.ENTRY_CLASS)
        utils.assert_segmentlist_equal(union.known, KNOWN + KNOWN2)
        utils.assert_segmentlist_equal(union.active, ACTIVE + ACTIVE2)

    def test_intersection(self, instance):
        intersection = instance.intersection()
        assert isinstance(intersection, self.ENTRY_CLASS)
        utils.assert_segmentlist_equal(intersection.known, KNOWN & KNOWN2)
        utils.assert_segmentlist_equal(intersection.active, ACTIVE & ACTIVE2)

    def test_plot(self, instance):
        with rc_context(rc={'text.usetex': False}):
            plot = instance.plot(figsize=(6.4, 3.8))
            assert isinstance(plot, SegmentPlot)
            assert isinstance(plot.gca(), SegmentAxes)
            with tempfile.NamedTemporaryFile(suffix='.png') as f:
                plot.save(f.name)

    # -- test I/O -------------------------------

    @utils.skip_missing_dependency('lal')
    def test_from_veto_definer_file(self, veto_definer):
        # read veto definer
        vdf = self.TEST_CLASS.from_veto_definer_file(veto_definer)
        assert len(vdf.keys()) == 4

        # test one flag to make sure it is well read
        name = 'X1:TEST-FLAG:1'
        assert name in vdf
        utils.assert_segmentlist_equal(vdf[name].known,
                                       [(100, float('inf'))])
        assert vdf[name].category is 1
        assert vdf[name].padding == (-1, 2)

        # test ifo kwarg
        vdf = self.TEST_CLASS.from_veto_definer_file(veto_definer, ifo='X1')
        assert len(vdf.keys()) == 3
        assert 'Y1:TEST-FLAG_2:2' not in vdf

        # test start and end kwargs
        vdf = self.TEST_CLASS.from_veto_definer_file(veto_definer,
                                                     start=200, end=300)
        assert len(vdf.keys()) == 3
        assert 'X1:TEST-FLAG_2:1' not in vdf

    @pytest.mark.parametrize('format, ext, dep, rw_kwargs', [
        ('ligolw', 'xml', 'glue.ligolw.lsctables', {}),
        ('ligolw', 'xml.gz', 'glue.ligolw.lsctables', {}),
        ('hdf5', 'hdf5', 'h5py', {}),
        ('hdf5', 'h5', 'h5py', {}),
        ('hdf5', 'hdf5', 'h5py', {'path': 'test-dqdict'}),
    ])
    def test_read_write(self, instance, format, ext, dep, rw_kwargs):
        from importlib import import_module
        try:
            import_module(dep)
        except ImportError as e:
            pytest.skip(str(e))

        # define assertion
        def _assert(a, b):
            return utils.assert_dict_equal(a, b, utils.assert_flag_equal)

        # simplify calling read/write tester
        def _read_write(**kwargs):
            read_kw = rw_kwargs.copy()
            read_kw.update(kwargs.pop('read_kw', {}))
            write_kw = rw_kwargs.copy()
            write_kw.update(kwargs.pop('write_kw', {}))
            return utils.test_read_write(instance, format, extension=ext,
                                         assert_equal=_assert,
                                         read_kw=read_kw, write_kw=write_kw,
                                         **kwargs)

        _read_write(autoidentify=False)
        with pytest.raises(IOError):
            _read_write(autoidentify=True)
        _read_write(autoidentify=True, write_kw={'overwrite': True})

    # -- test queries ---------------------------

    @pytest.mark.parametrize('api', ('dqsegdb', 'segdb'))
    def test_query(self, api):
        if api == 'dqsegdb':
            result = query_dqsegdb(self.TEST_CLASS.query, QUERY_FLAGS,
                                   0, 10)
            RESULT = QUERY_RESULTC
        else:
            result = query_segdb(self.TEST_CLASS.query, QUERY_FLAGS,
                                 0, 10, url='https://geosegdb.does.not.exist')
            RESULT = QUERY_RESULT

        assert isinstance(result, self.TEST_CLASS)
        utils.assert_dict_equal(result, RESULT, utils.assert_flag_equal)

    def test_query_dqsegdb(self):
        result = query_dqsegdb(self.TEST_CLASS.query_dqsegdb, QUERY_FLAGS,
                               0, 10)
        RESULT = QUERY_RESULTC
        assert isinstance(result, self.TEST_CLASS)
        utils.assert_dict_equal(result, RESULT, utils.assert_flag_equal)

        # check all values of on_error
        with pytest.warns(UserWarning) as record:
            result = query_dqsegdb(self.TEST_CLASS.query_dqsegdb,
                                   QUERY_FLAGS + ['X1:BLAHBLAH:1'], 0, 10,
                                   on_error='warn')
            result = query_dqsegdb(self.TEST_CLASS.query_dqsegdb,
                                   QUERY_FLAGS + ['X1:BLAHBLAH:1'], 0, 10,
                                   on_error='ignore')
        utils.assert_dict_equal(result, RESULT, utils.assert_flag_equal)
        assert len(record) == 1  # check on_error='ignore' didn't warn
        with pytest.raises(ValueError):
            self.TEST_CLASS.query_dqsegdb(QUERY_FLAGS, 0, 10, on_error='blah')

    def test_query_segdb(self):
        result = query_segdb(self.TEST_CLASS.query_segdb, QUERY_FLAGS, 0, 10)
        assert isinstance(result, self.TEST_CLASS)
        utils.assert_dict_equal(result, QUERY_RESULT, utils.assert_flag_equal)

    @utils.skip_missing_dependency('lal')
    @utils.skip_missing_dependency('dqsegdb')
    def test_populate(self):
        def fake():
            return self.TEST_CLASS({
                x: self.ENTRY_CLASS(name=x, known=y.known) for
                x, y in QUERY_RESULT.items()})

        # build fake veto definer file
        vdf = fake()
        vdf2 = fake()
        vdf3 = fake()

        flag = QUERY_FLAGS[0]
        vdf2[flag].padding = (-1, 1)

        span = SegmentList([Segment(0, 2)])

        # and populate using a mocked query
        with mock.patch('dqsegdb.apicalls.dqsegdbQueryTimes',
                        mocks.dqsegdb_query_times(QUERY_RESULT)):
            vdf.populate()
            vdf2.populate()
            vdf3.populate(segments=span)

            # test warnings on bad entries
            vdf['TEST'] = self.ENTRY_CLASS('X1:BLAHBLAHBLAH:1', known=[(0, 1)])
            with pytest.warns(UserWarning) as record:
                vdf.populate(on_error='warn')
                vdf.populate(on_error='ignore')
            assert len(record) == 1
            vdf.pop('TEST')

            with pytest.raises(ValueError):
                vdf.populate(on_error='blah')

        # check basic populate worked
        utils.assert_dict_equal(vdf, QUERY_RESULTC, utils.assert_flag_equal)

        # check padded populate worked
        utils.assert_flag_equal(vdf2[flag], QUERY_RESULTC[flag].pad(-1, 1))

        # check segment-restricted populate worked
        for flag in vdf3:
            utils.assert_segmentlist_equal(
                vdf3[flag].known, QUERY_RESULTC[flag].known & span)
            utils.assert_segmentlist_equal(
                vdf3[flag].active, QUERY_RESULTC[flag].active & span)
