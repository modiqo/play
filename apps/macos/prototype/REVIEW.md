# Prototype review evidence

The prototype was reviewed in Chrome on this Mac on September 23, 2026.
All actions below used sample data. No production services or installers were invoked.

## Interaction checks passed

- Email code entry rejects an incorrect code and accepts the documented demo code.
- Google and GitHub simulations continue into organization setup.
- Company creation and the optional colleague list work.
- Skipping an organization also skips invitations.
- Harnesses start selected; clearing every choice disables installation review.
- The plan shows Play, Rote, selected harnesses, and configuration backup.
- The interrupted-install state resumes and reaches completion.
- Existing harnesses remain visible when unselected and retain their prior Play version.
- A paired update brings Play, Rote, and all selected integrations to the target versions.
- Completion and Home show the installed harnesses and their individual Play versions.
- Selecting Codex changes cheat-sheet prompts to the canonical `$play` entry.
- Search groups sample results by organization, personal account, and community.
- Organization filters and empty-result recovery work.
- Light and dark appearance render correctly.
- At 1024 × 768 and 540 × 800, the document has no horizontal overflow.
- Compact navigation reaches Updates. The temporary viewport override was reset.
- No browser console errors or warnings were observed during the checks.

JavaScript syntax checks and local asset checks passed. The wordmark matches the website source byte for byte.
The prototype has no network API client or persistent account storage.
These checks do not validate live authentication, search relevance, native accessibility, or production installation.

## Copy review

Route: README uses desk row 4, how-to plus a separate native handoff reference; interface copy uses core rules.
Target prompt: how to set up Play across installed harnesses. This is an internal prototype, not an indexed acquisition page.
Conservation: new artifacts; all requested flows remain present, including existing installations and paired updates.
Skim: pass. Setup actions, installed harnesses, version changes, and prototype limitations remain visible in the extract.
The numbered-list extract starts with a numeral; the rendered steps were reviewed in context.
GEO extraction: Modiqo is the brand, Play is the installed experience and artifact, and Rote is the existing runtime.
Renderability: README is plain Markdown; prototype body copy renders in JavaScript. Public search indexing is disabled.
SPECULATIVE: Things, Linear, and Raycast inform the visual direction; their beauty is a design judgment.
Recommendation testing is not meaningful for this internal prototype. No external discoverability improvement is claimed.

### Interface copy: no lint failures

233 text units; average 4.8 words. No sentence exceeds the configured cap.

- WAIVE S-04 L1: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L5: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L35: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L89: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L91: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L97: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L117: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L153: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L213: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L225: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L227: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L231: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L233: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L261: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L267: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L277: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L277: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-05 L283: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-05 L305: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L307: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L341: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L361: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-05 L363: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L383: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.

### README: no lint failures

57 text units; average 9.8 words. No sentence exceeds the configured cap.

- WAIVE S-04 L3: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE T-02 L16: The extract combines separate numbered steps; each step remains a distinct action under T-03.
- WAIVE S-05 L16: The installed item or simulated action is the user’s subject; retain patient focus under S-05.
- WAIVE S-04 L25: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L30: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L37: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L45: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L72: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L72: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.
- WAIVE S-04 L98: The words include verbs, qualifiers, or separate control labels; retain precise names under Law 1.


## Exploration examples and account link

The fourth cheat-sheet step now uses `explore` with four copyable example prompts.
The header links directly to `https://www.modiqo.ai/account` for organization creation.
Browser review confirmed `/play explore` for Claude Code and `$play explore` for Codex.
The copied pricing prompt includes Notion extraction, parallel-cli research, and a sourced comparison.
JavaScript syntax and whitespace checks passed.

Copy review: core rules; 19 text units, 9.7 words on average, no failures.
WAIVE S-04 L3 (three warnings): the pricing prompt contains ordinary verbs and necessary comparison fields; preserve precision under Law 1.
Conservation: the requested Notion, pricing-table, competitor-grid, and parallel-cli details remain present.
Skim: pass; the four titles name concrete tasks and the header names its destination action.
SPECULATIVE: these are example prompts, not verified published Plays or measured outcomes.
