#!/usr/bin/env python3
"""Publish a markdown post to WordPress as a draft via the REST API."""

import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ENV_PATH = os.path.join(os.getcwd(), ".env")
TIMEOUT = 30
TERM_LABELS = {"categories": "category", "tags": "tag"}
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def load_env():
    if not os.path.exists(ENV_PATH):
        print("Error: .env not found. Create it with WP_URL, WP_USER, WP_APP_PASSWORD.")
        sys.exit(1)
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def parse_front_matter(content):
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not match:
        print("Error: no YAML front matter found")
        sys.exit(1)

    meta = {}
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            value = value.strip().strip('"')
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1]
                value = [i.strip().strip('"') for i in items.split(",") if i.strip()]
            meta[key.strip()] = value

    body = match.group(2).strip()
    return meta, body


def markdown_to_html(md):
    """Convert markdown to WordPress-compatible HTML."""
    html = md

    def escape_code(code):
        return code.replace("<", "&lt;").replace(">", "&gt;")

    # Code blocks (before other processing)
    html = re.sub(
        r"```\w*\n(.*?)```",
        lambda m: f"<pre><code>{escape_code(m.group(1))}</code></pre>",
        html,
        flags=re.DOTALL,
    )

    # Inline code
    html = re.sub(
        r"`([^`\n]+)`", lambda m: f"<code>{escape_code(m.group(1))}</code>", html
    )

    # Headers
    for level in range(6, 0, -1):
        html = re.sub(
            rf"^{'#' * level}\s+(.+)$",
            rf"<h{level}>\1</h{level}>",
            html,
            flags=re.MULTILINE,
        )

    # Bold and italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # Images before links, or ![alt](src) becomes !<a ...>
    html = IMAGE_PATTERN.sub(r'<img src="\2" alt="\1" />', html)

    # Links
    html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html)

    # Horizontal rules
    html = re.sub(r"^---+$", "<hr />", html, flags=re.MULTILINE)

    # Unordered list items
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>\n?)+", lambda m: f"<ul>\n{m.group(0)}</ul>\n", html)

    # Wrap remaining plain text paragraphs
    lines = html.split("\n\n")
    processed = []
    block_tags = ("<h", "<pre", "<ul", "<ol", "<li", "<block")
    for block in lines:
        block = block.strip()
        if not block:
            continue
        if any(block.lower().startswith(tag) for tag in block_tags):
            processed.append(block)
        else:
            processed.append(f"<p>{block}</p>")
    html = "\n\n".join(processed)

    return html


def auth_headers(env):
    credentials = base64.b64encode(
        f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()
    ).decode()
    return {
        "User-Agent": "BlogPublisher/1.0",
        "Authorization": f"Basic {credentials}",
    }


def wp_request(env, path, data=None):
    url = f"{env['WP_URL']}/wp-json/wp/v2/{path}"
    headers = auth_headers(env)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=body, method="POST" if body else "GET", headers=headers
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def upload_media(env, path, alt_text):
    content_type = mimetypes.guess_type(path)[0]
    if not content_type or not content_type.startswith("image/"):
        print(f"Error: not an image: {path}")
        sys.exit(1)
    query = urllib.parse.urlencode({"alt_text": alt_text})
    headers = auth_headers(env)
    headers["Content-Type"] = content_type
    headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
    with open(path, "rb") as f:
        req = urllib.request.Request(
            f"{env['WP_URL']}/wp-json/wp/v2/media?{query}",
            data=f.read(),
            method="POST",
            headers=headers,
        )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def local_image_path(src, base_dir):
    if re.match(r"^https?://", src):
        return None
    return os.path.normpath(os.path.join(base_dir, src))


def upload_images(env, meta, body_md, base_dir):
    """Upload local images, point the markdown at the WordPress copies, and return the featured image's media ID."""
    featured = meta.get("featured_image", "")
    featured_alt = meta.get("featured_image_alt", "")
    if featured and not local_image_path(featured, base_dir):
        print("Error: featured_image must be a local path")
        sys.exit(1)

    # Check every path before uploading so a typo can't leave half the images orphaned on the site
    sources = [match.group(2) for match in IMAGE_PATTERN.finditer(body_md)]
    for src in sources + ([featured] if featured else []):
        path = local_image_path(src, base_dir)
        if path and not os.path.exists(path):
            print(f"Error: image not found: {src}")
            sys.exit(1)

    uploads = {}

    def upload(src, alt):
        path = local_image_path(src, base_dir)
        if path not in uploads:
            uploads[path] = upload_media(env, path, alt)
            print(f"  Uploaded {src}")
        return uploads[path]

    def replace(match):
        alt, src = match.group(1), match.group(2)
        if not local_image_path(src, base_dir):
            return match.group(0)
        return f"![{alt}]({upload(src, alt)['source_url']})"

    body_md = IMAGE_PATTERN.sub(replace, body_md)
    featured_id = upload(featured, featured_alt)["id"] if featured else None
    return body_md, featured_id


def fetch_all_terms(env, taxonomy):
    terms = []
    page = 1
    while True:
        try:
            batch = wp_request(env, f"{taxonomy}?per_page=100&page={page}")
        except urllib.error.HTTPError as e:
            # WordPress returns 400 when the page number is past the last page
            if e.code == 400:
                break
            raise
        if not batch:
            break
        terms.extend(batch)
        page += 1
    return terms


def create_term(env, taxonomy, name):
    label = TERM_LABELS.get(taxonomy, taxonomy)
    try:
        result = wp_request(env, taxonomy, {"name": name})
    except urllib.error.HTTPError as e:
        print(f"  Warning: could not create {label} '{name}': {e}")
        return None
    print(f"  Created {label}: {name}")
    return result["id"]


def resolve_term_ids(env, taxonomy, names):
    term_map = {t["name"].lower(): t["id"] for t in fetch_all_terms(env, taxonomy)}
    ids = []
    for name in names:
        term_id = term_map.get(name.lower()) or create_term(env, taxonomy, name)
        if term_id:
            ids.append(term_id)
    return ids


def publish_draft(env, meta, body_html, featured_media=None):
    post_data = {
        "title": meta.get("title", "Untitled"),
        "content": body_html,
        "status": "draft",
        "slug": meta.get("slug", ""),
    }

    if featured_media:
        post_data["featured_media"] = featured_media

    excerpt = meta.get("excerpt", "")
    if excerpt:
        post_data["excerpt"] = excerpt

    categories = meta.get("categories", [])
    if isinstance(categories, list) and categories:
        print("Resolving categories...")
        post_data["categories"] = resolve_term_ids(env, "categories", categories)

    tags = meta.get("tags", [])
    if isinstance(tags, list) and tags:
        print("Resolving tags...")
        post_data["tags"] = resolve_term_ids(env, "tags", tags)

    return wp_request(env, "posts", post_data)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <markdown-file>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        sys.exit(1)

    env = load_env()
    for key in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"):
        if key not in env:
            print(f"Error: {key} not set in .env")
            sys.exit(1)
    env["WP_URL"] = env["WP_URL"].rstrip("/")
    if not env["WP_URL"].startswith("https://"):
        print("Error: WP_URL must start with https:// to protect credentials")
        sys.exit(1)

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    meta, body_md = parse_front_matter(content)

    print(f"Publishing draft: {meta.get('title', 'Untitled')}")
    print(f"  Slug: {meta.get('slug', '(none)')}")

    try:
        body_md, featured_id = upload_images(env, meta, body_md, os.path.dirname(filepath))
        result = publish_draft(env, meta, markdown_to_html(body_md), featured_id)
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
