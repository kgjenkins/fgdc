"""FGDC metadata enhancement."""

from datetime import date
from io import StringIO
import fiona
from pyproj import Transformer
from pyproj import CRS
import rasterio
from lxml import etree


def enhance(xml, datafile):
    """Enhance the xml string (containing fgdc metadata)
    using info from the datafile
    and return the new xml as a string."""

    # get extension of data file (shp, tif)
    ext = datafile.split('.')[-1]

    try:
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml, parser=parser)
    except:
        print('error parsing xml string {}'.format(xml))
        return xml

    tree = _update_geoform(tree, ext)
    tree = _update_spatial(tree, ext, datafile)
    tree = _update_metadata_date(tree)

    # These are CUGIR-specific
    #tree = _update_category(tree)
    #tree = _update_browse(tree, d)
    #tree = _update_distinfo(tree, d)
    #tree = _update_metainfo(tree)

    # prettify and return the enhanced xml string
    doctype = '<!DOCTYPE metadata SYSTEM "http://fgdc.gov/metadata/fgdc-std-001-1998.dtd">'
    xml = etree.tostring(tree, encoding='unicode', pretty_print=True, doctype=doctype)
    return xml


def _remove_path(tree, xpath):
    """Remove whatever matches xpath from the tree."""
    matches = tree.xpath(xpath)
    for m in matches:
      m.getparent().remove(m)


def _insert_after_last(tree, xmlstr, tags):
    """Insert the xmlstr after the last existing tag.

    tags should be a pipe-delimited list of tagnames, and at least one
    should be required and present."""

    existing = tree.xpath(tags)
    assert len(existing) > 0, 'FGDC metadata lacks one of {}'.format(tags)
    parser = etree.XMLParser(remove_blank_text=True)
    newnode = etree.fromstring(xmlstr, parser=parser)
    existing[-1].addnext(newnode)
    return tree


def _update_geoform(tree, ext):
    """Set geoform based on the data filetype"""
    ext2geoform = {
        'shp': 'vector digital data',
        'tif': 'raster digital data',
        'e00': 'vector digital data',
        'geojson': 'vector digital data'
        }
    g = ext2geoform.get(ext, None)
    if g is None:
        print('fgdc: WARNING: unable to determine geoform for file type {}'.format(ext))
        return tree

    citeinfo = tree.find('./idinfo/citation/citeinfo')
    geoform = citeinfo.find('geoform')

    # remove any existing geoform
    if geoform is not None:
        geoform.getparent().remove(geoform)

    _insert_after_last(citeinfo, '<geoform>{}</geoform>'.format(g), 'title|edition')

    return tree


def _update_spatial(tree, ext, datafilename):
    """Update spdoinfo (geomtype, raster/vector)"""
    # handle different data formats
    if ext in 'shp e00 geojson'.split(' '):
        return _update_vector_spdoinfo(tree, datafilename)
    elif ext in 'tif'.split(' '):
        return _update_raster_spdoinfo(tree, datafilename)
    else:
        return tree


def _update_vector_spdoinfo(tree, datafilename):
    """Update spdoinfo for vector datasets, via fiona."""
    try:
        fionasource = fiona.open(datafilename)
    except:
        print('fiona error trying to open {}'.format(datafilename))
        return tree

    # get geometry type and convert to FGDC term as necessary
    geomtype = fionasource.schema['geometry']

    # warn on 3D or multitypes, which might not be intentional
    if 'Multi' in geomtype or '3D' in geomtype:
        print('WARNING: geomtype is ', geomtype)

    # get feature count
    count = str(len(fionasource))

    _remove_path(tree, './spdoinfo')
    spdoinfo = f"""
      <spdoinfo>
        <direct>Vector</direct>
        <ptvctinf>
          <sdtsterm>
            <sdtstype>{geomtype}</sdtstype>
            <ptvctcnt>{count}</ptvctcnt>
          </sdtsterm>
        </ptvctinf>
      </spdoinfo>"""
    _insert_after_last(tree, spdoinfo, 'idinfo|dataqual')

    tree = _update_bounding(tree, fionasource)
    return tree


