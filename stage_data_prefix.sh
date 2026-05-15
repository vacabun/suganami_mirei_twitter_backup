#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_DIR="${ARCHIVE_DIR:-gallery-dl/twitter/suganami_mirei}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH_NAME="${BRANCH_NAME:-main}"

usage() {
  cat <<'EOF'
Usage:
  bash stage_data_prefix.sh [--dry-run] [--commit] [--push] [--auto] <group> [<group> ...]

Examples:
  bash stage_data_prefix.sh --dry-run meta 109 110
  bash stage_data_prefix.sh 109
  bash stage_data_prefix.sh --commit 109
  bash stage_data_prefix.sh --commit --push meta 109 110
  bash stage_data_prefix.sh --commit --push --auto 109

Notes:
  - Files are force-added even though gallery-dl/ is gitignored.
  - Smaller prefixes are safer. For this archive, 3-digit prefixes
    like 109 / 110 / 111 are much more practical than the whole 1* set.
  - --push implies --commit, and pushes each group right after its commit.
  - --auto expands the last numeric prefix to all later same-length prefixes.
EOF
}

dry_run=0
do_commit=0
do_push=0
auto_mode=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --commit)
      do_commit=1
      shift
      ;;
    --push)
      do_push=1
      do_commit=1
      shift
      ;;
    --auto)
      auto_mode=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

groups=("$@")

if [[ ! -d "$ARCHIVE_DIR" ]]; then
  echo "Archive directory not found: $ARCHIVE_DIR" >&2
  exit 1
fi

expand_auto_groups() {
  python3 - "$ARCHIVE_DIR" "$@" <<'PY'
import sys
from pathlib import Path

archive_dir = Path(sys.argv[1])
groups = sys.argv[2:]

numeric = [g for g in groups if g.isdigit()]
if not numeric:
    print("\n".join(groups))
    raise SystemExit(0)

start = numeric[-1]
width = len(start)

available = sorted(
    {
        p.name[:width]
        for p in archive_dir.iterdir()
        if p.is_file() and len(p.name) >= width and p.name[:width].isdigit()
    }
)

expanded = []
used = set()
for group in groups:
    if group == start:
        for candidate in available:
            if len(candidate) == width and candidate >= start and candidate not in used:
                expanded.append(candidate)
                used.add(candidate)
    elif group not in used:
        expanded.append(group)
        used.add(group)

print("\n".join(expanded))
PY
}

if [[ $auto_mode -eq 1 ]]; then
  expanded_groups=()
  while IFS= read -r group; do
    [[ -n "$group" ]] && expanded_groups+=("$group")
  done < <(expand_auto_groups "${groups[@]}")
  groups=("${expanded_groups[@]}")
fi

group_commit_message() {
  local group="$1"
  if [[ "$group" == "meta" ]]; then
    printf '%s\n' "Add archive metadata"
  else
    printf 'Add archive data prefix %s\n' "$group"
  fi
}

collect_files() {
  local group="$1"
  files=()

  if [[ "$group" == "meta" ]]; then
    [[ -f "$ARCHIVE_DIR/info.json" ]] && files+=("$ARCHIVE_DIR/info.json")
    return 0
  fi

  if [[ ! "$group" =~ ^[0-9]+$ ]]; then
    echo "Prefix must be digits or 'meta': $group" >&2
    return 1
  fi

  while IFS= read -r file; do
    files+=("$file")
  done < <(
    find "$ARCHIVE_DIR" -maxdepth 1 -type f -print \
      | awk -v prefix="$group" '
          {
            n = split($0, parts, "/");
            name = parts[n];
            if (index(name, prefix) == 1) {
              print $0;
            }
          }
        ' \
      | sort
  )
}

print_summary() {
  local group="$1"
  shift
  python3 - "$group" "$@" <<'PY'
import sys
from pathlib import Path

label = sys.argv[1]
paths = [Path(p) for p in sys.argv[2:]]
total = sum(p.stat().st_size for p in paths)
print(f"Staging group: {label}")
print(f"Files: {len(paths)}")
print(f"Size: {total / 1024 / 1024:.1f} MB")
print("First few files:")
for path in paths[:8]:
    print(f"  - {path.name}")
PY
}

for group in "${groups[@]}"; do
  files=()
  collect_files "$group"
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "No files found for group '$group' in $ARCHIVE_DIR" >&2
    exit 1
  fi
  echo
  print_summary "$group" "${files[@]}"

  if [[ $dry_run -eq 1 ]]; then
    continue
  fi

  git add -f -- "${files[@]}"
  echo "Staged ${#files[@]} files for group: $group"

  if [[ $do_commit -eq 1 ]]; then
    message="$(group_commit_message "$group")"
    git commit -m "$message"
    echo "Committed: $message"

    if [[ $do_push -eq 1 ]]; then
      git push "$REMOTE_NAME" "$BRANCH_NAME"
      echo "Pushed: $REMOTE_NAME/$BRANCH_NAME"
    fi
  fi
done

if [[ $dry_run -eq 1 ]]; then
  echo
  echo "Dry run only. No files were staged."
  exit 0
fi

if [[ $do_commit -eq 0 ]]; then
  echo
  echo "Staging complete."
  echo "Next step:"
  if [[ ${#groups[@]} -eq 1 && "${groups[0]}" == "meta" ]]; then
    echo '  git commit -m "Add archive metadata"'
  elif [[ ${#groups[@]} -eq 1 ]]; then
    echo "  git commit -m \"Add archive data prefix ${groups[0]}\""
  else
    echo '  git commit -m "Add archive data batch"'
  fi
fi
