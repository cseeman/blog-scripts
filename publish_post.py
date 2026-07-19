#!/usr/bin/env python3
"""Publish a markdown post to WordPress as a draft via the REST API."""

import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error

ENV_PATH = os.path.join(os.getcwd(), ".env")


def load_env():
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

    # Code blocks (before other processing)
    def replace_code_block(m):
        code = m.group(1).replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre><code>{code}</code></pre>"

    html = re.sub(r"```\w*\n(.*?)```", replace_code_block, html, flags=re.DOTALL)

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

    # Links
    html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html)

    # Images
    html = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" />', html)

    # Horizontal rules
    html = re.sub(r"^---+$", "<hr />", html, flags=re.MULTILINE)

    # Unordered list items
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>\n?)+", lambda m: f"<ul>\n{m.group(0)}</ul>\n", html)

    # Wrap remaining plain text paragraphs
    lines = html.split("\n\n")
    processed = []
    block_tags = ("< h", "<pre", "<ul", "<ol", "<li", "<hr", "<block")
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


def resolve_category_ids(env, category_names):
    if not category_names:
        return []
    url = f"{env['WP_URL']}/wp-json/wp/v2/categories?per_page=100"
    credentials = base64.b64encode(
        f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()
    ).decode()
    req = urllib.request.Request(url, headers={
        "User-Agent": "BlogPublisher/1.0",
        "Authorization": f"Basic {credentials}",
    })
    with urllib.request.urlopen(req) as resp:
        existing = json.loads(resp.read().decode())

    cat_map = {c["name"].lower(): c["id"] for c in existing}
    ids = []
    for name in category_names:
        if name.lower() in cat_map:
            ids.append(cat_map[name.lower()])
        else:
            new_id = create_term(env, "categories", name)
            if new_id:
                ids.append(new_id)
    return ids


def resolve_tag_ids(env, tag_names):
    if not tag_names:
        return []
    url = f"{env['WP_URL']}/wp-json/wp/v2/tags?per_page=100"
    credentials = base64.b64encode(
        f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()
    ).decode()
    req = urllib.request.Request(url, headers={
        "User-Agent": "BlogPublisher/1.0",
        "Authorization": f"Basic {credentials}",
    })
    with urllib.request.urlopen(req) as resp:
        existing = json.loads(resp.read().decode())

    tag_map = {t["name"].lower(): t["id"] for t in existing}
    ids = []
    for name in tag_names:
        if name.lower() in tag_map:
            ids.append(tag_map[name.lower()])
        else:
            new_id = create_term(env, "tags", name)
            if new_id:
                ids.append(new_id)
    return ids


def create_term(env, taxonomy, name):
    url = f"{env['WP_URL']}/wp-json/wp/v2/{taxonomy}"
    credentials = base64.b64encode(
        f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()
    ).decode()
    data = json.dumps({"name": name}).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "User-Agent": "BlogPublisher/1.0",
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            print(f"  Created {taxonomy[:-1]}: {name}")
            return result["id"]
    except urllib.error.HTTPError as e:
        print(f"  Warning: could not create {taxonomy[:-1]} '{name}': {e}")
        return None


def publish_draft(env, meta, body_html):
    url = f"{env['WP_URL']}/wp-json/wp/v2/posts"
    credentials = base64.b64encode(
        f"{env['WP_USER']}:{env['WP_APP_PASSWORD']}".encode()
    ).decode()

    post_data = {
        "title": meta.get("title", "Untitled"),
        "content": body_html,
        "status": "draft",
        "slug": meta.get("slug", ""),
    }

    excerpt = meta.get("excerpt", "")
    if excerpt:
        post_data["excerpt"] = excerpt

    categories = meta.get("categories", [])
    if isinstance(categories, list) and categories:
        print("Resolving categories...")
        post_data["categories"] = resolve_category_ids(env, categories)

    tags = meta.get("tags", [])
    if isinstance(tags, list) and tags:
        print("Resolving tags...")
        post_data["tags"] = resolve_tag_ids(env, tags)

    data = json.dumps(post_data).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "User-Agent": "BlogPublisher/1.0",
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    })

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
        return result


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <markdown-file>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: file not found: {sys.argv[1]}")
        sys.exit(1)

    env = load_env()
    for key in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"):
        if key not in env:
            print(f"Error: {key} not set in .env")
            sys.exit(1)

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    meta, body_md = parse_front_matter(content)
    body_html = markdown_to_html(body_md)

    print(f"Publishing draft: {meta.get('title', 'Untitled')}")
    print(f"  Slug: {meta.get('slug', '(none)')}")

    try:
        result = publish_draft(env, meta, body_html)
        print(f"\nDraft created successfully!")
        print(f"  ID:    {result['id']}")
        print(f"  Edit:  {env['WP_URL']}/wp-admin/post.php?post={result['id']}&action=edit")
        print(f"  Preview: {result['link']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Error {e.code}: {e.reason}")
        print(body)
        sys.exit(1)


if __name__ == "__main__":
    main()