def _update_raster_spdoinfo(tree, datafilename):
    """Update spdoinfo for raster datasets, via fiona."""
    try:
        rasteriosource = rasterio.open(datafilename)
    except:
        print('rasterio error trying to open {}'.format(datafilename))
        return tree

    cols = rasteriosource.width
    rows = rasteriosource.height

    _remove_path(tree, './spdoinfo')
    spdoinfo = """
      <spdoinfo>
        <direct>Raster</direct>
        <rastinfo>
          <rasttype>Grid Cell</rasttype>
          <rowcount>{}</rowcount>
          <colcount>{}</colcount>
        </rastinfo>
      </spdoinfo>""".format(rows, cols)
    _insert_after_last(tree, spdoinfo, 'idinfo|dataqual')

    tree = _update_bounding(tree, rasteriosource)

    return tree


def _update_bounding(tree, source):
    """Update spdom/bounding with WGS84 bounds via fiona/rasterio (source)."""
    bounds = source.bounds

    crs = source.crs
    tree = _update_spref(tree, crs)

    # convert bounds to EPSG:4326 as necessary
    if crs['init'] != 'epsg:4326':
        t = Transformer.from_crs(crs, 4326, always_xy=True)
        ws = t.transform(bounds[0], bounds[1])
        en = t.transform(bounds[2], bounds[3])
        bounds = (*ws, *en)

    _remove_path(tree, './idinfo/spdom')

    # make sure bbox sides are at least .001
    # (which will force preview map zoom to a visible level)
    if (bounds[2] - bounds[0]) < 0.001:
        bounds[0] -= 0.0005
        bounds[2] += 0.0005
    if (bounds[3] - bounds[1]) < 0.001:
        bounds[1] -= 0.0005
        bounds[3] += 0.0005

    spdom = """
        <spdom>
          <bounding>
            <westbc>{}</westbc>
            <eastbc>{}</eastbc>
            <northbc>{}</northbc>
            <southbc>{}</southbc>
          </bounding>
        </spdom>""".format(bounds[0], bounds[2], bounds[3], bounds[1]) # note the fgdc order!
    _insert_after_last(tree.find('idinfo'), spdom, 'status')

    return tree


