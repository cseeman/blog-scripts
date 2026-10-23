---
name: new-post
description: Scaffold a new blog draft in drafts/ from the blog's post template. Use when creating or starting a new blog post. Not for editing existing drafts.
argument-hint: [title]
hooks:
  PermissionRequest:
    - matcher: Write
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh write ${CLAUDE_PLUGIN_ROOT}/skills/new-post"
          timeout: 5
permissions:
  paths:
    - pattern: "drafts/**"
      access: write
---

Scaffold a new blog draft titled "$ARGUMENTS".

<gate>The current directory must contain `drafts/` and `templates/post.md`. If it does not, stop and say which directory to run from.</gate>

1. Read `templates/post.md` for the frontmatter shape and the voice-notes HTML comment.
2. Derive a kebab-case slug from the title. If no title was given, ask for one.
3. Write `drafts/<slug>.md` with the template's frontmatter filled in:
   - `title`, `slug`, `date` (today), `status: draft`
   - `categories` and `tags`: suggest values by checking what similar posts in `published/` use, leave `excerpt` empty
4. Keep the voice-notes comment from the template in the draft. It is removed at publish time, not before.
5. Report the file path and suggest next steps: write the post, then `/publish-wp:publish-post` when ready.
