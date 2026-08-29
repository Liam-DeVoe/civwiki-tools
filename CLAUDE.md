# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python toolset for automating edits to civwiki.org, a MediaWiki instance documenting Civilization Minecraft servers. The primary functionality includes:

1. **FactoryMod Configuration Management**: Parsing YAML configurations from various Civ servers (CivMC, CivClassic 2.0, Civcraft 3.0) and generating formatted wiki templates
2. **Wiki Automation Scripts**: Batch operations for category merging, backlink editing, and image importing from minecraft.wiki
3. **MediaWiki Bot Integration**: Built on pywikibot with custom authentication and site configuration

## Architecture

### Core Library (`civwiki_tools/`)

- **`factorymod.py`**: Custom YAML parser for FactoryMod server configs
- **`family.py`**: pywikibot Family definition for civwiki.org
- **`site.py`**: Thin wrapper around pywikibot's APISite with convenience methods
- **`__init__.py`**: Entry point that handles authentication

### Configuration Files

- **`user-config.py`**: Sets pywikibot username (format: `usernames["civwiki"]["en"] = "username"`)
- **`config.py`**: Contains bot password (format: `password = "..."`)
- Both have `.sample` versions showing required format

### Scripts (`scripts/`)

All scripts are standalone and meant to be run directly:

- **`update_factorymod.py`**: Main script for syncing FactoryMod configs to wiki
- **`import_item_image.py`**: Fetches block/item images from minecraft.wiki
- **`merge_civlization_categories.py`**: Consolidates server and civilization categories
- **`regex_edit_backlinks.py`**: Template for regex-based mass edits on pages linking to a target

### Utility Files

- **`batch.py`**: Simple line-by-line processor that reads `input.txt` and runs `import_item_image.py` for each line

## Development Commands

### Setup

```bash
# Install package in editable mode
pip install -e .

# Configure credentials
cp user-config.py.sample user-config.py
cp config.py.sample config.py
# Edit both files with actual credentials
```

### Running Scripts

```bash
# Update all factories for a server
python3 scripts/update_factorymod.py --server "civmc" --factory all

# Update specific factory
python3 scripts/update_factorymod.py --server "civclassic 2.0" --factory "Ore Smelter"

# Dry run (print output without saving)
python3 scripts/update_factorymod.py --server "civmc" --factory all --dry

# Import an image
python3 scripts/import_item_image.py "Oak Leaves"
python3 scripts/import_item_image.py "Block of Emerald" https://minecraft.wiki/images/Block_of_Emerald_JE4_BE3.png

# Run other utility scripts directly
python3 scripts/merge_civlization_categories.py
python3 scripts/regex_edit_backlinks.py
```

## Important Implementation Details

### Edit Summaries

If Claude is told to use Tybot to make an edit to the wiki, prefix the edit summary with `claude: ` — e.g. `claude: replace dead links` - unless told otherwise.

### Pywikibot Integration

- The library is not designed to be imported as a standard package. Importing `civwiki_tools` triggers authentication and login.
- The `site` object in `civwiki_tools.utils` is the authenticated API interface used by all scripts.
- `relog()` must be called if token-related errors occur (pywikibot's session management is fragile).

### Wiki Template Generation

- Templates follow format: `Template:FactoryModConfig_{factory}_({server})`
- Server names are case-normalized (e.g., "civmc" → "CivMC")
- Random recipe outputs get separate anchor-linked tables
- Float formatting: strips unnecessary precision while avoiding scientific notation

### Authentication Flow

1. `user-config.py` is loaded by pywikibot (sets username)
2. `config.py` is manually exec'd to get password
3. `ClientLoginManager` performs login
4. Site userinfo and tokens are force-refreshed (pywikibot caches anonymous session otherwise)
5. Scripts import the pre-authenticated `site` object from `civwiki_tools`
