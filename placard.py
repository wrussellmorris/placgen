#!/usr/bin/env python3

import argparse
import gcloud_helper
import os.path
import os
import simple_template
import re
from multiprint import create_multiprint_pdf
from utils import Hashes, make_hash_stable_pdf, status, ArgumentParser, syscmd

__placard_spreadsheet_id = '1jbha_NezYs8ONoTb29U4vIjH7LUzEJQauYeaf-Te93o'
__placard_spreadsheet_range = 'Placards!A2:E'
__multiprint_sheet_id = '1jbha_NezYs8ONoTb29U4vIjH7LUzEJQauYeaf-Te93o'
__multiprint_sheet_range = 'Multiprint!A2:A'
__drive_root_folder_id = '1syThtSUpFmP6vQ_erMh3BDGztN4qPEhD'


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
    args = parser.parse_args()

    status.debug(args.debug)

    gcloud = gcloud_helper.GCloud(args.drive_root_folder_id)

    multiprint_outputs = set()
    multiprint_selected = []
    if args.multiprint:
        multiprint_selected = [
            row[0] == 'TRUE' for row in gcloud.load_sheet(
                args.multiprint_sheet_id, args.multiprint_sheet_range, 1)]

    status.push("Processing")
    beer_index = 0

    prepared = []
    for row in gcloud.load_sheet(args.placard_sheet_id, args.placard_sheet_range, 5):
        (brewer, beer, style, abv_str, logo_url) = row
        if args.beer is not None and args.beer != beer:
            continue

        status.push(f'{brewer} - {beer}')
        beer_dir = re.sub('[^a-zA-Z0-9_-]', '_',
                          f"{brewer.lower()}_{beer}".lower())
        placard_dir = os.path.join(os.path.curdir, 'prepared', beer_dir)
        os.makedirs(placard_dir, exist_ok=True)

        prepared.append(simple_template.prepare_template(placard_dir, brewer, beer, style, abv_str, logo_url))

        # Add to multiprint, if necessary
        if args.multiprint and beer_index < len(multiprint_selected) and (multiprint_selected[beer_index] or args.multiprint_all):
            multiprint_outputs.add(prepared[-1])
        status.pop()
        beer_index += 1
    status.pop()

    if args.upload:
        status.push("Uploading")

        gcloud.add_upload_folder('PNG', 'image/png')
        gcloud.add_upload_folder('SVG', 'image/svg+xml')
        gcloud.add_upload_folder('PDF', 'application/pdf')
        gcloud.init_drive()

        for placard in prepared:
            for output in placard.output_files:
                status.write(f'output {output.type} {placard.brewer} {placard.beer} {output.file_path} {output.get_hash()}')
                gcloud.push_to_folder(output.type, placard.brewer, placard.beer,
                                        output.file_path, output.get_hash())
        status.pop()

    if (args.multiprint and len(multiprint_outputs) > 0):
        # Call multiprint
        multiprint_pdf_path = create_multiprint_pdf([output.svg_output.file_path for output in multiprint_outputs])
        syscmd(f'google-chrome {multiprint_pdf_path}')


if __name__ == '__main__':
    main()
