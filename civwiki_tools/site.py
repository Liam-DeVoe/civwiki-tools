from pywikibot import Page as _Page
from pywikibot.site import APISite


class Site(APISite):
    def page(self, title) -> _Page:
        return _Page(self, title)
