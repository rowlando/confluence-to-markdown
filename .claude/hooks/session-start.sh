#!/bin/bash
# Install the agent skills declared in apm.yml (pinned by apm.lock.yaml) into
# .claude/skills/, much like `npm install` restores node_modules/.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
export PATH="$HOME/.local/bin:$PATH"

# Hook stdout is added to Claude's context, so send tool output to stderr.
if ! command -v apm >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv tool install apm-cli >&2
  else
    pip install --user apm-cli >&2
  fi
fi

apm install >&2
