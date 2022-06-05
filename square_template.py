import base64
import os.path
import os
import re
from urllib.parse import urlencode
import requests
import defusedxml.ElementTree
from utils import Hashes, PreparedPlacard, make_hash_stable_pdf, status, ArgumentParser, syscmd, OutputFile

template_svg_path = os.path.join(os.curdir, 'templates/square_template.svg')


def prepare_template(placard_dir, brewer, beer, style, abv, logo_url, scale=1):
    template = SimpleTemplate(
        placard_dir, brewer, beer, style, abv, logo_url, scale)
    return template


class SimpleTemplate(PreparedPlacard):

    def __init__(self, placard_dir, brewer, beer, style, abv, logo_url, scale):
        super().__init__(f'{brewer} - {beer}', placard_dir)
        self.__hashes = Hashes(os.path.join(placard_dir, 'hashes.md5'))
        self.brewer = brewer
        self.beer = beer
        self.style = style
        self.abv = float(abv)
        self.logo_url = logo_url
        self.__image_file = None
        stem = os.path.join(placard_dir, 'placard')
        self.output_files['SVG'] = OutputFile(
            'SVG', 'image/svg+xml', stem + '.svg', self.__hashes)
        self.output_files['PNG'] = OutputFile(
            'PNG', 'image/png', stem + '.png', self.__hashes)
        self.output_files['PDF'] = OutputFile(
            'PDF', 'application/pdf', stem + '.pdf', self.__hashes)
        self.__scale = scale
        self.processed = self.__process()

    def __path_d_to_list(self, d):
        if d == None or d == '':
            return []
        return [e.split(',') for e in d.split(' ')]

    def __list_to_path_d(self, d):
        if len(d) == 0:
            return ''
        return ' '.join([','.join(e) for e in d])

    def __style_to_dict(self, style):
        if style == None or style == '':
            return {}
        return {t[0]: t[1] for t in (e.split(':') for e in style.split(';'))}

    def __dict_to_style(self, style):
        if len(style) == 0:
            return ""
        # Sort the keys so that the SVG is hash-stable with the same inputs
        keys = list(style.keys())
        keys.sort()
        return ';'.join([f'{key}:{style[key]}' for key in keys])

    def __data_url_for_png(self, png_path) -> str:
        with open(png_path, 'rb+') as f:
            return 'data:image/png;base64,' + str(base64.b64encode(f.read()), encoding='utf8')

    def __transform_svg(self):
        # Load SVG template
        e = defusedxml.ElementTree.parse(template_svg_path)
        root = e.getroot()
        root.find(".//*[@id='txtBrewer']")[0].text = self.brewer
        root.find(".//*[@id='txtBeer']")[0].text = self.beer
        root.find(".//*[@id='txtStyle']")[0].text = self.style
        root.find(".//*[@id='txtAbv']")[0].text = f"{self.abv:.1f}"
        root.find(".//*[@id='txtAbvBlur']")[0].text = f"{self.abv:.1f}"

        # Update image if one is present
        if self.__image_file is not None:
            root.find(".//*[@id='imgLogo']").set(
                "{http://www.w3.org/1999/xlink}href", self.__data_url_for_png(self.__image_file))

        # ABV Images
        hideIds = []
        if self.abv < 6:
            hideIds += ['imgNormalGray', 'imgStrong',
                        'imgBoozy', 'rectRed', 'rectStripes', 'txtAbvBlur']
        elif 6 <= self.abv < 9:
            hideIds += ['imgNormal', 'imgStrongGray',
                        'imgBoozy', 'rectRed', 'rectStripes', 'txtAbvBlur']
        elif self.abv >= 9:
            hideIds += ['imgNormal', 'imgStrong', 'imgBoozyGray']

        for id in hideIds:
            node = root.find(f".//*[@id='{id}']")
            nodeStyle = self.__style_to_dict(node.get('style'))
            nodeStyle['display'] = "none"
            node.set('style', self.__dict_to_style(nodeStyle))

        # ABV Line
        abvLine = root.find(".//*[@id='abvLine']")
        abvLineStyle = self.__style_to_dict(abvLine.get('style'))
        abvLineInstr = self.__path_d_to_list(abvLine.get('d'))

        if self.abv > 9:
            # Change ABV text color
            txtAbv = root.find(".//*[@id='txtAbv']")
            txtAbvStyle = self.__style_to_dict(txtAbv.get('style'))
            txtAbvStyle['fill'] = '#ff0030'
            txtAbvStyle['stroke'] = '#e0e0e0'
            txtAbv.set('style', self.__dict_to_style(txtAbvStyle))

        # Size the ABV line so that it represents the ABV of
        # this beer.
        # In the template, the first point defines the 4% mark,
        # and the end marks the 13% mark
        #
        # The line path instructions are expected to be
        #   "M X1,Y H X2"
        start = float(abvLineInstr[1][0])
        end = float(abvLineInstr[3][0])
        deltaAbv = self.abv - 4
        adjusted = start + (end-start)*(deltaAbv/9.0)
        if adjusted < start:
            adjusted = start
        elif adjusted > end:
            adjusted = end
        abvLineInstr[3][0] = str(adjusted)
        abvLine.set('style', self.__dict_to_style(abvLineStyle))
        abvLine.set('d', self.__list_to_path_d(abvLineInstr))

        if self.__scale != 1:
            # Transform the width/height of the root svg by the given scale
            self.__scale_length_propery(root, 'width')
            self.__scale_length_propery(root, 'height')

        e.write(self.output_files['SVG'].file_path)

    def __scale_length_propery(self, element, property):
        raw = element.get(property)
        match = re.match('^([0-9]+|[0-9]+\.[0-9]+)([a-z][a-z]|%)$', raw)
        if match is None:
            raise Exception(f'Not able to interpret {raw} as a length.')

        number = float(match.group(1))
        if '%' == match.group(2):
            # Percentage values are just set to the scale as a percentage
            number = self.__scale * 100
        else:
            # Actual numbers are scaled by the scaling factor
            number = number * self.__scale

        element.set(property, f'{number}{match.group(2)}')

    def __download_image_as_png(self):
        ContentTypes = {
            'image/jpeg': 'jpg',
            'image/png': 'png',
            'image/webp': 'webp',
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36'}
        with requests.get(self.logo_url, headers=headers) as response:
            contentType = response.headers['Content-Type']
            if contentType not in ContentTypes:
                raise Exception(
                    f'Unsupported Content-Type: {contentType} from {self.__image_url}')
            download_path = os.path.join(
                self.placard_dir, f'downloaded.{ContentTypes[contentType]}')
            with open(download_path, 'wb+') as f:
                f.write(response.content)
                f.close()
            if contentType != 'image/png':
                png_path = os.path.splitext(download_path)[0] + '.png'
                if syscmd(f'convert {download_path} {png_path}') != 0:
                    raise Exception(
                        f'Failed to convert {download_path} to {png_path}.  Do you have convert install?')
                else:
                    os.remove(download_path)
                download_path = png_path

            if syscmd(f'exiftool -overwrite_original -all=  {download_path}') != 0:
                raise Exception(
                    f'Failed to strip exif info from downloaded file.  Do you have exiftool installed?')
            self.__image_file = download_path

    def __create_png_and_pdf(self):
        svg_path = self.output_files['SVG'].file_path
        png_path = self.output_files['PNG'].file_path
        pdf_path = self.output_files['PDF'].file_path

        window_size = 278
        if self.__scale != 1:
            window_size = int(window_size*self.__scale)

        if syscmd(f'google-chrome --headless --window-size={window_size}x{window_size} --screenshot --hide-scrollbars {svg_path}') != 0:
            raise Exception(f"Failed to convert {svg_path} to PNG")

        if syscmd(f"google-chrome --headless --print-to-pdf --print-to-pdf-no-header {svg_path}") != 0:
            raise Exception(f"Failed to convert {svg_path} to PDF")

        # Chrome dumps 'output.pdf' and 'screenshot.png' in curdir
        if syscmd(f'mv output.pdf {pdf_path}') != 0:
            raise Exception(f'Failed to mv ./output.pdf to {pdf_path}')
        if syscmd(f'mv screenshot.png {png_path}') != 0:
            raise Exception(
                f'Failed to mv ./screenshot.png to {png_path}')

        # Crop the PDF, as chrome saves with a bunch of extra whitespace.
        if syscmd(f"pdfcrop {pdf_path} {pdf_path}") != 0:
            raise Exception(
                f"Failed to crop {pdf_path}.  Do you have pdfcrop installed?")

        # Make the PDF hash stable by getting rid of metadata and dynamic ids
        make_hash_stable_pdf(pdf_path)

    def __process(self) -> bool:
        parser = ArgumentParser()
        args = parser.parse_args()

        # Figure out which image file (if any) we are going to use
        custom_file = os.path.join(self.placard_dir, 'custom.png')
        downloaded_file = os.path.join(self.placard_dir, 'downloaded.png')
        if os.path.isfile(custom_file):
            # Use custom.png if present
            self.__image_file = custom_file
        elif os.path.isfile(downloaded_file):
            # Otherwise, use downloaded.png
            self.__image_file = downloaded_file
        elif len(self.logo_url) != 0:
            # Attempt a download of the image
            self.__download_image_as_png()

        data = [
            self.brewer,
            self.beer,
            self.style,
            str(self.abv),
            self.logo_url,
            str(self.__scale)
        ]
        self.__hashes.add_blob('data', ','.join(data).encode('utf8'))

        # Hash selected image
        if self.__image_file is not None:
            self.__hashes.add_file(self.__image_file)

        # Hash output files
        for output_file in self.output_files.values():
            self.__hashes.add_file(output_file.file_path)

        # Hash the template svg
        self.__hashes.add_file(template_svg_path)

        if not args.force and not self.__hashes.has_changes():
            # Nothing is changed, so nothing needs to be regenerated
            return False

        status.write(f"Rebuilding placard")
        self.__transform_svg()
        self.__create_png_and_pdf()
        self.__hashes.save()
        return True

    def has_changes(self):
        return self.__hashes.has_changes()
