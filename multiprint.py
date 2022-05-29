import argparse
from audioop import mul
import os.path
import os
from urllib.parse import urlencode
import requests
import defusedxml.ElementTree
from utils import status, syscmd, ArgumentParser


def svg_to_pdf(svg_path, pdf_path):
    status.write('Convering multiprint page to PDF')

    # Print PDF to file
    if syscmd(f"google-chrome --headless --print-to-pdf --print-to-pdf-no-header {svg_path}") != 0:
        raise Exception(f"Failed to convert {svg_path} to PDF")

    # Chrome dumps 'output.pdf' and 'screenshot.png' in curdir
    if syscmd(f'mv output.pdf {pdf_path}') != 0:
        raise Exception(f'Failed to mv ./output.pdf to {pdf_path}')

    # Get rid of page SVG
    os.remove(svg_path)


def prepare_page(template_svg_path, output_svg_path, svg_paths):
    status.write('Preparing multiprint page')
    # Load SVG multiprint template and roots
    e = defusedxml.ElementTree.parse(template_svg_path)
    root = e.getroot()
    placard_groups = [
        root.find(f".//*[@id='placard{i}']") for i in range(1, 7)
    ]
    for placard_group, svg_path in zip(placard_groups, svg_paths):
        placard = defusedxml.ElementTree.parse(svg_path)
        placard_group.append(placard.getroot())

    e.write(output_svg_path)


def create_multiprint_pdf(svg_paths):
    out_dir = os.path.join(os.curdir, 'prepared/multiprint')
    os.makedirs(out_dir, exist_ok=True)
    template_svg_path = os.path.join(os.curdir, 'templates/multiprint_template.svg')
    page_svg_paths = []
    page_pdf_paths = []
    svg_paths_list = list(svg_paths)
    i = 0
    status.push('Preparing Multiprint PDF')
    while i < len(svg_paths_list):
        page = int(i/6)
        page_svg_paths.append(os.path.join(out_dir, f'page_{page+1}.svg'))
        page_pdf_paths.append(os.path.join(out_dir, f'page_{page+1}.pdf'))
        prepare_page(template_svg_path, page_svg_paths[page], svg_paths_list[i:i+6])
        svg_to_pdf(page_svg_paths[page], page_pdf_paths[page])
        i += 6
    status.pop()

    # Combine PDF pages.
    multiprint_pdf_path = os.path.join(out_dir, 'multiprint.pdf')
    syscmd(f'qpdf --empty --pages {" ".join(page_pdf_paths)} -- {multiprint_pdf_path}')
    for page_pdf in page_pdf_paths: os.remove(page_pdf)
    return multiprint_pdf_path    