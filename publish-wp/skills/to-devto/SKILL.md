---
name: to-devto
description: Convert a blog post to dev.to markdown and copy it to the clipboard. Use when cross-posting to dev.to, from a live WordPress URL or a local file.
argument-hint: [post-url-or-file]
hooks:
  PermissionRequest:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh bash ${CLAUDE_PLUGIN_ROOT}/skills/to-devto"
          timeout: 5
    - matcher: Write
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh write ${CLAUDE_PLUGIN_ROOT}/skills/to-devto"
          timeout: 5
permissions:
  paths:
    - pattern: "drafts/**"
      access: write
  bash:
    - "^python3 (~|\\$HOME|/Users/[^/ ]+)/Documents/blog-scripts/to_devto\\.py https://"
---

Convert $ARGUMENTS to dev.to markdown. Run from the blog content directory.

<branch condition="post is live on WordPress (URL loads)">
Run `python3 ~/Documents/blog-scripts/to_devto.py <url> --tags <tags>`. The live post is the source of truth; the script writes `drafts/<slug>.devto.md` and copies it to the clipboard.
</branch>

<branch condition="WordPress post still a draft (URL would 404)">
Build the file manually from the local markdown:

1. Read the local post from `published/` or `drafts/`.
2. Write `drafts/<slug>.devto.md` with dev.to frontmatter:
   - `title` (no quotes needed)
   - `published: false`
   - `description`: the post's excerpt
   - `tags`: see tag rules below
   - `canonical_url`: the future live URL, `https://<site>/<slug>/`
3. Repeat the title as an H1 at the top of the body, then the post body unchanged.
4. Copy to clipboard with `pbcopy < drafts/<slug>.devto.md` (this command needs manual approval; that is expected).
</branch>

Rules for both branches:

- dev.to tags are alphanumeric only. Strip hyphens (`active-storage` becomes `activestorage`), max 4 tags.
- If the WP post is not live yet, say so: the `canonical_url` will 404 until it is published in wp-admin, so publish there before publishing on dev.to.
