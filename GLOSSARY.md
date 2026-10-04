# Confluence to Markdown

Turns a Confluence page hierarchy into a local tree of Markdown, by way of each page's Word export, so that AI tools and people can read it offline.

## Language

### Pages

**Root page**:
The Confluence page whose URL the user supplies; the top of the hierarchy being exported.

**Descendant**:
Any page beneath the root page, at any depth.
_Avoid_: Child (unless meaning a direct child), sub-page

**Selected page**:
A page that will be downloaded: a descendant (or the root page, when asked for) that passes the title filters and has no excluded ancestor.
_Avoid_: Included page, eligible page

### Filtering

**Include term**:
A title substring; when any are given, only pages whose titles contain at least one are selected.

**Exclude term**:
A title substring that excludes any page whose title contains it, overriding include terms.
_Avoid_: Ignore term

**Ignore file**:
A persistent list of exclude terms, one per line.

**Excluded**:
Removed by an exclude term, together with its whole subtree.
_Avoid_: Filtered out, ignored

**Unselected**:
Not matched by any include term; the page itself is not downloaded, but its selected descendants still are, in their proper place.
_Avoid_: Excluded

### Outputs

**Word export**:
The file Confluence produces when one page is exported to Word.
_Avoid_: Word document, Word file, exported document

**Word export tree**:
The folder tree of Word exports, mirroring the page hierarchy.

**Markdown tree**:
The folder tree of Markdown files converted from a Word export tree, mirroring it.

**Mirrored hierarchy**:
The shared shape of the Word export tree and the Markdown tree, which follows the Confluence page hierarchy.

**Skipped**:
Left untouched because its output already exists; never a filtering outcome.

### Process

**Run**:
One invocation of either tool.
_Avoid_: Export (as a noun), job
