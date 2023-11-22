# imports an image of a block or item from minecraft.wiki.
# Usage:
# python3 scripts/import_item_image.py --name "Block of Emerald" --url https://minecraft.wiki/images/Block_of_Emerald_JE4_BE3.png

from argparse import ArgumentParser

from bs4 import BeautifulSoup
import requests
from pywikibot.specialbots import UploadRobot

from civwiki_tools import site


MINECRAFT_BASE_URL = "https://minecraft.wiki"
MINECRAFT_FILE_URL = f"{MINECRAFT_BASE_URL}/w/File:{{item_name}}.png"

def guess_url(args):
    if args.url is not None:
        return args.url

    # try and intelligently clean it up, but leave alone otherwise.
    item_name = args.name
    if "_" in item_name:
        item_name = item_name.replace("_", " ").title()
    if item_name.endswith(" Block"):
        item_name = f"Block of {item_name.removesuffix(" Block")}"

    image_url = MINECRAFT_FILE_URL.format(item_name=item_name)

    r = requests.get(image_url, allow_redirects=True)
    # we're now at https://minecraft.wiki/w/File:Nether_Wart_Age_3_JE8.png.
    # we want to parse the direct file name of
    # https://minecraft.wiki/images/Nether_Wart_Age_3_JE8.png?d9978.
    soup = BeautifulSoup(r.text)
    image_url = soup.select(".fullMedia a")[0].get("href")
    return f"{MINECRAFT_BASE_URL}{image_url}"

parser = ArgumentParser()
parser.add_argument("name")
parser.add_argument("url", nargs="?")
args = parser.parse_args()

image_url = guess_url(args)
item_name = args.name

description = f"{item_name}. Imported from minecraft.wiki ({image_url})"
new_filename = f"{item_name}.png"
upload_bot = UploadRobot(
    image_url,
    target_site=site,
    use_filename=new_filename,
    # prevent asking for filename confirmation
    keep_filename=True,
    description=description,
    # prevent asking for description confirmation
    verify_description=False
)
upload_bot.run()
