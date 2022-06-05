# placard-gen

Generating Placard PNGs and PDFs.

## Prerequisites

### Linux packages

#### pip, qpdf, texlive-extra-utils (for pdfcrop)

```bash
sudo apt install pip qpdf texlive-extra-utils
```

### Python packages

```bash
pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib defusedxml PyPDF2
```

## Parameters

| Parameter                  | Default                     | Description                                                               |
| -------------------------- | --------------------------- | ------------------------------------------------------------------------- |
| `--upload`                 | `True`                      | Upload to Google Drive after generation                                   |
| `--placard_sheet_id`       | [default spreadsheet]       | Id of Google Sheet to read from                                           |
| `--placard_sheet_range`    | [default spreadsheet range] | Tab and range of Google Sheet to select beers                             |
| `--drive_root_folder_id`   | [default drive root folder] | Id of Google Drive folder used as Placards master folder                  |
| `--multiprint`             | `False`                     | Print all placards marked as "Print" in --multiprint_sheet_id, 6 per page |
| `--multiprint_all`         | `False`                     | Print all placards, 6 per page                                            |
| `--multiprint_sheet_id`    | [default spreadsheet]       | Tab and range of Google Sheet to select beers to multiprint               |
| `--multiprint_sheet_range` | [default spreadsheet range] | Tab and range of Google Sheet to select beers to multiprint               |
| `--site`                   | `None`                      | Only do work for the given site                                           |

## Usage

### Generating and Uploading Placards

The script defaults are fine for a normal run that regenerates all placards for all sites and uploads any changed outputs.

```bash
./placard.py
```

### Printing Multiple Placards for a Site

If printing more than 1 new placard, select the placards in the Multiprint tab on the Placard spreadsheet and use the `--multiprint` and `--site`
parameters to generate a PDF that packs a bunch of placards onto the same page.

```bash
./placard.py \
  --multiprint \
  --site=[Site Name]
```
