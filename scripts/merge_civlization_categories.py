import difflib

import pywikibot
import pywikibot.textlib
from pywikibot import Category
from civwiki_tools import site


# takes a page with e.g.
#   [[Category:CivMC]]
#   [[Category:Civilizations]]
# and replaces it with
#   [[Category: Civilizations (CivMC)]]

civ_category = Category(site, "Category:Civilizations")
replacements = {
    f"Category:{server}": f"Category:{civ}"
    for (server, civ) in [
        ("CivMC", "Civilizations (CivMC)"),
        ("CivClassic 2.0", "Civilizations (CivClassic 2.0)"),
        ("CivRealms 2.0", "Civilizations (CivRealms 2.0)"),
        ("Civcraft 3.0", "Civilizations (Civcraft 3.0)"),
        ("Devoted 3.0", "Civilizations (Devoted 3.0)"),
        ("Civ+", "Civilizations (Civ+)"),
    ]
}


def merge_categories():
    civ_category_title = civ_category.title()
    for page in civ_category.articles():
        print(f"Processing {page.full_url()}")
        if not page.exists():
            print("  does not exist, skipping")
            continue

        categories = [c.title() for c in pywikibot.textlib.getCategoryLinks(page.text)]
        new_categories = categories.copy()
        found = None
        skip = False
        for server_category, new_civ_category in replacements.items():
            if server_category not in categories:
                continue
            if found is not None:
                print(f"  found multiple server categories in {categories}, skipping")
                skip = True
                break
            found = {"server_cat": server_category, "new_civ_cat": new_civ_category}

            # not always explicitly present. it might be transcluded from a template.
            if civ_category_title in new_categories:
                new_categories.remove(civ_category_title)
            new_categories.remove(server_category)
            new_categories.append(new_civ_category)

        if skip:
            continue
        if found is None:
            print(f"  no matching server category in {categories}, skipping")
            continue

        old_text = page.text
        page.text = pywikibot.textlib.replaceCategoryLinks(old_text, new_categories)

        summary = (
            f"Merging categories [[{civ_category_title}]] + [[{found["server_cat"]}]] "
            f"-> [[{found["new_civ_cat"]}]]"
        )
        diff = "\n".join(difflib.unified_diff(old_text.split("\n"), page.text.split("\n")))
        print(f"  {summary}")
        print(f"  diff: {diff}")

        try:
            print("  saving changes...")
            page.save(summary)
            print("  ...saved")
        except pywikibot.exceptions.Error as e:
            print(f"  error saving changes: {e}")

merge_categories()
