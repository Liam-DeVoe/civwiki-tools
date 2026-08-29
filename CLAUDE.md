# CLAUDE.md

Tools for automating edits to civwiki.org, a MediaWiki instance documenting Civilization Minecraft servers. The `civwiki_tools` package handles authentication and parsing FactoryMod server configs, `scripts/` contains standalone scripts that use it, and `civlint/` is a wikitext linter.

## Setup

```bash
pip install -e .
cp user-config.py.sample user-config.py
cp config.py.sample config.py
# fill in credentials in both files
```

## Interacting with CivWiki

```python
from civwiki_tools import site  # importing triggers login
import pywikibot

# reading a page
page = site.page("Some Page")
print(page.text)

# editing a page
page = site.page("Some Page")
page.text = new_text
page.save(summary="automated: replace dead links")

# categories
category = pywikibot.Category(site, "Category:CivMC")
members = category.members()
categories = site.page("Some Page").categories()

pages = site.page("Some Page").backlinks() # pages linking to a page
pages = site.search("some phrase", namespaces=[0]) # searching page text
site.page("Some Page").exists() # checking whether a page exists
```

- Prefix edit summaries with `automated: ` unless told otherwise.
- Treat scripts you write as throwaway by default: run them and delete them, unless it's clear from context (or an explicit ask) that the script should be kept for reuse.
- Beyond the custom `site.page()`, `site` is a normal pywikibot `APISite` — standard pywikibot usage works.

## FactoryMod templates

`scripts/update_factorymod.py` syncs FactoryMod configs (in `resources/`) to wiki templates named `Template:FactoryModConfig_{factory}_({server})`:

```bash
python3 scripts/update_factorymod.py --server "civmc" --factory all
# --factory "Ore Smelter" for a single factory, --dry to print without saving
```

## Linter (`civlint/`)

A ruff-style linter for civwiki.org wikitext: rules grouped by code prefix
(CW = civwiki-specific, WP = Check Wikipedia ports, PC = pywikibot
cosmetic_changes ports, ML = MediaWiki Linter subset, BA = broken section
anchors, TY = known misspellings), safe/unsafe autofix tiers, and a sqlite
site index for cross-page rules. See `civlint/README.md` for usage and how
to write rules.

```bash
python3 -m civlint index          # build/refresh the site index (logs in)
python3 -m civlint check --all    # lint the whole wiki from the index
python3 -m pytest tests/          # run the linter's test suite
```

Invariant: nothing in `civlint/` may import `civwiki_tools` at module level —
that import logs into the wiki. Network access (page fetch/save, index build)
belongs in function-local imports; linting and tests must work offline.
