"""FGDC metadata enhancement."""

import argparse
import sys
from pprint import pprint
import fgdcstuff

argparser = argparse.ArgumentParser(description='Enhance an FGDC XML file with metadata from a geospatial data file.')
argparser.add_argument('fgdc', type=str, help='the original XML file containing FGDC CSDGM metadata')
argparser.add_argument('data', type=str, help='the geospatial data file (.shp or .tif)')
argparser.add_argument('-o', '--output', type=argparse.FileType('w'), default=sys.stdout, help='output xml file')
args = argparser.parse_args()

pprint(args)

fgdcstuff.enhance(xml)


