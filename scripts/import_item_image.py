# imports an image of a block or item from minecraft.wiki.
# Usage:
# python scripts/import_item_image.py --name "Block of Emerald" --url https://minecraft.wiki/images/Block_of_Emerald_JE4_BE3.png

from argparse import ArgumentParser

from civwiki_tools import site

from pywikibot.specialbots import UploadRobot

MINECRAFT_BASE_URL = "https://minecraft.wiki/w/File:{item_name}.png"

# def guess_url(args):
#     if args.url is not None:
#         return args.url

#     # try and intelligently clean it up, but leave alone otherwise.
#     item_name = args.item_name
#     if "_" in item_name:
#         item_name = item_name.replace("_", " ").title()

#     image_url = MINECRAFT_BASE_URL.format(item_name=item_name)

#     # UploadRobot won't follow redirects for us, so we have to do it here.
#     r = requests.get(image_url, allow_redirects=True)
#     return r.url

parser = ArgumentParser()
parser.add_argument("--name")
parser.add_argument("--url")
args = parser.parse_args()

image_url = args.url
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
