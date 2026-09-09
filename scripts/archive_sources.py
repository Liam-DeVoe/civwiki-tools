# Archives external content linked on civwiki pages, to combat link rot.
#
# Links are split into two sections: (1) urls inside <ref> tags, (2) all other
# external urls. Each url is categorized:
#
#   * media (imgur, discord cdn, streamable, direct file urls, ...):
#     downloaded and uploaded to civwiki as a file.
#   * album (imgur albums): every image is uploaded to civwiki and collected
#     on a gallery page under CivWiki:Archived albums/.
#   * youtube: downloaded with yt-dlp and uploaded to civwiki. only runs with
#     --include-youtube, so it can be enabled explicitly.
#   * webpage (reddit, blogs, google docs, ...): archived to the wayback
#     machine. an existing snapshot is reused if one exists; otherwise a fresh
#     save is requested.
#   * skip (other wikis, archives, discord invites): nothing to archive.
#
# The original url is always kept; the bot appends "([... archived])" after it.
#
# Reruns are incremental without any local state: annotated urls are detected
# in the wikitext, existing uploads are found by their deterministic filename,
# and existing wayback snapshots are found by the availability api. The only
# thing persisted is dead_links.json, the record of negative outcomes (dead
# urls, failed saves) — these would otherwise be slowly re-attempted every
# rerun, and the file doubles as the report of sources needing human hunting.
# Pass --retry-failed to re-attempt them anyway.
#
# Usage:
# python3 scripts/archive_sources.py scan
# python3 scripts/archive_sources.py run --pages "List of Videos|Generic War" --dry
# python3 scripts/archive_sources.py run --pages "List of Videos" --include-youtube
# python3 scripts/archive_sources.py run --all

import difflib
import json
import re
import subprocess
import tempfile
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pywikibot import FilePage
from pywikibot.exceptions import APIError, Error as PywikibotError

from civwiki_tools import site
from civwiki_tools.utils import relog

DEAD_LINKS_PATH = Path(__file__).parent.parent / "dead_links.json"
SCAN_PATH = Path(__file__).parent.parent / "archive_scan.json"

USER_AGENT = "civwiki-archive-bot/0.1 (https://civwiki.org/wiki/User:CivWikiBot)"

# nothing meaningful to archive: archives themselves, wikis with their own
# history, and discord invites (which require login and expire server-side).
SKIP_DOMAINS = {
    "web.archive.org",
    "archive.org",
    "archive.ph",
    "civwiki.org",
    "miraheze.org",
    "wikipedia.org",
    "wikimedia.org",
    "minecraft.gamepedia.com",
    "minecraft.wiki",
    "discord.gg",
    "discord.com",
    "discordapp.com",
}

# hosts serving a single media file, possibly behind an html page
MEDIA_DOMAINS = {
    "i.imgur.com",
    "imgur.com",
    "cdn.discordapp.com",
    "media.discordapp.net",
    "streamable.com",
    "gyazo.com",
    "i.gyazo.com",
    "puu.sh",
    "postimg.cc",
    "i.postimg.cc",
    "files.catbox.moe",
    "prnt.sc",
    "medal.tv",
}

YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "gaming.youtube.com"}

# extension: allowed on civwiki (from siteinfo fileextensions)
CONTENT_TYPE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/flac": "flac",
    "application/pdf": "pdf",
}

URL_RE = re.compile(r'https?://[^\s<>\[\]{}|"]+')
REF_RE = re.compile(r"<ref[^>/]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
NOWIKI_RE = re.compile(
    r"<nowiki>.*?</nowiki>|<pre>.*?</pre>", re.DOTALL | re.IGNORECASE
)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


@dataclass
class Link:
    url: str
    start: int
    end: int
    section: str  # "refs" or "other"
    category: str  # "media", "album", "youtube", "webpage", "skip"
    # for urls inside <nowiki>/<pre>, the annotation goes after the closing
    # tag (inside those spans it would render as literal text)
    insert_at: int | None = None


def domain(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def categorize(url):
    dom = domain(url)
    if dom in SKIP_DOMAINS or any(dom.endswith(f".{d}") for d in SKIP_DOMAINS):
        # discord cdn subdomains are media, not invites
        if dom not in MEDIA_DOMAINS:
            return "skip"
    if dom in YOUTUBE_DOMAINS or any(dom.endswith(f".{d}") for d in YOUTUBE_DOMAINS):
        return "youtube"
    ext = Path(urlparse(url).path).suffix.lstrip(".").lower()
    if ext in CONTENT_TYPE_EXTENSIONS.values() or ext in {"jpeg", "webp"}:
        return "media"
    if dom == "imgur.com" and ("/a/" in url or "/gallery/" in url):
        return "album"
    if dom in MEDIA_DOMAINS:
        return "media"
    return "webpage"


def template_spans(text):
    """Spans of {{...}} template calls (including nested content)."""
    spans = []
    depth = 0
    start = 0
    i = 0
    while i < len(text) - 1:
        if text[i : i + 2] == "{{":
            if depth == 0:
                start = i
            depth += 1
            i += 2
        elif text[i : i + 2] == "}}" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 2))
            i += 2
        else:
            i += 1
    return spans


