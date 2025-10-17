from pathlib import Path

from pywikibot import Site as _Site
from pywikibot.config import family_files

from civwiki_tools import family
from civwiki_tools.site import Site

# register our family
family_name = family.CivwikiFamily.name
family_files[family_name] = family.__file__
site: Site = _Site("en", family_name, interface=Site)

RESOURCES = Path(__file__).parent.parent / "resources"


def relog():
    del site.userinfo
    del site.tokens
