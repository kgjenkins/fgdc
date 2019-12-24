"""FGDC metadata enhancement."""

"""
usage: fgdc-cli.py [-h] [-o OUT] xml data

Enhance an FGDC XML file with metadata from a geospatial data file.

positional arguments:
  xml                   the original XML file containing FGDC CSDGM metadata
  data                  the geospatial data file (.shp or .tif)

optional arguments:
  -h, --help            show this help message and exit
  -o OUT, --out OUT     output xml file
"""

import argparse
import sys
import fgdc

argparser = argparse.ArgumentParser(
    description='Enhance an FGDC XML file with metadata from a geospatial data file.'
    )
argparser.add_argument(
    'xml',
    type=argparse.FileType('r'),
    help='the original XML file containing FGDC CSDGM metadata'
    )
argparser.add_argument(
    'data',
    type=str,
    help='the geospatial data file (.shp or .tif)'
    )
argparser.add_argument(
    '-o', '--out',
    type=argparse.FileType('w'),
    default=sys.stdout, help='output xml file'
    )

args = argparser.parse_args()

xml = fgdc.enhance(args.xml.read(), args.data)
args.out.write(xml)

if (args.out.name != '<stdout>'):
    print('Enhanced xml written to file {}'.format(args.out.name))
