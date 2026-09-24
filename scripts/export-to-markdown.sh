#!/usr/bin/env bash
#
# export-to-markdown.sh — end-to-end orchestrator.
#
# Chains the two composable tools in this repo:
#   1. confluence-word-export  (download a Confluence hierarchy as Word .doc)
#   2. word-to-markdown        (convert that tree to Markdown)
#
# Usage:
#   scripts/export-to-markdown.sh ROOT_PAGE_URL [OPTIONS]
#
# Options:
#   --docs DIR       Where to download the Word .doc files
#                    (default: ./confluence-export)
#   --markdown DIR   Where to write the Markdown tree
#                    (default: ./markdown-export)
#   --backend NAME   HTML->Markdown backend: markitdown (default) | pandoc
#   --clean-names    Turn Confluence "+"-encoded names into spaced names
#   --overwrite      Replace existing files in both steps
#
# Any additional arguments after `--` are passed through to
# confluence-word-export, e.g.:
#   scripts/export-to-markdown.sh URL --clean-names -- --include security
#
# Authentication for the download step is read from CONFLUENCE_EMAIL and
# CONFLUENCE_API_TOKEN, exactly as documented for confluence-word-export.

set -euo pipefail

DOCS_DIR="./confluence-export"
MARKDOWN_DIR="./markdown-export"
BACKEND="markitdown"
CLEAN_NAMES=""
OVERWRITE=""
ROOT_URL=""
EXPORT_PASSTHROUGH=()

usage() {
  sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# --- Parse arguments --------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docs)        DOCS_DIR="$2"; shift 2 ;;
    --markdown)    MARKDOWN_DIR="$2"; shift 2 ;;
    --backend)     BACKEND="$2"; shift 2 ;;
    --clean-names) CLEAN_NAMES="--clean-names"; shift ;;
    --overwrite)   OVERWRITE="--overwrite"; shift ;;
    -h|--help)     usage 0 ;;
    --)            shift; EXPORT_PASSTHROUGH=("$@"); break ;;
    -*)            echo "error: unknown option: $1" >&2; usage 2 ;;
    *)
      if [[ -z "$ROOT_URL" ]]; then
        ROOT_URL="$1"; shift
      else
        echo "error: unexpected argument: $1" >&2; usage 2
      fi
      ;;
  esac
done

if [[ -z "$ROOT_URL" ]]; then
  echo "error: ROOT_PAGE_URL is required" >&2
  usage 2
fi

# --- Step 1: download -------------------------------------------------------
echo ">> [1/2] Downloading Word documents from Confluence..."
confluence-word-export "$ROOT_URL" \
  --output "$DOCS_DIR" \
  ${OVERWRITE:+$OVERWRITE} \
  ${EXPORT_PASSTHROUGH[@]+"${EXPORT_PASSTHROUGH[@]}"}

# --- Step 2: convert --------------------------------------------------------
echo ">> [2/2] Converting Word documents to Markdown..."
word-to-markdown "$DOCS_DIR" \
  --output "$MARKDOWN_DIR" \
  --backend "$BACKEND" \
  ${CLEAN_NAMES:+$CLEAN_NAMES} \
  ${OVERWRITE:+$OVERWRITE}

echo ">> Done. Markdown written to: $MARKDOWN_DIR"
