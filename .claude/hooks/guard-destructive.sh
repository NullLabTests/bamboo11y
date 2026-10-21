#!/usr/bin/env bash
# Claude Code PreToolUse guard. Denies clearly destructive shell commands; everything
# else is left to the permission rules in .claude/settings.json.
set -euo pipefail

payload="$(cat)"
command="$(printf '%s' "$payload" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print("")
    raise SystemExit(0)
print(data.get("tool_input", {}).get("command", ""))
')"

if [[ -z "$command" ]]; then
  exit 0
fi

reason=""
case "$command" in
  *"rm -rf /"*|*"rm -rf ~"*|*"rm -rf ."*|*"rm -rf *"*)
    reason="Recursive deletion is blocked by the Bamboo11y project guard."
    ;;
  *"git reset --hard"*|*"git clean -"*|*"git push --force"*|*"git push -f"*)
    reason="History-destroying git operations are blocked; ask the human to run them."
    ;;
  *"docker system prune"*|*"docker volume prune"*|*"docker rm -f"*)
    reason="Docker cleanup is blocked by the Bamboo11y project guard."
    ;;
  *"DROP TABLE"*|*"TRUNCATE TABLE"*|*"DELETE FROM"*)
    reason="Destructive database statements are blocked by the Bamboo11y project guard."
    ;;
esac

if [[ -n "$reason" ]]; then
  python3 -c '
import json
import sys

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": sys.argv[1],
    }
}))
' "$reason"
fi

exit 0
