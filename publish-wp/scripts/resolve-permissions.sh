#!/bin/bash
# Declarative permissions resolver for Claude Code plugin skills.
# Reads permissions directly from the active skill's SKILL.md frontmatter.
#
# Usage: resolve-permissions.sh <tool-type> [skill-dir]
#   tool-type: bash | read | write | edit
#   skill-dir: path to the skill directory containing SKILL.md (${CLAUDE_SKILL_DIR})
#
# Expects JSON on stdin with tool_input.command (bash) or tool_input.file_path (file ops).

set -euo pipefail

TOOL_TYPE="${1:-}"
SKILL_DIR="${2:-}"

if [[ -z "$TOOL_TYPE" ]]; then
  exit 0
fi

INPUT=$(cat)

# ── Debug logging (enable with RESOLVE_PERMISSIONS_DEBUG=1) ──────────────────

DEBUG_LOG=""
if [[ "${RESOLVE_PERMISSIONS_DEBUG:-}" == "1" ]]; then
  DEBUG_LOG="${CLAUDE_PROJECT_DIR:-.}/.claude/local/resolve-permissions-debug.log"
  mkdir -p "$(dirname "$DEBUG_LOG")"
fi

debug() {
  if [[ -n "$DEBUG_LOG" ]]; then
    echo "[$(date '+%H:%M:%S')] $*" >> "$DEBUG_LOG"
  fi
}

debug "── $TOOL_TYPE request ──"

# ── Helpers ──────────────────────────────────────────────────────────────────

approve() {
  debug "APPROVE"
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PermissionRequest",
      decision: { behavior: "allow" }
    }
  }'
  exit 0
}

deny() {
  local msg="${1:-Blocked by plugin permissions resolver}"
  debug "DENY: $msg"
  jq -n --arg m "$msg" '{
    hookSpecificOutput: {
      hookEventName: "PermissionRequest",
      decision: { behavior: "deny", message: $m }
    }
  }'
  exit 0
}

# Portable realpath: try grealpath (Homebrew coreutils), then realpath, then python3
canonical_path() {
  local p="$1"
  if command -v grealpath >/dev/null 2>&1; then
    grealpath -m -- "$p" 2>/dev/null
  elif realpath -m -- "$p" 2>/dev/null; then
    :
  else
    python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$p" 2>/dev/null
  fi
}

# Convert a glob pattern to an extended regex.
# Supports **, *, and ? wildcards.
glob_to_regex() {
  local glob="$1"
  local regex=""
  local i=0
  local len=${#glob}

  while (( i < len )); do
    local c="${glob:$i:1}"
    if [[ "$c" == "*" ]] && (( i + 1 < len )) && [[ "${glob:$((i+1)):1}" == "*" ]]; then
      # ** matches any path segment(s)
      regex+=".*"
      (( i += 2 ))
      # Skip a trailing slash after ** so **/foo works
      if (( i < len )) && [[ "${glob:$i:1}" == "/" ]]; then
        (( i += 1 ))
        regex+="(.*/)?"
      fi
    elif [[ "$c" == "*" ]]; then
      regex+="[^/]*"
      (( i += 1 ))
    elif [[ "$c" == "?" ]]; then
      regex+="[^/]"
      (( i += 1 ))
    elif [[ "$c" == "." ]]; then
      regex+="\\."
      (( i += 1 ))
    elif [[ "$c" =~ [\+\(\)\[\]\{\}\^\$\|] ]]; then
      regex+="\\$c"
      (( i += 1 ))
    else
      regex+="$c"
      (( i += 1 ))
    fi
  done

  echo "$regex"
}

# ── Security gates ───────────────────────────────────────────────────────────

if [[ "$TOOL_TYPE" == "bash" ]]; then
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
  [[ -z "$COMMAND" ]] && { debug "empty command, skip"; exit 0; }
  debug "command: $COMMAND"

  # Reject chaining operators, subshells, redirects, and embedded newlines
  if [[ "$COMMAND" == *$'\n'* ]] || [[ "$COMMAND" == *$'\r'* ]] || echo "$COMMAND" | grep -qE '[;|&`]|\$\(|>'; then
    deny "Command contains shell operators (;, &, |, \`, \$(), redirects, or embedded newlines) which cannot be auto-approved. Split into separate Bash tool calls — one command per call."
  fi

  # Reject dangerous find subcommands that bypass the chaining guard
  if echo "$COMMAND" | grep -qE '^find\s' && echo "$COMMAND" | grep -qE '\s-(exec|execdir|delete|ok)\b'; then
    deny "find with -exec, -execdir, -delete, or -ok cannot be auto-approved. Use find without these flags, or run the command with manual approval."
  fi
else
  FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
  [[ -z "$FILE_PATH" ]] && { debug "empty file_path, skip"; exit 0; }
  debug "file_path: $FILE_PATH"

  CANONICAL=$(canonical_path "$FILE_PATH")
  [[ -z "$CANONICAL" ]] && { debug "canonical_path failed"; exit 0; }
  debug "canonical: $CANONICAL"

  # Reject suspicious patterns in the canonical path
  if echo "$CANONICAL" | grep -qE '(\x00|;|&|\||`|\$\()'; then
    deny "File path contains suspicious characters (shell operators or null bytes). Use a clean file path without special characters."
  fi

  # Only auto-approve paths inside the project directory; anything else falls
  # through to the normal permission prompt
  if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_CANONICAL=$(canonical_path "$CLAUDE_PROJECT_DIR")
    if [[ -n "$PROJECT_CANONICAL" ]] && [[ "$CANONICAL" != "$PROJECT_CANONICAL/"* ]]; then
      debug "path outside project dir ($PROJECT_CANONICAL), pass through"
      exit 0
    fi
  fi
fi

# ── Map tool type to access filter ───────────────────────────────────────────

case "$TOOL_TYPE" in
  read)  ACCESS_FILTER='read|both' ;;
  write) ACCESS_FILTER='write|both' ;;
  edit)  ACCESS_FILTER='write|both' ;;
  bash)  ACCESS_FILTER='bash' ;;
  *)     exit 0 ;;
