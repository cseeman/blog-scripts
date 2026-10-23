---
name: style-check
description: Review a blog draft's voice and style before publishing, hunting AI-sounding tells (em dashes, mirrored antithesis, rhetorical-question chains, code cliches). Use to check or review a draft's style or voice, and always before publishing a post.
argument-hint: [file]
hooks:
  PermissionRequest:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-permissions.sh bash ${CLAUDE_PLUGIN_ROOT}/skills/style-check"
          timeout: 5
permissions:
  bash:
    - "^grep -n .+ (drafts|published|templates)/[^ ]+\\.md$"
---

Run a voice and style pass on $ARGUMENTS (default: the draft currently being worked on). Run from the blog content directory.

1. Read the voice-notes HTML comment in `templates/post.md`. That comment is the authoritative checklist; do not substitute a generic style guide.
   <fallback>If the file is missing, use the checklist summarized in step 3.</fallback>
2. Mechanical scan first, with line numbers:
   - `grep -n` for em dashes and en dashes (U+2014, U+2013)
   - `grep -n` for emoji and double hyphens used as punctuation
3. ultrathink: read the full post once, hunting only for the structural tells:
   - Generic claims that could describe any team or tool (needs real numbers, real names)
   - Mirrored antithesis and matched-adjective wordplay ("X isn't the problem, Y is")
   - Rhetorical-question chains
   - Cliche abstraction-speak about code ("earns its keep", "pulls its weight")
   - Fragments that obscure the actual claim
   - Hedging tails and double hedges in one sentence
   - Verbatim third-party quotes that should be paraphrased and anonymized
   - Jargon or acronyms used without a short explanation on first use
   - Sarcasm, condescension, or bossy phrasing toward readers who don't know something yet
4. Report findings as a list with line references. State plainly if the post is clean.
5. IMPORTANT: Propose a concrete rewrite for each finding, but apply edits only after the user approves.
