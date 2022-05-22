#!/usr/bin/env python3

import argparse
import gcloud_helper
import os.path
import os
import simple_template
import re
from utils import Hashes, status

data_spreadsheet_id = '1jbha_NezYs8ONoTb29U4vIjH7LUzEJQauYeaf-Te93o'
data_spreadsheet_range = 'Placards!A2:E'
drive_shared_drive_id = '0ALUzUy2w2YeeUk9PVA'
drive_root_folder_id = '1syThtSUpFmP6vQ_erMh3BDGztN4qPEhD'

parser = argparse.ArgumentParser('Placard generator')
parser.add_argument('--sheet_id', default=data_spreadsheet_id,
                    help='Id of Google Sheet to read from')
parser.add_argument('--sheet_range', default=data_spreadsheet_range,
                    help='Range of Google Sheet to select')
parser.add_argument('--drive_root_folder_id', default=drive_root_folder_id,
                    help='Id of Google Drive folder used as Placards master folder')
parser.add_argument('--force', default=False,
                    action=argparse.BooleanOptionalAction, help='Force regeneration of the SVG placard even if no changes are detected.')
parser.add_argument('--debug', default=False,
                    action=argparse.BooleanOptionalAction, help='Do not overwrite status messages during execution')
parser.add_argument('--upload', default=True,
                    action=argparse.BooleanOptionalAction, help='Upload to Google Drive after generation')
parser.add_argument('--beer', default=None,
                    help='Only process beers with this exact name')


def main():

    args = parser.parse_args()
    status.debug(args.debug)

    gcloud = gcloud_helper.GCloud(args.drive_root_folder_id)
    gcloud.add_upload_folder('PNG', 'image/png')
    gcloud.add_upload_folder('SVG', 'image/svg+xml')
    gcloud.add_upload_folder('PDF', 'application/pdf')

    if args.upload:
        gcloud.init_drive()

    status.push("Processing")
    for row in gcloud.load_sheet(args.sheet_id, args.sheet_range):
        (brewer, beer, style, abv_str, logo_url) = row
        if args.beer is not None and args.beer != beer:
            continue

        status.push(f'{brewer} - {beer}')
        beer_dir = re.sub('[^a-zA-Z0-9_-]', '_',
                          f"{brewer.lower()}_{beer}".lower())
        placard_dir = os.path.join(os.path.curdir, 'prepared', beer_dir)
        os.makedirs(placard_dir, exist_ok=True)
        stem_path = os.path.join(placard_dir, 'placard')
        svg_path = f'{stem_path}.svg'
        png_path = f'{stem_path}.png'
        pdf_path = f'{stem_path}.pdf'

        hashes_file = os.path.join(placard_dir, 'hashes.md5')
        hashes = Hashes(hashes_file)

        # Hash input data
        hashes.add_blob('data', ",".join(row).encode('utf8'))
        hashes.add_file(svg_path)
        hashes.add_file(png_path)
        hashes.add_file(pdf_path)

        simple_template.process(
            args.force, placard_dir, svg_path, hashes, brewer, beer, style, abv_str, logo_url)

        redirect = '' if args.debug else ' > /dev/null 2>&1'
        if os.system(f"google-chrome --headless --window-size=278x278 --screenshot --hide-scrollbars {svg_path} {redirect}") != 0:
            raise Exception(f"Failed to convert {svg_path} to PNG")

        if os.system(f"google-chrome --headless --print-to-pdf --print-to-pdf-no-header {svg_path} {redirect}") != 0:
            raise Exception(f"Failed to convert {svg_path} to PDF")

        # Chrome dumps 'output.pdf' and 'screenshot.png' in curdir
        if os.system(f'mv output.pdf {pdf_path} {redirect}') != 0:
            raise Exception(f'Failed to mv ./output.pdf to {placard_dir}')
        if os.system(f'mv screenshot.png {png_path} {redirect}') != 0:
            raise Exception(f'Failed to mv ./screenshot.png to {placard_dir}')

        # Crop the PDF, as chrome saves with a bunch of extra whitespace.
        if os.system(f"pdfcrop {pdf_path} {pdf_path} {redirect}") != 0:
            raise Exception(
                f"Failed to crop {pdf_path}.  Do you have pdfcrop installed?")

        # Make the PDF hash stable by getting rid of metadata and dynamic ids
        pdf_path_cleansed = f'{pdf_path}.cleansed'
        if os.system(f'qpdf --static-id --pages {pdf_path} 1-z -- --empty {pdf_path_cleansed} ' +
                     f'&& qpdf --static-id {pdf_path_cleansed} {pdf_path} {redirect}') != 0:
            raise Exception(
                f'Failed to make pdf idempotent.  Do you have qpdf installed?')
        os.remove(pdf_path_cleansed)

        if args.upload:
            status.push("Uploading")
            gcloud.push_to_folder('PNG', brewer, beer,
                                  png_path, hashes.get_hash(png_path))
            gcloud.push_to_folder('PDF', brewer, beer,
                                  pdf_path, hashes.get_hash(pdf_path))
            gcloud.push_to_folder('SVG', brewer, beer,
                                  svg_path, hashes.get_hash(svg_path))
            status.pop()

        # Record everything that went into this run
        hashes.save()
        status.pop()
    status.pop()


if __name__ == '__main__':
    main()
