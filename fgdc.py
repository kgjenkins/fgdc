"""FGDC metadata enhancement."""

import json
import os
import re
from datetime import date
from collections import OrderedDict
from io import StringIO
import fiona
import fiona.crs
from pyproj import Transformer
import rasterio
import requests
from lxml import etree


def enhance(xmlfilename, datafilename):
    """Enhance the fgdc metadata (xmlfile) using info from datafile and return the new xml as a string."""

    # get extension of data file (shp, tif)
    ext = datafilename.split('.')[-1]

    with open(xmlfilename, 'r') as f:
        # parse the xml string
        try:
          parser = etree.XMLParser(remove_blank_text=True)
          tree = etree.parse(f, parser=parser)
        except:
          print('error parsing xml file {}'.format(xmlfilename))

    tree = _update_geoform(tree, ext)
    #tree = _update_onlink(tree, d) -- only when adding to CUGIR
    tree = _update_category(tree)
    #tree = _update_browse(tree, d) -- only when adding to CUGIR
    tree = _update_spdoinfo(tree, ext, datafilename)
    #tree = _update_bounding(tree, d) -- included in _update_spdoinfo

    # TODO normalize <spref> (coordinate system)
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


def _update_category(tree):
    """Add or update CUGIR categories (human-readable variant of ISO Topic Category)."""
    t2c = {
        "farming": "agriculture",
        "biota": "biology",
        "boundaries": "boundaries",
        "climatologymeteorologyatmosphere": "climate",
        "economy": "economy",
        "elevation": "elevation",
        "environment": "environment",
        "geoscientificinformation": "geology",
        "health": "health",
        "imagery": "imagery",
        "index map": "index map",
        "basemaps": "basemaps",
        "land cover": "landcover",
        "landcover": "landcover",
        "intelligencemilitary": "military",
        "inlandwaters": "inland waters",
        "location": "location",
        "oceans": "oceans",
        "planningcadastre": "property",
        "society": "society",
        "soils": "geology",
        "structure": "structure",
        "transportation": "transportation",
        "utilitiescommunication": "utilities"
        }
    themekeys = tree.findall('.//themekey')
    categories = []
    for t in themekeys:
        c = t2c.get(t.text.lower(), None)
        if c and not c in categories:
            categories.append(c)

    # remove any existing CUGIR Category -- TODO reconsider this
    _remove_path(tree, './/theme[themekt/text()="CUGIR Category"]')

    if len(categories) == 0:
        print('warning: unable to determine CUGIR category')
    else:
        themekeys = '\n'.join(["<themekey>{}</themekey>".format(c) for c in categories])
        theme = """
            <theme>
              <themekt>CUGIR Category</themekt>
              {}
            </theme>""".format(themekeys)
        _insert_after_last(tree.find('idinfo/keywords'), theme, 'theme')
    return tree

def _update_browse(tree, d):
    """Add browse graphic (preview thumbnail image)"""
    _remove_path(tree, './/browse')
    if d.local_preview:
        browseurl = 'https://{}.s3.amazonaws.com/{}preview.png'.format(config.s3_bucket, d.prefix)
        browse = """
            <browse>
              <browsen>{}</browsen>
              <browsed>preview of the dataset</browsed>
              <browset>PNG</browset>
            </browse>""".format(browseurl)
        _insert_after_last(tree.find('idinfo'), browse, 'keywords|accconst|useconst|ptcontac')
    return tree

def _update_spdoinfo(tree, ext, datafilename):
    """Update spdoinfo (geomtype, raster/vector)"""
    # handle different data formats
    if ext in 'shp e00 geojson'.split(' '):
        print('updating vector spdoinfo')
        return _update_vector_spdoinfo(tree, datafilename)
    elif ext in 'tif'.split(' '):
        print('updating raster spdoinfo')
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
    _insert_after_last(tree.getroot(), spdoinfo, 'idinfo|dataqual')

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
    _insert_after_last(tree.getroot(), spdoinfo, 'idinfo|dataqual')

    tree = _update_bounding(tree, rasteriosource)

    return tree


def _update_bounding(tree, source):
    """Update spdom/bounding with WGS84 bounds via fiona/rasterio (source)."""
    bounds = source.bounds
    print(bounds)

    # convert bounds to EPSG:4326 as necessary
    crs = source.crs
    if crs['init'] != 'epsg:4326':
        t = Transformer.from_crs(crs, 4326, always_xy=True)
        ws = t.transform(bounds[0], bounds[1])
        en = t.transform(bounds[2], bounds[3])
        print(ws, en)
        bounds = (*ws, *en)

    print(bounds)

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


