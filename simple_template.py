import argparse
import base64
import os.path
import os
import re
from urllib.parse import urlencode
import requests
import defusedxml.ElementTree
from utils import Hashes, status

template_name = 'simple_template.svg'


def PathDToList(d_string):
    if d_string == None or d_string == '':
        return []
    return [e.split(',') for e in d_string.split(' ')]


def ListToPathD(d_list):
    if len(d_list) == 0:
        return ''
    return ' '.join([','.join(e) for e in d_list])


def StyleToDict(style_string):
    if style_string == None or style_string == '':
        return {}
    return {t[0]: t[1] for t in (e.split(':') for e in style_string.split(';'))}


def DictToStyle(style_dict):
    if len(style_dict) == 0:
        return ""
    # Sort the keys so that the SVG is hash-stable with the same inputs
    keys = list(style_dict.keys())
    keys.sort()
    return ';'.join([f'{key}:{style_dict[key]}' for key in keys])


def DataUrlForPng(png_path) -> str:
    with open(png_path, 'rb+') as f:
        return 'data:image/png;base64,' + str(base64.b64encode(f.read()), encoding='utf8')


def TransformSvg(template_svg_path: str, placard_svg_path: str, brewer: str, beer: str, beer_style: str, abv: float, image_file=None):
    # Load SVG template
    e = defusedxml.ElementTree.parse(template_svg_path)
    root = e.getroot()
    root.find(".//*[@id='txtBrewer']")[0].text = brewer
    root.find(".//*[@id='txtBeer']")[0].text = beer
    root.find(".//*[@id='txtStyle']")[0].text = beer_style
    root.find(".//*[@id='txtAbv']")[0].text = f"{abv:.1f}"

    # Update image if one is present
    if image_file is not None:
        root.find(".//*[@id='imgLogo']").set(
            "{http://www.w3.org/1999/xlink}href", DataUrlForPng(image_file))

    # ABV Images
    hideIds = []
    if abv < 6:
        hideIds += ['imgNormalGray', 'imgStrong',
                    'imgBoozy', 'rectRed', 'rectStripes']
    elif 6 <= abv < 9:
        hideIds += ['imgNormal', 'imgStrongGray',
                    'imgBoozy', 'rectRed', 'rectStripes']
    elif abv >= 9:
        hideIds += ['imgNormal', 'imgStrong', 'imgBoozyGray']

    for id in hideIds:
        node = root.find(f".//*[@id='{id}']")
        nodeStyle = StyleToDict(node.get('style'))
        nodeStyle['display'] = "none"
        node.set('style', DictToStyle(nodeStyle))

    # ABV Line
    abvLine = root.find(".//*[@id='abvLine']")
    abvLineStyle = StyleToDict(abvLine.get('style'))
    abvLineInstr = PathDToList(abvLine.get('d'))

    if abv > 9:
        # Change line ending if this is a boozy beer
        abvLineStyle['marker-end'] = "url(#markBurst)"

    # Size the ABV line so that it represents the ABV of
    # this beer.
    # In the template, the first point defines the 4% mark,
    # and the end marks the 13% mark
    #
    # The line path instructions are expected to be
    #   "M X1,Y H X2"
    start = float(abvLineInstr[1][0])
    end = float(abvLineInstr[3][0])
    deltaAbv = abv - 4
    adjusted = start + (end-start)*(deltaAbv/9.0)
    if adjusted < start:
        adjusted = start
    elif adjusted > end:
        adjusted = end
    abvLineInstr[3][0] = str(adjusted)
    abvLine.set('style', DictToStyle(abvLineStyle))
    abvLine.set('d', ListToPathD(abvLineInstr))

    e.write(placard_svg_path)


def DownloadImageAsPng(image_url: str, download_dir: str, downloaded_filename: str) -> str:
    ContentTypes = {
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36'}
    with requests.get(image_url, headers=headers) as response:
        contentType = response.headers['Content-Type']
        if contentType not in ContentTypes:
            raise Exception(
                f'Unsupported Content-Type: {contentType} from {image_url}')
        download_path = os.path.join(
            download_dir, f'{downloaded_filename}.{ContentTypes[contentType]}')
        with open(download_path, 'wb+') as f:
            f.write(response.content)
            f.close()
        if contentType != 'image/png':
            png_path = os.path.splitext(download_path)[0] + '.png'
            if 0 != os.system(f'convert {download_path} {png_path} > /dev/null 2>&1'):
                raise Exception(
                    f'Failed to convert {download_path} to {png_path}.  Do you have convert install?')
            else:
                os.remove(download_path)
            download_path = png_path

        if os.system(f'exiftool -overwrite_original -all=  {download_path} > /dev/null 2>&1') != 0:
            raise Exception(
                f'Failed to strip exif info from downloaded file.  Do you have exiftool installed?')
        return download_path


def process(force, placard_dir: str, svg_path: str, hashes: Hashes, brewer, beer, style, abv_str, logo_url) -> bool:

    # Figure out which image file (if any) we are going to use
    image_file = None
    custom_file = os.path.join(placard_dir, 'custom.png')
    downloaded_file = os.path.join(placard_dir, 'downloaded.png')
    if os.path.isfile(custom_file):
        # Use custom.png if present
        image_file = custom_file
    elif os.path.isfile(downloaded_file):
        # Otherwise, use downloaded.png
        image_file = downloaded_file
    elif logo_url is not None:
        # Attempt a download of the image
        image_file = DownloadImageAsPng(logo_url, placard_dir, 'downloaded')

    # Hash selected image
    if image_file is not None:
        hashes.add_file(image_file)

    # Hash template SVG
    hashes.add_file(f'templates/{template_name}')
    template_svg_path = os.path.join(os.curdir, f'templates/{template_name}')

    if not force and not hashes.has_changes():
        # Nothing is changed, so nothing needs to be regenerated
        return False

    status.write(f"Rebuilding placard")
    TransformSvg(template_svg_path, svg_path, brewer,
                 beer, style, float(abv_str), image_file)

    return True