def extract_links(text):
    ref_spans = [m.span() for m in REF_RE.finditer(text)]
    tpl_spans = template_spans(text)
    nowiki_spans = [m.span() for m in NOWIKI_RE.finditer(text)]
    comment_spans = [m.span() for m in COMMENT_RE.finditer(text)]
    links = []
    for m in URL_RE.finditer(text):
        if any(s <= m.start() < e for s, e in comment_spans):
            continue
        url = m.group().rstrip(".,;:!?'\"")
        # a trailing ) is usually wikitext, not part of the url
        while url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        end = m.start() + len(url)
        insert_at = next((e for s, e in nowiki_spans if s <= m.start() < e), None)
        if any(s <= m.start() < e for s, e in ref_spans):
            section = "refs"
        elif any(s <= m.start() < e for s, e in tpl_spans):
            # inserting text inside a template parameter can break rendering,
            # so these are excluded from editing unless explicitly requested
            section = "other-template"
        else:
            section = "other"
        links.append(Link(url, m.start(), end, section, categorize(url), insert_at))
    return links


def already_archived(text, link):
    window = text[link.end : (link.insert_at or link.end) + 200]
    return (
        "archived])" in window or "archived]]" in window or "web.archive.org" in window
    )


# wayback machine


def wayback_available(url):
    try:
        r = session.get(
            "https://archive.org/wayback/available", params={"url": url}, timeout=30
        )
        snapshot = r.json().get("archived_snapshots", {}).get("closest")
    except (requests.RequestException, ValueError):
        return None
    if snapshot and snapshot.get("available"):
        return snapshot["url"].replace("http://", "https://", 1)
    return None


def wayback_save(url):
    for _ in range(2):
        try:
            r = session.get(
                f"https://web.archive.org/save/{url}",
                timeout=180,
                allow_redirects=True,
            )
        except requests.RequestException as e:
            print(f"    wayback save error: {e}")
            return None
        if r.status_code == 429:
            print("    wayback rate limited, sleeping 120s")
            time.sleep(120)
            continue
        if "/web/" in r.url:
            return r.url
        # save succeeded but didn't redirect; check for a fresh snapshot
        return wayback_available(url)
    return None


# media resolution and download


