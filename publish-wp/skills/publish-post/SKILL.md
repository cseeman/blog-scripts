---
name: publish-post
description: Publish a blog draft to WordPress and archive it to published/. Runs a style-check first, then publish_post.py, then moves the file with a date prefix.
argument-hint: [draft-file]
disable-model-invocation: true
hooks:
  PermissionRequest:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh bash ${CLAUDE_PLUGIN_ROOT}/skills/publish-post"
          timeout: 5
    - matcher: Edit
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh edit ${CLAUDE_PLUGIN_ROOT}/skills/publish-post"
          timeout: 5
permissions:
  paths:
    - pattern: "drafts/**"
      access: write
  bash:
    - "^python3 (~|\\$HOME|/Users/[^/ ]+)/Documents/blog-scripts/publish_post\\.py drafts/"
    - "^mv drafts/[^ ]+\\.md published/"
---

Publish the draft $ARGUMENTS to WordPress. Run from the blog content directory (contains `drafts/`, `published/`, `.env`).

Before starting, create a TodoWrite task list with these milestones so progress survives interruption: style-check passed, frontmatter verified, script run and post ID captured, status flipped, file moved. Mark each as you complete it. Step 3 is not idempotent; never re-run it after a lost context without checking the todo state first.

1. Run the style-check skill on the draft.
   <gate>If it reports findings, resolve them with the user before continuing.</gate>
2. Read the draft and confirm frontmatter is complete: `title`, `slug`, `date`, `excerpt`, `categories`, `tags`. Remove the voice-notes HTML comment if still present.
3. Run `python3 ~/Documents/blog-scripts/publish_post.py drafts/<file>.md`. Capture the post ID, edit URL, and preview URL from the output.
4. Flip `status: draft` to `status: published` in the frontmatter.
5. Move the file: `mv drafts/<file>.md published/YYYY-MM-DD-<slug>.md` using today's date.
6. Report the outcome, and always include these reminders:
   - The script creates a WordPress DRAFT. The post is not live until reviewed and published in wp-admin (include the edit URL).
   - Any categories or tags the script created on the site (its output lists them).
   - Cross-posting comes after the WP post is live: `/publish-wp:to-devto`.
