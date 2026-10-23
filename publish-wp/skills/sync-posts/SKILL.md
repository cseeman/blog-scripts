---
name: sync-posts
description: Pull live WordPress edits back into the local published/ archive via fetch_posts.py and summarize what changed.
disable-model-invocation: true
hooks:
  PermissionRequest:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh bash ${CLAUDE_PLUGIN_ROOT}/skills/sync-posts"
          timeout: 5
permissions:
  bash:
    - "^python3 (~|\\$HOME|/Users/[^/ ]+)/Documents/blog-scripts/fetch_posts\\.py$"
    - "^git status"
    - "^git diff"
---

Sync the local `published/` archive with the live WordPress site. Run from the blog content directory.

1. Check `git status -- published/` first.
   <gate>IMPORTANT: If there are uncommitted local changes in `published/`, warn the user that the fetch will overwrite them and stop until they decide.</gate>
2. Run `python3 ~/Documents/blog-scripts/fetch_posts.py`.
3. Run `git status` and `git diff -- published/` to see what the fetch changed.
4. Summarize: which posts picked up live edits, which posts are new to the archive. Flag anything unexpected, such as a post that changed drastically or disappeared.
