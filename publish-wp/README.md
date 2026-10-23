# publish-wp

Claude Code plugin wrapping the blog-scripts publishing workflow. Skills run
from a blog content directory laid out with `drafts/`, `published/`,
`templates/post.md`, and a `.env` holding `WP_URL`, `WP_USER`,
`WP_APP_PASSWORD`.

## Skills

| Skill | Invocation | What it does |
|-------|------------|--------------|
| `/publish-wp:new-post [title]` | User or Claude | Scaffold a draft from `templates/post.md` |
| `/publish-wp:style-check [file]` | User or Claude | Voice pass hunting AI-sounding tells before publishing |
| `/publish-wp:publish-post [draft-file]` | User only | Style-check, publish to WordPress as a draft, archive to `published/` with a date prefix |
| `/publish-wp:sync-posts` | User only | Pull live WordPress edits back into `published/` |
| `/publish-wp:to-devto [url-or-file]` | User or Claude | Convert a post to dev.to markdown and copy to the clipboard |

`publish-post` and `sync-posts` are user-only (`disable-model-invocation`)
because they mutate the WordPress site or overwrite local files.

## Hooks

Each skill declares PermissionRequest hooks that run
`scripts/resolve-permissions.sh` against the `permissions:` block in its own
SKILL.md. The resolver auto-approves only the narrow patterns each skill
needs (the wrapped script invocations, `mv drafts/... published/...`,
`grep -n` over post files, writes under `drafts/` inside the project
directory) and everything else falls through to the normal permission
prompt. There are no other hooks; nothing runs automatically.

## Install

```
/plugin marketplace add cseeman/blog-scripts
/plugin install publish-wp@blog-scripts
```

The skills call the Python scripts at the root of this repo and expect it
cloned at `~/Documents/blog-scripts`. If it lives elsewhere, the commands
still work but need manual permission approval.