esac

# ── Load permissions from SKILL.md frontmatter ───────────────────────────────

if [[ -z "$SKILL_DIR" ]]; then
  debug "no skill dir provided, pass through"
  exit 0
fi

SKILL_MD="$SKILL_DIR/SKILL.md"
if [[ ! -f "$SKILL_MD" ]]; then
  debug "no SKILL.md at $SKILL_MD, pass through"
  exit 0
fi

debug "loading permissions from: $SKILL_MD"

PERM_JSON=$(python3 - "$SKILL_MD" <<'PYEOF'
import sys, re, json

skill_path = sys.argv[1]
with open(skill_path) as f:
    content = f.read()

parts = content.split("---", 2)
frontmatter_text = parts[1] if len(parts) >= 3 else ""

paths = []
bash = []

lines = frontmatter_text.splitlines()
in_permissions = False
in_paths = False
in_bash = False
current_path = {}

def unescape_yaml_dq(s):
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == '\\': result.append('\\'); i += 2
            elif nxt == '"': result.append('"'); i += 2
            elif nxt == 'n': result.append('\n'); i += 2
            elif nxt == 't': result.append('\t'); i += 2
            elif nxt == '/': result.append('/'); i += 2
            else: result.append(s[i]); i += 1
        else:
            result.append(s[i]); i += 1
    return ''.join(result)

for line in lines:
    stripped = line.rstrip()
    if stripped == "permissions:":
        in_permissions = True
        in_paths = False
        in_bash = False
        continue
    if in_permissions:
        if re.match(r"^  paths:\s*$", stripped):
            in_paths = True
            in_bash = False
            continue
        elif re.match(r"^  bash:\s*$", stripped):
            in_bash = True
            in_paths = False
            continue
        elif re.match(r"^\S", stripped):
            break

        if in_paths:
            m = re.match(r'^\s+- pattern:\s+"(.+)"', stripped)
            if m:
                current_path = {"pattern": unescape_yaml_dq(m.group(1))}
                continue
            m = re.match(r"^\s+access:\s+(\S+)", stripped)
            if m and current_path:
                current_path["access"] = m.group(1)
                paths.append(current_path)
                current_path = {}
                continue

        if in_bash:
            m = re.match(r'^\s+- "(.+)"', stripped)
            if m:
                bash.append(unescape_yaml_dq(m.group(1)))
                continue

if not paths and not bash:
    sys.exit(2)

print(json.dumps({"paths": paths, "bash": bash}))
PYEOF
) || { debug "no permissions in SKILL.md or parse failed, pass through"; exit 0; }

[[ -z "$PERM_JSON" ]] && { debug "empty permissions JSON, pass through"; exit 0; }

# ── Evaluate permissions ──────────────────────────────────────────────────────

debug "checking permissions from SKILL.md"

if [[ "$TOOL_TYPE" == "bash" ]]; then
  while IFS= read -r pattern; do
    [[ -z "$pattern" ]] && continue
    debug "  bash pattern: $pattern"
    # Reject trivially permissive patterns (no literal characters).
    _tmp="$pattern"
    _tmp="${_tmp//.}"; _tmp="${_tmp//\*}"; _tmp="${_tmp//+}"; _tmp="${_tmp//\?}"
    _tmp="${_tmp//^}"; _tmp="${_tmp//\$}"; _tmp="${_tmp//\(}"; _tmp="${_tmp//\)}"
    _tmp="${_tmp//\{}"; _tmp="${_tmp//\}}"; _tmp="${_tmp//\[}"; _tmp="${_tmp//\]}"
    _tmp="${_tmp//|}"; _tmp="${_tmp//\\}"
    if [[ -z "$_tmp" ]]; then
      debug "  skip pattern (no literal chars, too permissive): $pattern"
      continue
    fi
    unset _tmp
    rc=0
    grep -qE "$pattern" /dev/null 2>/dev/null || rc=$?
    if [[ $rc -eq 2 ]]; then continue; fi
    if echo "$COMMAND" | grep -qE "$pattern"; then
      approve
    fi
  done < <(echo "$PERM_JSON" | jq -r '.bash[]? // empty')
else
  while IFS=$'\t' read -r glob access; do
    [[ -z "$glob" ]] && continue
    if ! echo "$access" | grep -qE "^($ACCESS_FILTER)$"; then
      debug "  skip pattern '$glob' (access=$access, need=$ACCESS_FILTER)"
      continue
    fi

    regex=$(glob_to_regex "$glob")
    debug "  path pattern: $glob -> regex: $regex"
    echo "$regex" | grep -qE '' 2>/dev/null || continue

    if echo "$CANONICAL" | grep -qE "(^|/)${regex}$"; then
      approve
    else
      debug "  no match"
    fi
  done < <(echo "$PERM_JSON" | jq -r '.paths[]? | [.pattern, .access] | @tsv')
fi

debug "no match in SKILL.md permissions, passing through"
exit 0
