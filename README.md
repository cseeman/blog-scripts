# blog-scripts

Small, dependency-free Python scripts for running a WordPress blog from
local markdown, with cross-posting to dev.to. Everything uses the Python 3
standard library, so there is nothing to install.

The workflow these support:

1. Write a post as markdown with YAML front matter.
2. `publish_post.py` pushes it to WordPress as a draft via the REST API.
3. Finalize and publish in wp-admin (images, formatting tweaks, scheduling).
4. `fetch_posts.py` pulls the published posts back down as markdown, so the
   local directory stays an archive of what is actually live.
5. `to_devto.py` converts the live post into dev.to-ready markdown with a
   `canonical_url` pointing back to the original.

The scripts operate on the current working directory, so run them from your
blog directory:

```
blog/
  .env          WordPress credentials (never committed)
  drafts/       work in progress, and generated .devto.md files
  published/    markdown archive of live posts
```

## Setup

Create a `.env` in your blog directory (only needed for `publish_post.py`):

```
WP_URL=https://your-site.com
WP_USER=your-username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

`WP_APP_PASSWORD` is a WordPress application password (wp-admin, Users,
Profile, Application Passwords), not your login password.

## publish_post.py

Converts a markdown file to HTML and creates a WordPress draft. Reads
title, slug, excerpt, categories, and tags from the front matter, creating
any categories or tags that do not exist yet. Always creates a draft, never
publishes directly.

```
python3 path/to/publish_post.py drafts/my-post.md
```

## fetch_posts.py

Fetches every published post from the WordPress REST API and writes each to
`published/<date>-<slug>.md` with front matter (title, slug, date, url,
categories, tags, excerpt) and the body converted to markdown.

```
python3 path/to/fetch_posts.py https://your-site.com
```

## to_devto.py

Converts a live post into dev.to-ready markdown. It fetches the rendered
page rather than reusing local markdown, because the live post is the
source of truth once you have edited in wp-admin.

```
python3 path/to/to_devto.py https://your-site.com/my-post/ --tags ruby,rails
```

It converts headings, lists, images, blockquotes, and code blocks (fenced,
with language detection), rewrites images to full-resolution WordPress URLs,
normalizes curly quotes and dashes to plain ASCII, and writes
`drafts/<slug>.devto.md` with front matter:

- `published: false`, so pasting into dev.to never publishes by accident
- `canonical_url` pointing at the original post, so your site keeps the SEO
  credit
- title, description, and cover image pulled from the page's meta tags

The result is also copied to the clipboard (macOS `pbcopy`) for pasting
into the dev.to editor.

## Caveats

- The markdown/HTML conversion is regex-based and intentionally simple. It
  covers common WordPress blocks; tables, nested lists, and embeds are not
  handled.
- `to_devto.py` locates the post body via the theme's `entry-content` class,
  which works with standard WordPress themes but may need adjusting for
  heavily customized ones.