def _update_spref(tree, crs):
    """Update spref with standard CRS info for epsg codes we recognize."""
    spref = ''
    init = crs['init']
    if init == 'epsg:4326':
        # WGS84
        spref = """
            <spref>
              <horizsys>
                <geograph>
                  <latres>0.000001</latres>
                  <longres>0.000001</longres>
                  <geogunit>Decimal degrees</geogunit>
                </geograph>
                <geodetic>
                  <horizdn>D_WGS_1984</horizdn>
                  <ellips>WGS_1984</ellips>
                  <semiaxis>6378137.000000</semiaxis>
                  <denflat>298.257224</denflat>
                </geodetic>
              </horizsys>
            </spref>"""
    elif init == 'epsg:4269':
        # NAD83
        spref = """
            <spref>
              <horizsys>
                <geograph>
                  <latres>0.000001</latres>
                  <longres>0.000001</longres>
                  <geogunit>Decimal degrees</geogunit>
                </geograph>
                <geodetic>
                  <horizdn>North American Datum of 1983</horizdn>
                  <ellips>GRS1980</ellips>
                  <semiaxis>6378137.0</semiaxis>
                  <denflat>298.257222</denflat>
                </geodetic>
              </horizsys>
            </spref>"""
    elif init == 'epsg:2261':
        # NAD83 State Plane New York Central feet
        spref = """
            <spref>
              <horizsys>
                <planar>
                  <gridsys>
                    <gridsysn>State Plane Coordinate System 1983</gridsysn>
                    <spcs>
                      <spcszone>3102</spcszone>
                      <transmer>
                        <sfctrmer>0.9999375</sfctrmer>
                        <longcm>-76.5833333334</longcm>
                        <latprjo>40</latprjo>
                        <feast>250000</feast>
                        <fnorth>0</fnorth>
                      </transmer>
                    </spcs>
                  </gridsys>
                  <planci>
                    <plance>Coordinate Pair</plance>
                    <coordrep>
                      <absres>1</absres>
                      <ordres>1</ordres>
                    </coordrep>
                    <plandu>US survey feet</plandu>
                  </planci>
                </planar>
                <geodetic>
                  <horizdn>North American Datum of 1983</horizdn>
                  <ellips>Geodetic Reference System 80</ellips>
                  <semiaxis>6378206</semiaxis>
                  <denflat>294.9786982</denflat>
                </geodetic>
              </horizsys>
            </spref>"""
    elif init == 'epsg:26718':
        # NAD27 UTM zone 18N
        spref = """
          <spref>
            <horizsys>
              <planar>
                <gridsys>
                  <gridsysn>Universal Transverse Mercator</gridsysn>
                  <utm>
                    <utmzone>18</utmzone>
                    <transmer>
                      <sfctrmer>0.999600</sfctrmer>
                      <longcm>-75.000000</longcm>
                      <latprjo>0.000000</latprjo>
                      <feast>500000.000000</feast>
                      <fnorth>0.000000</fnorth>
                    </transmer>
                  </utm>
                </gridsys>
                <planci>
                  <plance>coordinate pair</plance>
                  <coordrep>
                    <absres>0.000256</absres>
                    <ordres>0.000256</ordres>
                  </coordrep>
                  <plandu>meters</plandu>
                </planci>
              </planar>
              <geodetic>
                <horizdn>North American Datum of 1927</horizdn>
                <ellips>Clarke 1866</ellips>
                <semiaxis>6378206.400000</semiaxis>
                <denflat>294.978698</denflat>
              </geodetic>
            </horizsys>
          </spref>"""
    elif init == 'epsg:26918':
        # NAD83 UTM zone 18N
        spref = """
          <spref>
            <horizsys>
              <planar>
                <gridsys>
                  <gridsysn>Universal Transverse Mercator</gridsysn>
                  <utm>
                    <utmzone>18</utmzone>
                    <transmer>
                      <sfctrmer>0.999600</sfctrmer>
                      <longcm>-75.000000</longcm>
                      <latprjo>0.000000</latprjo>
                      <feast>500000.000000</feast>
                      <fnorth>0.000000</fnorth>
                    </transmer>
                  </utm>
                </gridsys>
                <planci>
                  <plance>coordinate pair</plance>
                  <coordrep>
                    <absres>0.000512</absres>
                    <ordres>0.000512</ordres>
                  </coordrep>
                  <plandu>meters</plandu>
                </planci>
              </planar>
              <geodetic>
                <horizdn>North American Datum of 1983</horizdn>
                <ellips>Geodetic Reference System 80</ellips>
                <semiaxis>6378137.000000</semiaxis>
                <denflat>298.257222</denflat>
              </geodetic>
            </horizsys>
          </spref>"""
    elif init == 'epsg:32618':
        # WGS84 UTM zone 18N
        spref = """
          <spref>
            <horizsys>
              <planar>
                <gridsys>
                  <gridsysn>Universal Transverse Mercator</gridsysn>
                  <utm>
                    <utmzone>18</utmzone>
                    <transmer>
                      <sfctrmer>0.999600</sfctrmer>
                      <longcm>-75.000000</longcm>
                      <latprjo>0.000000</latprjo>
                      <feast>500000.000000</feast>
                      <fnorth>0.000000</fnorth>
                    </transmer>
                  </utm>
                </gridsys>
                <planci>
                  <plance>coordinate pair</plance>
                  <coordrep>
                    <absres>0.000000</absres>
                    <ordres>0.000000</ordres>
                  </coordrep>
                  <plandu>meters</plandu>
                </planci>
              </planar>
              <geodetic>
                <horizdn>D_WGS_1984</horizdn>
                <ellips>WGS_1984</ellips>
                <semiaxis>6378137.000000</semiaxis>
                <denflat>298.257224</denflat>
              </geodetic>
            </horizsys>
          </spref>"""
    else:
        # The above covers many CRS in New York, but for any others,
        # we'll at least provide the EPSG code and proj4 definition
        crs = CRS.from_string(init)
        spref = """
            <spref>
              <horizsys>
                <local>
                  <localdes>{}</localdes>
                  <localgeo>{}</localgeo>
                </local>
              </horizsys>
            </spref>""".format(crs.to_string(), crs.to_wkt())

    if spref:
        _remove_path(tree, './spref')
        _insert_after_last(tree, spref, 'idinfo|dataqual|spdoinfo')
    return tree



def _update_metadata_date(tree):
    """Update metadata with today's date."""
    metd = tree.find('./metainfo/metd')
    metd.text = date.today().strftime('%Y%m%d')
    return tree
