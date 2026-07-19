#!/usr/bin/env python3
"""Fetch all published posts from a WordPress site and save as markdown.

Usage:
    python3 fetch_posts.py [site-url]

Run from your blog directory. Posts are written to published/ in the
current working directory.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from html import unescape

SITE = "https://christine-seeman.com"
PUBLISHED_DIR = os.path.join(os.getcwd(), "published")
TIMEOUT = 30


def fetch_paginated(api_base, resource):
    items = []
    page = 1
    while True:
        url = f"{api_base}/{resource}?per_page=100&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": "BlogArchiver/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                batch = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            # WordPress returns 400 when the page number is past the last page
            if e.code == 400:
                break
            raise
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


def html_to_markdown(html):
    """Convert WordPress HTML to markdown using basic transformations."""
    text = html

    # Remove WordPress block comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # Headers
    for level in range(6, 0, -1):
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            lambda m, l=level: f"\n{'#' * l} {unescape(m.group(1).strip())}\n",
            text,
            flags=re.DOTALL,
        )

    # Bold and italic
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)

    # Links
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.DOTALL,
    )

    # Images
    text = re.sub(
        r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*/?>', r"![\2](\1)", text
    )
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>', r"![](\1)", text)

    # Code blocks
    text = re.sub(
        r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
        lambda m: f"\n```\n{unescape(m.group(1)).strip()}\n```\n",
        text,
        flags=re.DOTALL,
    )

    # Inline code
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)

    # Blockquotes
    text = re.sub(
        r"<blockquote[^>]*>(.*?)</blockquote>",
        lambda m: "\n"
        + "\n".join(f"> {line}" for line in m.group(1).strip().split("\n"))
        + "\n",
        text,
        flags=re.DOTALL,
    )

    # Lists
    text = re.sub(r"<ul[^>]*>", "\n", text)
    text = re.sub(r"</ul>", "\n", text)
    text = re.sub(r"<ol[^>]*>", "\n", text)
    text = re.sub(r"</ol>", "\n", text)
    text = re.sub(
        r"<li>(.*?)</li>", lambda m: f"- {m.group(1).strip()}", text, flags=re.DOTALL
    )

    # Horizontal rules
    text = re.sub(r"<hr[^>]*/?>", "\n---\n", text)

    # Paragraphs and line breaks
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Figure/figcaption
    text = re.sub(r"<figure[^>]*>", "", text)
    text = re.sub(r"</figure>", "", text)
    text = re.sub(r"<figcaption[^>]*>(.*?)</figcaption>", r"*\1*", text, flags=re.DOTALL)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # Unescape HTML entities
    text = unescape(text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def sanitize_filename(slug):
    return re.sub(r"[^a-z0-9-]", "", slug.lower())


def main():
    site = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else SITE
    if not site.startswith("https://"):
        print("Error: site URL must start with https://")
        sys.exit(1)
    api_base = site + "/wp-json/wp/v2"

    os.makedirs(PUBLISHED_DIR, exist_ok=True)

    try:
        print("Fetching categories and tags...")
        categories = {
            c["id"]: unescape(c["name"])
            for c in fetch_paginated(api_base, "categories")
        }
        tags = {
            t["id"]: unescape(t["name"]) for t in fetch_paginated(api_base, "tags")
        }

        print("Fetching posts...")
        posts = fetch_paginated(api_base, "posts")
    except urllib.error.URLError as e:
        print(f"Error: request to {site} failed: {e}")
        sys.exit(1)

    print(f"Found {len(posts)} posts")

    for post in sorted(posts, key=lambda p: p["date"]):
        slug = post["slug"]
        date = post["date"][:10]
        title = unescape(post["title"]["rendered"])
        content_html = post["content"]["rendered"]
        excerpt_html = post["excerpt"]["rendered"]

        post_categories = [categories.get(cid, "") for cid in post.get("categories", [])]
        post_categories = [c for c in post_categories if c and c != "Uncategorized"]

        post_tags = [tags.get(tid, "") for tid in post.get("tags", [])]
        post_tags = [t for t in post_tags if t]

        excerpt_text = re.sub(r"<[^>]+>", "", excerpt_html).strip()
        excerpt_text = unescape(excerpt_text)
        if excerpt_text.endswith("[&hellip;]") or excerpt_text.endswith("[...]"):
            excerpt_text = excerpt_text.rsplit("[", 1)[0].strip()

        content_md = html_to_markdown(content_html)

        # Build front matter
        front_matter = f"""---
title: "{title.replace('"', '\\"')}"
slug: "{slug}"
date: {date}
status: published
url: "{site}/{slug}/"
categories: [{', '.join(f'"{c}"' for c in post_categories)}]
tags: [{', '.join(f'"{t}"' for t in post_tags)}]
excerpt: "{excerpt_text[:200].replace('"', '\\"')}"
---"""

        filename = f"{date}-{sanitize_filename(slug)}.md"
        filepath = os.path.join(PUBLISHED_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(front_matter + "\n\n" + content_md + "\n")

        print(f"  {filename}")

    print(f"\nDone. {len(posts)} posts saved to published/")


if __name__ == "__main__":
    main()
