from pywikibot import APISite, Page as _Page


class Site(APISite):
    def page(self, title) -> _Page:
        return _Page(self, title)