def resolve_media_url(url):
    """Resolve a media host page url to a direct file url."""
    dom = domain(url)
    path = urlparse(url).path
    if Path(path).suffix:
        return url
    if dom == "streamable.com":
        video_id = path.strip("/").split("/")[-1]
        r = session.get(f"https://api.streamable.com/videos/{video_id}", timeout=30)
        if r.ok:
            files = r.json().get("files", {})
            for key in ("mp4", "mp4-mobile"):
                if key in files and files[key].get("url"):
                    return files[key]["url"]
        return None
    if dom == "imgur.com":
        return f"https://i.imgur.com/{path.strip('/').split('/')[-1]}.jpg"
    # generic: look for og:video / og:image on the page
    try:
        r = session.get(url, timeout=30)
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    soup = BeautifulSoup(r.text, features="lxml")
    for prop in ("og:video:secure_url", "og:video", "og:image"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag and tag.get("content"):
            return tag["content"]
    return None


def download_media(url):
    """Download url to a temp file. Returns (path, extension) or None."""
    try:
        r = session.get(url, timeout=120, stream=True)
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    content_type = r.headers.get("Content-Type", "").split(";")[0].strip()
    ext = CONTENT_TYPE_EXTENSIONS.get(content_type)
    if ext is None:
        # imgur returns the removed-image placeholder as image/png at a
        # different url; catch that separately
        return None
    if "imgur.com" in r.url and "removed" in r.url:
        return None
    file = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
    for chunk in r.iter_content(chunk_size=1 << 20):
        file.write(chunk)
    file.close()
    return Path(file.name), ext


# imgur's public web client id; allows anonymous api access
IMGUR_CLIENT_ID = "546c25a59c58ad7"


def imgur_album(url):
    """Fetch an imgur album's media list. Returns (album_id, title, media_urls)
    or None if the album is gone."""
    slug = Path(urlparse(url).path).name
    # album urls are either a bare id (imgur.com/a/xcwPnNU) or a slug ending
    # in the id (imgur.com/a/some-title-8qxdRWr); the api only accepts the id
    for album_id in dict.fromkeys([slug, slug.split("-")[-1]]):
        try:
            r = session.get(
                f"https://api.imgur.com/post/v1/albums/{album_id}",
                params={"client_id": IMGUR_CLIENT_ID, "include": "media"},
                timeout=30,
            )
        except requests.RequestException:
            return None
        if r.ok:
            data = r.json()
            urls = [m["url"] for m in data.get("media", []) if m.get("url")]
            if urls:
                return album_id, data.get("title") or "", urls
    return None


def gallery_page_title(album_id):
    return f"CivWiki:Archived albums/{album_id}"


def create_gallery_page(album_id, album_title, url, files, page_title):
    title = gallery_page_title(album_id)
    page = site.page(title)
    if page.exists():
        return title
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title_line = f'\n\nAlbum title: "{album_title}"' if album_title else ""
    gallery = "\n".join(f"File:{f}" for f in files)
    page.text = (
        f"Automated archive of imgur album {url}, cited on [[{page_title}]]. "
        f"Retrieved {date}.{title_line}\n\n"
        f"<gallery>\n{gallery}\n</gallery>\n\n"
        "[[Category:Archived external sources]]"
    )
    with_relog(lambda: page.save(f"archive imgur album {url}"))
    return title


def download_youtube(url):
    """Download a youtube video with yt-dlp. Returns (path, extension) or None."""
    out_dir = Path(tempfile.mkdtemp())
    result = subprocess.run(
        [
            "yt-dlp",
            "--max-filesize",
            "2G",
            "-f",
            "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
            "-o",
            str(out_dir / "%(id)s.%(ext)s"),
            url,
        ],
        capture_output=True,
        text=True,
    )
    files = list(out_dir.iterdir())
    if result.returncode != 0 or not files:
        print(f"    yt-dlp failed: {result.stderr.strip().splitlines()[-1:]}")
        return None
    return files[0], files[0].suffix.lstrip(".")


def with_relog(fn):
    """Run a wiki write, retrying once after a token refresh. pywikibot's
    csrf tokens go stale over long runs (see relog in civwiki_tools)."""
    try:
        return fn()
    except APIError as e:
        if e.code != "badtoken":
            raise
        print("    stale csrf token, refreshing and retrying...", end=" ", flush=True)
        relog()
        return fn()


def file_title(url, ext):
    dom = domain(url)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", urlparse(url).path).strip("-.")
    slug = re.sub(rf"\.{ext}$", "", slug, flags=re.IGNORECASE)
    return f"Archive {dom} {slug}"[:180] + f".{ext}"


def upload_media(path, ext, url, page_title, title=None):
    """Upload a downloaded file to civwiki. Returns the file title."""
    if title is None:
        title = file_title(url, ext)
    filepage = FilePage(site, f"File:{title}")
    if filepage.exists():
        return title
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    text = (
        f"Automated archive of external source {url}, "
        f"cited on [[{page_title}]]. Retrieved {date}.\n\n"
        "[[Category:Archived external sources]]"
    )
    with_relog(
        lambda: site.upload(
            filepage,
            source_filename=str(path),
            comment=f"archive external source {url}",
            text=text,
            ignore_warnings=True,
            chunk_size=4 * 1024 * 1024,
        )
    )
    return title


# archival orchestration


def ensure_archived(link, page_title, dead, cache, args):
    """Archive link.url if not already handled. Returns an entry like
    {"status": "archived", "type": "file"|"wayback"|"page", "value": ...}.

    `cache` dedupes urls cited on multiple pages within this run; `dead` is
    the persistent record of negative outcomes.

    With args.dry, nothing is uploaded or saved anywhere; entries that would
    require a write get status "planned".
    """
    if link.url in cache:
        return cache[link.url]
    if link.url in dead and not args.retry_failed:
        return dead[link.url]

    date = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {"status": "failed", "category": link.category, "checked": date}

    if link.category == "media":
        resolved = resolve_media_url(link.url)
        downloaded = download_media(resolved) if resolved else None
        if downloaded:
            path, ext = downloaded
            if args.dry:
                entry |= {
                    "status": "planned",
                    "type": "file",
                    "value": file_title(link.url, ext),
                }
            else:
                title = upload_media(path, ext, link.url, page_title)
                entry |= {"status": "archived", "type": "file", "value": title}
            path.unlink()
        else:
            # dead media: best we can do is an existing wayback snapshot
            snapshot = wayback_available(link.url)
            if snapshot:
                entry |= {"status": "archived", "type": "wayback", "value": snapshot}
            else:
                entry["status"] = "dead"
    elif link.category == "album":
        album = imgur_album(link.url)
        if album is None:
            # dead album: best we can do is an existing wayback snapshot
            snapshot = wayback_available(link.url)
            if snapshot:
                entry |= {"status": "archived", "type": "wayback", "value": snapshot}
            else:
                entry["status"] = "dead"
        else:
            album_id, album_title, media_urls = album
            if args.dry:
                entry |= {
                    "status": "planned",
                    "type": "page",
                    "value": gallery_page_title(album_id),
                }
            else:
                files = []
                for i, media_url in enumerate(media_urls, 1):
                    downloaded = download_media(media_url)
                    if downloaded is None:
                        print(f"    album image failed: {media_url}")
                        continue
                    path, ext = downloaded
                    files.append(
                        upload_media(
                            path,
                            ext,
                            link.url,
                            page_title,
                            title=f"Archive imgur.com {album_id} {i}.{ext}",
                        )
                    )
                    path.unlink()
                if files:
                    if len(files) < len(media_urls):
                        print(
                            f"    only {len(files)}/{len(media_urls)} album"
                            " images archived"
                        )
                    gallery = create_gallery_page(
                        album_id, album_title, link.url, files, page_title
                    )
                    entry |= {"status": "archived", "type": "page", "value": gallery}
    elif link.category == "youtube":
        if not args.include_youtube:
            entry["status"] = "held"
        elif args.dry:
            entry |= {
                "status": "planned",
                "type": "file",
                "value": file_title(link.url, "mp4"),
            }
        else:
            downloaded = download_youtube(link.url)
            if downloaded:
                path, ext = downloaded
                title = upload_media(path, ext, link.url, page_title)
                path.unlink()
                entry |= {"status": "archived", "type": "file", "value": title}
            else:
                snapshot = wayback_available(link.url)
                if snapshot:
                    entry |= {
                        "status": "archived",
                        "type": "wayback",
                        "value": snapshot,
                    }
                else:
                    entry["status"] = "dead"
    elif link.category == "webpage":
        snapshot = wayback_available(link.url)
        if snapshot:
            entry |= {"status": "archived", "type": "wayback", "value": snapshot}
        elif args.dry:
            entry |= {
                "status": "planned",
                "type": "wayback",
                "value": "https://web.archive.org/web/<new snapshot>",
            }
        else:
            snapshot = wayback_save(link.url)
            if snapshot:
                entry |= {"status": "archived", "type": "wayback", "value": snapshot}

    cache[link.url] = entry
    if not args.dry:
        if entry["status"] in ("dead", "failed"):
            dead[link.url] = entry
        else:
            dead.pop(link.url, None)
    return entry


def archived_annotation(entry):
    if entry["type"] == "file":
        return f" ([[:File:{entry['value']}|archived]])"
    if entry["type"] == "page":
        return f" ([[{entry['value']}|archived]])"
    return f" ([{entry['value']} archived])"


def insertion_point(text, link):
    """Point to insert the annotation: after the enclosing nowiki/pre span if
    any, after the closing bracket for [url title] links, directly after the
    url otherwise."""
    if link.insert_at is not None:
        return link.insert_at
    if link.start > 0 and text[link.start - 1] == "[":
        close = text.find("]", link.end)
        if close != -1:
            return close + 1
    return link.end


def process_page(page, dead, cache, args):
    print(f"processing {page.title()}")
    text = page.text
    links = extract_links(text)
    insertions = []
    for link in links:
        if link.section not in args.sections:
            continue
        if link.category == "skip":
            # don't report the wayback urls inside our own annotations
            if not text.startswith(" archived])", link.end):
                print(f"  [{link.section}/skip] {link.url}")
            continue
        if already_archived(text, link):
            continue
        # print before attempting: archival can take minutes (fresh wayback
        # saves, video downloads), and a silent terminal looks stuck
        print(f"  [{link.section}/{link.category}] {link.url}:", end=" ", flush=True)
        try:
            entry = ensure_archived(link, page.title(), dead, cache, args)
        except Exception as e:
            # a single url must not kill a long run. not recorded as failed,
            # so the next rerun retries it naturally
            print(f"error ({e})")
            continue
        status = entry["status"]
        print(status)
        if status in ("archived", "planned"):
            insertions.append((insertion_point(text, link), archived_annotation(entry)))

    if not args.dry:
        save_dead_links(dead)
    if not insertions:
        print("  no changes")
        return

    new_text = text
    for point, annotation in sorted(insertions, reverse=True):
        new_text = new_text[:point] + annotation + new_text[point:]

    if args.dry:
        diff = "\n".join(
            difflib.unified_diff(text.split("\n"), new_text.split("\n"), lineterm="")
        )
        print(f"  diff:\n{diff}")
        print("  (dry run, not saving)")
        return
    try:
        page.text = new_text
        with_relog(
            lambda: page.save(
                f"add archived copies of {len(insertions)} external sources"
            )
        )
        print(
            f"  saved: https://civwiki.org/w/index.php?diff={page.latest_revision_id}"
        )
    except PywikibotError as e:
        print(f"  error saving: {e}")


# state and scan


def load_dead_links():
    if DEAD_LINKS_PATH.exists():
        return json.loads(DEAD_LINKS_PATH.read_text())
    return {}


def save_dead_links(dead):
    DEAD_LINKS_PATH.write_text(json.dumps(dead, indent=2))


def pages_with_external_links():
    titles = set()
    for protocol in ("http", "https"):
        for page in site.exturlusage(protocol=protocol, namespaces=[0]):
            titles.add(page.title())
    return sorted(titles)


def scan(args):
    from pywikibot.pagegenerators import PreloadingGenerator

    titles = pages_with_external_links()
    print(f"{len(titles)} pages with external links")
    report = {"pages": {}}
    counts = {}
    pages = PreloadingGenerator(site.page(t) for t in titles[: args.limit])
    for i, page in enumerate(pages):
        links = extract_links(page.text)
        entries = [
            {"url": l.url, "section": l.section, "category": l.category}
            for l in links
            if not already_archived(page.text, l)
        ]
        if entries:
            report["pages"][page.title()] = entries
        for e in entries:
            key = (e["section"], e["category"])
            counts[key] = counts.get(key, 0) + 1
        if (i + 1) % 200 == 0:
            print(f"  scanned {i + 1}/{len(titles)}")

    SCAN_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nscan saved to {SCAN_PATH}\n")
    print(f"{'section':<8} {'category':<10} {'links':>6}")
    for (section, category), n in sorted(counts.items()):
        print(f"{section:<8} {category:<10} {n:>6}")


def run(args):
    dead = load_dead_links()
    cache = {}
    if args.pages:
        titles = args.pages.split("|")
    else:
        if not SCAN_PATH.exists():
            print("no scan file; run `scan` first (or pass --pages)")
            return
        titles = list(json.loads(SCAN_PATH.read_text())["pages"])
    if args.limit:
        titles = titles[: args.limit]
    for title in titles:
        page = site.page(title)
        if not page.exists():
            print(f"{title} does not exist, skipping")
            continue
        process_page(page, dead, cache, args)


parser = ArgumentParser()
subparsers = parser.add_subparsers(dest="command", required=True)

parser_scan = subparsers.add_parser("scan")
parser_scan.add_argument("--limit", type=int, default=None)
parser_scan.set_defaults(func=scan)

parser_run = subparsers.add_parser("run")
group = parser_run.add_mutually_exclusive_group(required=True)
group.add_argument("--pages", help="pipe-separated page titles")
group.add_argument("--all", action="store_true", help="all pages from the scan file")
parser_run.add_argument("--dry", action="store_true", help="print diffs, don't save")
parser_run.add_argument("--limit", type=int, default=None)
parser_run.add_argument("--sections", default="refs,other", type=lambda s: s.split(","))
parser_run.add_argument("--include-youtube", action="store_true")
parser_run.add_argument("--retry-failed", action="store_true")
parser_run.set_defaults(func=run)

args = parser.parse_args()
args.func(args)
