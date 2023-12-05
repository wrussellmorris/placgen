#!/usr/bin/env python3

import argparse
import gcloud_helper
import os.path
import os
import square_template
import re
from multiprint import create_multiprint_pdf
from utils import Hashes, make_hash_stable_pdf, status, ArgumentParser, syscmd, Site, PreparedPlacard

__placard_spreadsheet_id = '1jbha_NezYs8ONoTb29U4vIjH7LUzEJQauYeaf-Te93o'
__placard_spreadsheet_range = 'Placards!A2:H'
__multiprint_sheet_id = '1jbha_NezYs8ONoTb29U4vIjH7LUzEJQauYeaf-Te93o'
__multiprint_sheet_range = 'Multiprint!A2:A'
__drive_root_folder_id = '1syThtSUpFmP6vQ_erMh3BDGztN4qPEhD'


class GoldPan(Site):
    def __init__(self, prepared_dir):
        super().__init__('Gold Pan', prepared_dir)

    def _do_prepare_placard(self, brewer: str, beer: str, style: str, abv_str: str, logo_url: str, brewery_font_size: str, beer_font_size: str, style_font_size: str) -> PreparedPlacard:
        placard_dir = os.path.join(
            self.site_dir, self._safe_path(f'{brewer}_{beer}'))
        os.makedirs(placard_dir, exist_ok=True)
        return square_template.prepare_template(placard_dir, brewer, beer, style, abv_str, logo_url, brewery_font_size, beer_font_size, style_font_size, 0.82)


def main():
    parser = ArgumentParser()
    parser.add_argument('--upload', default=True,
                        action=argparse.BooleanOptionalAction, help='Upload to Google Drive after generation')
    parser.add_argument('--placard_sheet_id', default=__placard_spreadsheet_id,
                        help='Id of Google Sheet to read from')
    parser.add_argument('--placard_sheet_range', default=__placard_spreadsheet_range,
                        help='Tab and range of Google Sheet to select beers')
    parser.add_argument('--drive_root_folder_id', default=__drive_root_folder_id,
                        help='Id of Google Drive folder used as Placards master folder')
    parser.add_argument('--multiprint', default=False,
                        action=argparse.BooleanOptionalAction, help='Print all placards marked as "Print" in --multiprint_sheet_id, 6 per page')
    parser.add_argument('--multiprint_all', default=False,
                        action=argparse.BooleanOptionalAction, help='Print all placards, 6 per page')
    parser.add_argument('--multiprint_sheet_id', default=__multiprint_sheet_id,
                        help='Tab and range of Google Sheet to select beers to multiprint')
    parser.add_argument('--multiprint_sheet_range', default=__multiprint_sheet_range,
                        help='Tab and range of Google Sheet to select beers to multiprint')
    parser.add_argument('--site', default=None,
                        help='Only do work for the given site')
    args = parser.parse_args()

    status.debug(args.debug)

    if args.multiprint and args.site is None:
        print('Must specify --site when using --multiprint')
        return

    prepared_dir = os.path.join(os.curdir, 'prepared')
    os.makedirs(prepared_dir, exist_ok=True)

    all_sites = [GoldPan(prepared_dir)]
    sites = list(
        filter(lambda site: args.site is None or args.site == site.name, all_sites))

    gcloud = gcloud_helper.GCloud(args.drive_root_folder_id, sites)

    multiprint_outputs = set()
    multiprint_selected = []
    if args.multiprint:
        multiprint_selected = [
            row[0] == 'TRUE' for row in gcloud.load_sheet(
                args.multiprint_sheet_id, args.multiprint_sheet_range, 1)]

    status.push("Preparing placards")
    beer_index = 0

    for row in gcloud.load_sheet(args.placard_sheet_id, args.placard_sheet_range, 8):
        (brewer, beer, style, abv_str, logo_url, brewery_font_size, beer_font_size, style_font_size) = row
        if args.beer is not None and args.beer != beer:
            beer_index += 1
            continue

        status.push(f'{brewer} - {beer}')
        for site in sites:
            if args.site is not None and args.site != site.name:
                continue

            status.push(site.name)
            prepared_placard = site.prepare_placard(
                brewer, beer, style, abv_str, logo_url, brewery_font_size, beer_font_size, style_font_size)
            # Add to multiprint, if necessary
            if args.multiprint and args.site == site.name and (multiprint_selected[beer_index] or args.multiprint_all):
                status.write(f"multiprinting {beer}" )
                multiprint_outputs.add(prepared_placard)
            status.pop()

        status.pop()
        beer_index += 1

    status.pop()

    if args.upload:
        gcloud.upload()

    if (args.multiprint and len(multiprint_outputs) > 0):
        # Call multiprint
        multiprint_pdf_path = create_multiprint_pdf(
            [output.output_files['SVG'].file_path for output in multiprint_outputs])
        syscmd(f'google-chrome {multiprint_pdf_path}')


if __name__ == '__main__':
    main()
