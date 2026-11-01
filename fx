#!/bin/sh
# factorio-agent CLI launcher (Linux, macOS, Git Bash on Windows).
# Needs Python 3.10 or newer.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 \
      && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
          >/dev/null 2>&1; then
    exec "$py" "$here/fx.py" "$@"
  fi
done
if command -v py >/dev/null 2>&1; then exec py -3 "$here/fx.py" "$@"; fi
echo "fx: Python 3.10 or newer is needed and was not found" \
    "(tried python3, python, py)" >&2
exit 127
