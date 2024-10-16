import re
import difflib

import pywikibot
from pywikibot import Page
from civwiki_tools import site


def regex_edit_backlinks(page, pattern, replacement):
    target_page = Page(site, page)

    for referring_page in target_page.backlinks():
        print(f"Processing {referring_page.full_url()}")

        if not referring_page.exists():
            print("  does not exist, skipping")
            continue

        old_text = referring_page.text
        new_text = re.sub(pattern, replacement, old_text)
        if old_text == new_text:
            print("  empty diff, skipping")
            continue
        diff = "\n".join(
            difflib.unified_diff(old_text.split("\n"), new_text.split("\n"))
        )
        print(f"  diff: {diff}")
        try:
            referring_page.text = new_text
            referring_page.save(f"regex edit: {pattern} -> {replacement}")
            print("  ...saved")
        except pywikibot.exceptions.Error as e:
            print(f"  error saving changes: {e}")


page = "Geographical Regions (CivMC)"
pattern = r"Geographical Regions \(CivMC\)"
replacement = "Geography of CivMC"

regex_edit_backlinks(page, pattern, replacement)