def _update_distinfo(tree, d):
    """Update Mann Libary's <distinfo> section with contact info, download links, wms/wfs.

    This should replace any existing Mann distinfo seciton, or add one as necessary.
    This should not affect any non-Mann distinfo sections.
    """

    id = d.id
    _remove_path(tree, './distinfo[.//cntorg[contains(text(),"Mann Library")]]')

    # TODO put cntinfo into config
    distinfo = """
      <distinfo>
        <distrib>
          <cntinfo>
            <cntorgp>
              <cntorg>Albert R. Mann Library</cntorg>
            </cntorgp>
            <cntaddr>
              <addrtype>mailing and physical</addrtype>
              <address>Cornell University</address>
              <city>Ithaca</city>
              <state>New York</state>
              <postal>14853</postal>
            </cntaddr>
            <cntvoice>607-255-5406</cntvoice>
            <cntemail>mann-ref@cornell.edu</cntemail>
          </cntinfo>
        </distrib>
        <distliab>Cornell University provides these geographic data "as is". Cornell
          University makes no guarantee or warranty concerning the accuracy of
          information contained in the geographic data. Cornell University further
          makes no warranty either expressed or implied, regarding the condition of
          the product or its fitness for any particular purpose. The burden for
          determining fitness for use lies entirely with the user. Although these
          files have been processed successfully on computers at Cornell University,
          no warranty is made by Cornell University regarding the use of these data
          on any other system, nor does the fact of distribution constitute or imply
          any such warranty.</distliab>
        <stdorder>
        </stdorder>
      </distinfo>
      """
    _insert_after_last(tree.getroot(), distinfo, 'idinfo|dataqual|spdoinfo|spref|eainfo')
    stdorder = tree.xpath('distinfo/stdorder')[0]

    # try to calculate zip size (in MB)
    zipfile = os.path.join(d.temp_path, 'cugir-{}.zip'.format(id))
    if os.path.isfile(zipfile):
        # add 0.01 so that it is not zero
        transize = '{0:.2f}'.format(0.01 + os.stat(zipfile).st_size/1024.0/1024)
    else:
        transize = 'unknown'
        # TODO ideally, omit the <transize> element in this case

    if d.ext == 'shp':
        # we can't just use d.s3_zip because it may not exist yet
        url = 'https://{}.s3.amazonaws.com/{}cugir-{}.zip'.format(config.s3_bucket, d.prefix, d.id)
        digform = """
          <digform>
            <digtinfo>
              <formname>Shapefile</formname>
              <formcont>zipped shapefile</formcont>
              <filedec>zip</filedec>
              <transize>{}</transize>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(transize, url)
        stdorder.append(etree.fromstring(digform))

    if d.ext == 'geojson':
        # This assumes all geojson files are named thusly
        url = 'https://{}.s3.amazonaws.com/{}cugir-{}-index.geojson'.format(config.s3_bucket, d.prefix, d.id)
        digform = """
          <digform>
            <digtinfo>
              <formname>GeoJSON</formname>
              <formcont>OpenIndexMaps</formcont>
              <transize>{}</transize>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(transize, url)
        stdorder.append(etree.fromstring(digform))

    elif d.ext == 'tif':
        # we can't just use d.s3_zip because it may not exist yet
        url = 'https://{}.s3.amazonaws.com/{}cugir-{}.zip'.format(config.s3_bucket, d.prefix, d.id)
        digform = """
          <digform>
            <digtinfo>
              <formname>GeoTIFF</formname>
              <formcont>zipped geotiff</formcont>
              <filedec>zip</filedec>
              <transize>{}</transize>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(transize, url)
        stdorder.append(etree.fromstring(digform))

    elif d.ext == 'e00':
        # we can't just use d.s3_zip because it may not exist yet
        url = 'https://{}.s3.amazonaws.com/{}cugir-{}.zip'.format(config.s3_bucket, d.prefix, d.id)
        digform = """
          <digform>
            <digtinfo>
              <formname>E00</formname>
              <formcont>zipped Arc/Info .e00 file</formcont>
              <filedec>zip</filedec>
              <transize>{}</transize>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(transize, url)
        stdorder.append(etree.fromstring(digform))

    # always include metadata xml
    url = 'https://{}.s3.amazonaws.com/{}fgdc.xml'.format(config.s3_bucket, d.prefix)
    digform = """
          <digform>
            <digtinfo>
              <formname>metadata</formname>
              <formcont>FGDC XML metadata</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(url)
    stdorder.append(etree.fromstring(digform))

    # always include metadata html
    url = 'https://{}.s3.amazonaws.com/{}fgdc.html'.format(config.s3_bucket, d.prefix)
    digform = """
          <digform>
            <digtinfo>
              <formname>HTML metadata</formname>
              <formcont>FGDC HTML metadata</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(url)
    stdorder.append(etree.fromstring(digform))

    # Special handling for NYS Ag&Markets Ag Districts
    #   - link to agALBA.pdf and agALBA2015.kmz directly on s3
    kml = False
    # we sort by extension so that the PDF always comes before the KML
    for f in sorted(d.temp_files, key=lambda x: x.split('.')[-1], reverse=True):
        ff = os.path.split(f)[1]

        if re.match(r'ag[A-Z]{4}(2\d{3})?\.pdf', ff):
            url = 'https://{}.s3.amazonaws.com/{}{}'.format(config.s3_bucket, d.prefix, ff)
            digform = """
          <digform>
            <digtinfo>
              <formname>PDF</formname>
              <formcont>prepared PDF map</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(url)
            stdorder.append(etree.fromstring(digform))

        if re.match(r'ag[A-Z]{4}(2\d{3})?\.kmz', ff):
            kml = True
            url = 'https://{}.s3.amazonaws.com/{}{}'.format(config.s3_bucket, d.prefix, ff)
            digform = """
          <digform>
            <digtinfo>
              <formname>KML</formname>
              <formcont>zipped KML file</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(url)
            stdorder.append(etree.fromstring(digform))

    if d.ext == 'shp':

        # kml -- only show if there is not already a custom kmz file (as in NYS Ag Districts)
        if not kml:
            kml = '{}cugir/wfs?version=1.0.0&amp;request=GetFeature&amp;typeName={}&amp;outputFormat=application%2Fvnd.google-earth.kml%2Bxml'.format(config.geoserver_base, d.postgres)
            digform = """
              <digform>
                <digtinfo>
                  <formname>KML</formname>
                  <formcont>generated KML, via WFS</formcont>
                </digtinfo>
                <digtopt>
                  <onlinopt>
                    <computer>
                      <networka>
                        <networkr>{}</networkr>
                      </networka>
                    </computer>
                  </onlinopt>
                </digtopt>
              </digform>""".format(kml)
            stdorder.append(etree.fromstring(digform))

        # geojson -- offer shapefile vectors as geojson via WFS
        geojson = '{}cugir/wfs?version=1.0.0&amp;request=GetFeature&amp;typeName={}&amp;outputFormat=application%2Fjson'.format(config.geoserver_base, d.postgres)
        digform = """
          <digform>
            <digtinfo>
              <formname>GeoJSON</formname>
              <formcont>generated GeoJSON, via WFS</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(geojson)
        stdorder.append(etree.fromstring(digform))


    # wms
    bbox = d.bbox()
    #if bbox is not None:
    # this should really check for d.geoserver instead
    if d.geoserver:
        bboxwidth = bbox[2] - bbox[0]
        bboxheight = bbox[3] - bbox[1]

        # Add 3% margin
        bbox[0] -= bboxwidth*0.03
        bbox[2] += bboxwidth*0.03
        bbox[1] -= bboxheight*0.03
        bbox[3] += bboxheight*0.03

        # For the WMS url, we need the bbox as a comma-delimited string
        bboxstr = ','.join([str(a) for a in bbox])

        # Assign 256 to longest side, and scale other dimension proportionally
        if bboxheight > bboxwidth:
            height = 256
            width = int(height * bboxwidth / bboxheight)
        else:
            width = 256
            height = int(width * bboxheight/ bboxwidth)

        # TODO this url could also be used for a browse graphic (idinfo/browsen)
        wms = '{}cugir/wms?version=1.1.0&amp;request=GetMap&amp;layers=cugir{}&amp;bbox={}&amp;width={}&amp;height={}&amp;srs=EPSG:4326&amp;format=image/png'.format(config.geoserver_base, d.id, bboxstr, width, height)

        digform = """
          <digform>
            <digtinfo>
              <formname>OGC:WMS</formname>
              <formcont>WMS, from GeoServer</formcont>
            </digtinfo>
            <digtopt>
              <onlinopt>
                <computer>
                  <networka>
                    <networkr>{}</networkr>
                  </networka>
                </computer>
              </onlinopt>
            </digtopt>
          </digform>""".format(wms)
        stdorder.append(etree.fromstring(digform))

    tree.xpath('distinfo/stdorder')[0].append(etree.fromstring('<fees>None</fees>'))
    return tree


def _update_metainfo(tree):
    """Update metadata with Mann contact info and today's date."""
    _remove_path(tree, './metainfo')
    metainfo = etree.fromstring("""
    <metainfo>
      <metd>{}</metd>
      <metc>
        <cntinfo>
          <cntorgp>
            <cntorg>Albert R. Mann Library</cntorg>
          </cntorgp>
          <cntaddr>
            <addrtype>mailing and physical</addrtype>
            <address>Albert R. Mann Library</address>
            <city>Ithaca</city>
            <state>New York</state>
            <postal>14853</postal>
            <country>USA</country>
          </cntaddr>
          <cntvoice>607-255-5406</cntvoice>
          <cntemail>mann-ref@cornell.edu</cntemail>
        </cntinfo>
      </metc>
      <metstdn>FGDC Content Standard for Digital Geospatial Metadata</metstdn>
      <metstdv>FGDC-STD-001-1998</metstdv>
      <mettc>local time</mettc>
    </metainfo>""".format(date.today().strftime('%Y%m%d')))

    # insert at end of metadata
    tree.getroot().append(metainfo)
    return tree
