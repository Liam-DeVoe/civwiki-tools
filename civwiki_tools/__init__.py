from pathlib import Path

from pywikibot.login import ClientLoginManager
from pywikibot.config import usernames

from civwiki_tools.utils import site


__all__ = ["site"]

mod = {}
with open(Path(__file__).parent.parent / "config.py") as f:
    source = f.read()

exec(source, mod)

family_name = site.family.name
# username is retrieved from pywikibot after it parses user-config.py.
# password is retrieved separately by us from config.py.
# pywikibot was not really built to be used as a library...this was the nicest
# solution I could find that still gave me a reasonable amount of control over
# when and how logins happen.
user = usernames[family_name]["en"]
password = mod["password"]

manager = ClientLoginManager(user=user, password=password, site=site)
manager.login()

# force a re-fetch of site information. Even though we just logged in, pywikibot
# keeps information for an anonymous user here, and we need to tell it to update
# for our freshly logged in user.
del site.userinfo
del site.tokens
