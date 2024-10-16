from pywikibot import Family as _Family


class CivwikiFamily(_Family):
    name = "civwiki"
    langs = {
        "en": "civwiki.org",
    }

    def scriptpath(self, code):
        return "/w"


# pywikibot requires that the family defined here be named Family. Leaving an
# alias works just as well.
Family = CivwikiFamily
