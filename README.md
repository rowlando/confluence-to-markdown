# Confluence Word Export &rarr; Markdown

[![CI](https://github.com/rowlando/confluence-to-markdown/actions/workflows/ci.yml/badge.svg)](https://github.com/rowlando/confluence-to-markdown/actions/workflows/ci.yml)

Two small, composable command-line tools (plus a shell script that chains them):

1. **`confluence-word-export`** — downloads a Confluence page hierarchy as Word
   exports. Given the URL of a root page, it discovers descendant pages via the
   Confluence REST API, filters them by title, and downloads each selected page's
   Word export into a Word export tree that mirrors the Confluence hierarchy.
2. **`word-to-markdown`** — converts that Word export tree into a mirrored
   Markdown tree, which is much friendlier for agentic tools like GitHub Copilot
   and Claude Code.

The `scripts/export-to-markdown.sh` orchestrator runs both steps end-to-end.

## Why this exists

This is a small stopgap tool, not a production system. It exists because
useful reference material tends to be scattered across Confluence, SharePoint,
and GitHub, while the AI tools people actually work in day to day (GitHub
Copilot, Claude Code, ChatGPT Enterprise, MS 365 Copilot) generally work best
with plain Markdown, not a wiki's native rendering. Until those tools and
content sources are better streamlined and natively connected, this tool
bridges the gap by turning a Confluence page hierarchy into a local Markdown
tree.

Some possible use cases:

- Giving GitHub Copilot or Claude Code local, `@workspace`-searchable
  Markdown context for a Confluence space (e.g. architecture principles,
  security guardrails) instead of copy-pasting page content into chats.
- Uploading the Markdown tree into a ChatGPT Enterprise project/knowledge
  base, which handles Markdown far better than scraped HTML.
- Keeping an offline, greppable, diffable snapshot of a Confluence space
  for use in a git repo, without a live Confluence connection.

These are examples, not requirements the tool enforces — it just produces
plain Markdown files and lets you decide what to do with them.

## Quickstart

```bash
# 1. Clone and set up a virtual environment
git clone <this-repo-url>
cd confluence-to-markdown
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the tools (editable install; requires Python 3.11+)
pip install -e .

# 3. Set your Confluence credentials for this shell session
export CONFLUENCE_EMAIL="you@example.com"
read -s CONFLUENCE_API_TOKEN   # paste an API token, then press Enter
export CONFLUENCE_API_TOKEN
echo

# 4. Run the end-to-end orchestrator on a Confluence page URL
scripts/export-to-markdown.sh \
  "https://your-site.atlassian.net/wiki/spaces/KEY/pages/12345/Title"
```

That downloads the page hierarchy as Word exports into
`./confluence-export`, then converts them to Markdown in
`./markdown-export`. See the sections below for filtering, options, and
running each tool independently.

## Install

```bash
pip install -e .
```

This exposes the `confluence-word-export` and `word-to-markdown` commands. You
can also run them as modules:

```bash
python -m confluence_word_export --help
python -m word_to_markdown --help
```

## Authentication

Credentials are read from environment variables and used as HTTP Basic auth.
They are never logged, printed, or written to disk.

```bash
export CONFLUENCE_EMAIL="you@example.com"
read -s CONFLUENCE_API_TOKEN
export CONFLUENCE_API_TOKEN
echo
```

Create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>.

## Usage

```text
confluence-word-export ROOT_PAGE_URL [OPTIONS]
```

A basic run (the root page itself is not downloaded unless you pass
`--include-root`):

```bash
confluence-word-export \
  "https://your-site.atlassian.net/wiki/spaces/KEY/pages/12345/Title" \
  --output ./exports
```

A filtered run:

```bash
confluence-word-export URL \
  --include security --include architecture \
  --exclude draft --exclude archive \
  --output ./exports
```

Preview without downloading:

```bash
confluence-word-export URL --list-only
```

### Options

| Option | Description |
| --- | --- |
| `--output PATH` | Output directory (default `./confluence-export`). |
| `--include TEXT` | Include term: select only pages whose titles contain TEXT (repeatable, OR semantics). |
| `--exclude TEXT` | Exclude term: exclude pages whose titles contain TEXT, with their whole subtrees (repeatable). |
| `--ignore-file PATH` | Ignore file of extra exclude terms (default `./.confluence-word-export-ignore` if present). |
| `--include-root` | Also download the supplied root page. |
| `--list-only` | Show selected pages and intended paths without downloading. |
| `--format {text,json}` | Output format (default `text`). `json` writes one JSON object per line (JSON Lines) to stdout — see [Scripting / composability](#scripting--composability). |
| `--manifest PATH` | Also write a JSON Lines record of every page processed to PATH, regardless of `--format`. |
| `--overwrite` | Replace existing Word exports (default: skip). |
| `--verbose` | Show extra detail, including excluded and unselected pages. |
| `--ca-bundle PATH` | Trust an additional CA bundle (e.g. a corporate proxy CA). |
| `--system-certs` / `--no-system-certs` | Use / skip the OS trust store (auto-enabled when `truststore` is installed). |
| `--insecure` | Disable TLS certificate verification (not recommended). |
| `--version` | Show the version. |
| `--help` | Show usage. |

## Filtering rules

- Matching is case-insensitive literal substring on page titles only.
- Include terms use OR semantics; with no include terms, every page is selected
  unless it is excluded.
- Exclude terms (from `--exclude` and the ignore file) always override include
  terms.
- A page is **excluded** when its title contains an exclude term. Its **entire
  subtree** is excluded with it: no descendant is downloaded and no directory is
  created for it, so a section such as "Archived" is left out in full.
- A page is **unselected** when include terms are given and its title contains
  none of them. Only that page is left out: its selected descendants are still
  downloaded, in their proper place in the mirrored hierarchy.

## Ignore file

By default the tool looks for `.confluence-word-export-ignore` in the current
directory. Each non-empty line is an exclude term (a case-insensitive title substring);
lines beginning with `#` are comments. See
[`.confluence-word-export-ignore.sample`](.confluence-word-export-ignore.sample).

## Output layout

A page that has children is represented as both a Word export and a directory:

```text
exports/
└── Acme Docs/
    ├── Getting started.doc
    ├── Getting started/
    │   ├── Installation.doc
    │   └── Configuration.doc
    └── Architecture overview.doc
```

Filenames come from the Confluence `Content-Disposition` header, so the correct
extension (`.doc`, `.docx`, …) is preserved. Names are sanitised, and sibling
collisions are disambiguated with the page ID.

## Convert to Markdown

The `word-to-markdown` command turns a Word export tree into a mirrored Markdown
tree.

```bash
word-to-markdown ./confluence-export --output ./markdown-export --clean-names
```

### How it works

Confluence's "Export to Word" endpoint does **not** produce a genuine binary
Word file — each Word export (`.doc`) is actually an **MHTML**
(`multipart/related`) container holding a quoted-printable HTML part plus
embedded images. So the converter:

1. Detects and unpacks the MHTML container (pure Python, standard library).
2. Writes the embedded images into a `*.assets/` folder beside each Markdown
   file and rewrites the image links so they keep working in the Markdown.
3. Converts the cleaned HTML to Markdown via a swappable backend.

Genuine `.docx`/binary `.doc` and plain `.html` files are handed straight to the
backend, so the same command works on mixed inputs.

### Backends

| Backend | Notes |
| --- | --- |
| `markitdown` (default) | LLM-friendly Markdown, proper `![](…)` image links. Pure Python dependency. |
| `pandoc` (`--backend pandoc`) | Higher-fidelity conversion that preserves complex tables. Requires the external `pandoc` binary. |

Both render simple tables as GitHub-Flavored-Markdown pipe tables. For very
table-heavy pages (e.g. the "Traceability Matrix" pages), `--backend pandoc`
preserves complex tables that markitdown may simplify.

### Options

| Option | Description |
| --- | --- |
| `--output PATH` | Output directory (default `./markdown-export`). |
| `--backend NAME` | `markitdown` (default) or `pandoc`. |
| `--overwrite` | Replace existing Markdown and embedded images (default: skip existing). |
| `--clean-names` | Turn Confluence `+`-encoded names into ordinary spaced names. |
| `--flatten` | Do not mirror subdirectories; write every `.md` in the output root. |
| `--list-only` | Show what would be converted without writing anything. |
| `--format {text,json}` | Output format (default `text`). `json` writes one JSON object per line (JSON Lines) to stdout — see [Scripting / composability](#scripting--composability). |
| `--manifest PATH` | Also write a JSON Lines record of every file processed to PATH, regardless of `--format`. |
| `--verbose` | Show extra detail, including skipped files. |
| `--version` / `--help` | Show version / usage. |

### Output layout

The Word export tree is mirrored, with each `.doc` becoming a `.md` and any
embedded images written alongside:

```text
markdown-export/
└── Getting started/
    ├── Installation.md
    └── Installation.assets/
        ├── 0dbc309d…​.png
        └── 98e78675…​.png
```

## End-to-end orchestrator

`scripts/export-to-markdown.sh` chains both tools: download, then convert.

```bash
export CONFLUENCE_EMAIL="you@example.com"
read -s CONFLUENCE_API_TOKEN; export CONFLUENCE_API_TOKEN; echo

scripts/export-to-markdown.sh \
  "https://your-site.atlassian.net/wiki/spaces/KEY/pages/12345/Title" \
  --docs ./confluence-export \
  --markdown ./markdown-export \
  --clean-names
```

Arguments after `--` are passed through to `confluence-word-export`, e.g.
`scripts/export-to-markdown.sh URL --clean-names -- --include security`.

## Scripting / composability

Both CLIs support `--format json`, writing one JSON object per line (JSON
Lines / NDJSON) to stdout instead of prose — the human-readable notices you'd
normally see move out of the way so stdout is safe to pipe into `jq`, `xargs`,
or a future third tool. Each line has a `"type"` field (`run_started`, `page`,
`file`, `result`, or `summary`) so consumers can filter with `jq 'select(...)'`.

```bash
# Which pages would download, as a plain list of titles?
confluence-word-export URL --list-only --format json \
  | jq -r 'select(.type == "page") | .title'

# Fail a script if any conversion failed, without scraping prose:
word-to-markdown ./confluence-export --format json \
  | jq -c 'select(.type == "result" and .status == "failed")'
```

### `confluence-word-export` result statuses

Every page in the hierarchy gets one `result` line, whose `status` is one of:

| Status | Meaning |
| --- | --- |
| `DOWNLOADED` | Selected, and its Word export was written. |
| `SKIPPED` | Selected, but its Word export already exists (pass `--overwrite` to replace it). |
| `EXCLUDED` | Its title, or an ancestor's, contains an exclude term; the whole subtree is excluded. |
| `UNSELECTED` | Include terms were given and its title contains none of them; its selected descendants are still downloaded. |
| `FAILED` | Selected, but the download failed (see `error`). |

The `run_started` line counts `matchingPages` (selected), `excludedPages` and
`unselectedPages`; the final `summary` line counts `matched` (selected),
`downloaded`, `skipped`, `excluded`, `unselected` and `failed`.

> **Changed:** earlier versions reported include misses as `EXCLUDED` and
> counted them in `excludedPages`/`excluded`. They are now `UNSELECTED`,
> counted in the new `unselectedPages`/`unselected` fields, so `EXCLUDED`
> means only "removed by an exclude term". Scripts that treated `EXCLUDED` as
> "anything not downloaded" should also match `UNSELECTED`.

```bash
# Which pages were left out by an include miss?
confluence-word-export URL --include security --format json \
  | jq -r 'select(.type == "result" and .status == "UNSELECTED") | .title'
```

### Manifests

If you want a durable, parseable record of a run *without* giving up the
human-readable terminal output, use `--manifest PATH` instead (or alongside)
`--format json`: it always writes the same JSON Lines events to a file,
regardless of `--format`.

```bash
confluence-word-export URL --manifest ./last-run.jsonl
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Completed with no download failures (skips are still success). |
| 1 | One or more pages failed to download. |
| 2 | Invalid arguments or configuration. |
| 3 | Authentication or authorisation failure. |
| 4 | Root page could not be retrieved. |

## Development

Install with the dev extras (adds `pytest` and `ruff`):

```bash
pip install -e ".[dev]"
```

Run the test suite, linter, and formatter:

```bash
pytest                  # all tests (or e.g. tests/word_to_markdown)
ruff check .            # lint
ruff format .           # auto-format
```

### Project layout

```text
src/
  confluence_word_export/   # Confluence -> Word downloader package
  word_to_markdown/         # Word -> Markdown converter package
scripts/
  export-to-markdown.sh     # end-to-end orchestrator chaining both CLIs
tests/
  confluence_word_export/   # tests for the downloader
  word_to_markdown/         # tests for the converter (+ shared fixtures)
```

Both packages live under `src/` (a "src layout"), so an editable install
(`pip install -e .`) is required for imports to resolve during development.
Tests are split per package, mirroring the source tree.

### Agent skills

Claude Code skills are managed with [APM](https://github.com/microsoft/apm),
much like npm: `apm.yml` declares them (cf. `package.json`), `apm.lock.yaml`
pins the exact commits (cf. `package-lock.json`), and `apm install` puts them
into `.claude/skills/` (cf. `node_modules/`), which is git-ignored along with
APM's `apm_modules/` cache.

In Claude Code cloud sessions, a SessionStart hook
(`.claude/hooks/session-start.sh`) installs APM and runs `apm install`
automatically. Locally, run it yourself:

```bash
uv tool install apm-cli   # or: pip install apm-cli
apm install
```

To add or upgrade skills, edit `apm.yml`, run `apm install`, and commit
`apm.yml` and `apm.lock.yaml`. In cloud sessions, edit `apm.yml` rather than
running `apm install <package>`: the command-line form checks the package via
the GitHub API, which cloud sessions block for repositories not attached to
the session.

### Contributing

This is a small stopgap tool for a handful of people, so there's no separate
`CONTRIBUTING.md` or heavyweight process — just:

- Run `pytest` and `ruff check .` / `ruff format .` before opening a PR (CI
  runs the same checks on push/PR, see the badge above).
- Keep changes small and focused; add or update tests alongside behaviour
  changes.
- Prefer extending the existing composable-CLI style (see "Project layout"
  above) over adding one-off scripts.

## Corporate proxies / TLS interception

Many corporate networks intercept HTTPS with their own certificate authority.
`curl` works in this setting because it trusts your operating system's
certificate store; plain Python does not, which causes errors like
`certificate verify failed: self-signed certificate in certificate chain`.

This tool solves that automatically: it depends on
[`truststore`](https://pypi.org/project/truststore/), so by default it uses the
**OS trust store** (macOS Keychain, Windows cert store, Linux system store) —
the same CAs `curl` trusts, including any your IT team installed. TLS
verification stays fully enabled, and no configuration is needed.

If you need to override the default:

```bash
# Explicitly force / disable the OS trust store
confluence-word-export URL --system-certs
confluence-word-export URL --no-system-certs

# Trust a specific CA bundle instead
confluence-word-export URL --ca-bundle /path/to/corporate-ca.pem
export REQUESTS_CA_BUNDLE=/path/to/corporate-ca.pem
```

As a last resort you can disable verification with `--insecure` (not
recommended, prints a warning).

## Security note

Word exports, and the Markdown converted from them, inherit the sensitivity of
their source pages. Store and share them accordingly.
