from pathlib import Path

from pywikibot.config import family_files
from pywikibot import Site as _Site

from civwiki_tools import family
from civwiki_tools.site import Site

# register our family
family_files[family.CivwikiFamily.name] = family.__file__
site: Site = _Site("en", "civwiki", interface=Site)

RESOURCES = Path(__file__).parent.parent / "resources"
