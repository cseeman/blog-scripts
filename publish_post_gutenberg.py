#!/usr/bin/env python3
"""Publish a markdown post to WordPress as a draft built from Gutenberg blocks.

This is the block-editor counterpart to publish_post.py. It reuses that
script's env loading, front matter parsing, and REST calls, and replaces only
the markdown conversion so the result parses into real blocks instead of
landing in a single Classic block.

Differences from publish_post.py beyond the block markup:
  - blockquotes are supported (publish_post.py emitted the > characters as text)
  - ordered lists are supported
  - images are matched before links, so ![alt](src) no longer becomes !<a ...>
  - HTML comments in the source are dropped, so voice notes never reach the site

Usage:
    python3 publish_post_gutenberg.py drafts/some-post.md
    python3 publish_post_gutenberg.py drafts/some-post.md --dry-run
"""

import os
import re
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from publish_post import load_env, parse_front_matter, publish_draft, upload_local_images

SEPARATOR_BLOCK = (
    "<!-- wp:separator -->\n"
    '<hr class="wp-block-separator has-alpha-channel-opacity"/>\n'
    "<!-- /wp:separator -->"
)


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_bare_ampersands(text):
    """Gutenberg's validator rejects raw & in markup, but leave real entities alone."""
    return re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)


def render_inline(text):
    """Apply inline markdown. Code spans are stashed so nothing rewrites them."""
    stash = []

    def stash_code(match):
        stash.append(f"<code>{escape_html(match.group(1))}</code>")
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", stash_code, text)
    text = escape_bare_ampersands(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1"/>', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def paragraph_block(text):
    rendered = render_inline(text)
    if re.fullmatch(r"<img [^>]+/>", rendered):
        return (
            "<!-- wp:image -->\n"
            f'<figure class="wp-block-image">{rendered}</figure>\n'
            "<!-- /wp:image -->"
        )
    return f"<!-- wp:paragraph -->\n<p>{rendered}</p>\n<!-- /wp:paragraph -->"


def heading_block(level, text):
    attrs = "" if level == 2 else f' {{"level":{level}}}'
    return (
        f"<!-- wp:heading{attrs} -->\n"
        f'<h{level} class="wp-block-heading">{render_inline(text)}</h{level}>\n'
        "<!-- /wp:heading -->"
    )


def code_block(code):
    return (
        "<!-- wp:code -->\n"
        f'<pre class="wp-block-code"><code>{escape_html(code)}</code></pre>\n'
        "<!-- /wp:code -->"
    )


def quote_block(lines):
    """Consecutive quote lines keep their line breaks; blank lines split paragraphs."""
    paragraphs = []
    current = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)

    inner = "".join(
        "<!-- wp:paragraph -->\n<p>{}</p>\n<!-- /wp:paragraph -->".format(
            "<br>".join(render_inline(line) for line in paragraph)
        )
        for paragraph in paragraphs
    )
    return (
        "<!-- wp:quote -->\n"
        f'<blockquote class="wp-block-quote">{inner}</blockquote>\n'
        "<!-- /wp:quote -->"
    )


def list_block(items, ordered):
    attrs = ' {"ordered":true}' if ordered else ""
    tag = "ol" if ordered else "ul"
    inner = "".join(
        "<!-- wp:list-item -->\n"
        f"<li>{render_inline(item)}</li>\n"
        "<!-- /wp:list-item -->"
        for item in items
    )
    return (
        f"<!-- wp:list{attrs} -->\n"
        f'<{tag} class="wp-block-list">{inner}</{tag}>\n'
        "<!-- /wp:list -->"
    )


def starts_block(line):
    return bool(
        re.match(r"^```", line)
        or re.match(r"^#{1,6}\s+", line)
        or re.match(r"^-{3,}\s*$", line)
        or line.startswith(">")
        or re.match(r"^[-*]\s+", line)
        or re.match(r"^\d+\.\s+", line)
    )


def markdown_to_blocks(md):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
    lines = md.split("\n")
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        if re.match(r"^```", line):
            i += 1
            buffer = []
            while i < len(lines) and not lines[i].startswith("```"):
                buffer.append(lines[i])
                i += 1
            i += 1
            blocks.append(code_block("\n".join(buffer)))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            blocks.append(heading_block(len(heading.group(1)), heading.group(2).strip()))
            i += 1
            continue

        if re.match(r"^-{3,}\s*$", line):
            blocks.append(SEPARATOR_BLOCK)
            i += 1
            continue

        if line.startswith(">"):
            buffer = []
            while i < len(lines) and (
                lines[i].startswith(">") or (buffer and not lines[i].strip())
            ):
                if not lines[i].strip():
                    break
                buffer.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            blocks.append(quote_block(buffer))
            continue

        if re.match(r"^[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(re.sub(r"^[-*]\s+", "", lines[i]))
                i += 1
            blocks.append(list_block(items, ordered=False))
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i]))
                i += 1
            blocks.append(list_block(items, ordered=True))
            continue

        buffer = []
        while i < len(lines) and lines[i].strip() and not starts_block(lines[i]):
            buffer.append(lines[i].strip())
            i += 1
        blocks.append(paragraph_block(" ".join(buffer)))

    return "\n\n".join(blocks)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv[1:]

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <markdown-file> [--dry-run]")
        sys.exit(1)

    filepath = args[0]
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        sys.exit(1)

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    meta, body_md = parse_front_matter(content)

    if dry_run:
        print(markdown_to_blocks(body_md))
        return

    env = load_env()
    for key in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"):
        if key not in env:
            print(f"Error: {key} not set in .env")
            sys.exit(1)
    env["WP_URL"] = env["WP_URL"].rstrip("/")
    if not env["WP_URL"].startswith("https://"):
        print("Error: WP_URL must start with https:// to protect credentials")
        sys.exit(1)

    print(f"Publishing draft: {meta.get('title', 'Untitled')}")
    print(f"  Slug: {meta.get('slug', '(none)')}")

    try:
        body_md = upload_local_images(env, body_md, os.path.dirname(filepath))
        result = publish_draft(env, meta, markdown_to_blocks(body_md))
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.reason}")
        print(e.read().decode())
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: could not reach {env['WP_URL']}: {e.reason}")
        sys.exit(1)

    print("\nDraft created successfully!")
    print(f"  ID:    {result['id']}")
    print(f"  Edit:  {env['WP_URL']}/wp-admin/post.php?post={result['id']}&action=edit")
    print(f"  Preview: {result['link']}")


if __name__ == "__main__":
    main()
