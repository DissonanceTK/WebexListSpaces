# Webex Spaces Exporter

This Python script retrieves the Webex group spaces you belong to and writes two files: `WebexSpaces.txt` and `WebexSpaces.csv`. Each file contains space names, a deep link that opens the space in the Webex desktop/mobile app, and a web link that opens it in Webex for web.

## Prerequisites

- Python 3.8 or later
- A Webex personal access token with at least `spark:rooms_read` scope
- `spark:teams_read` scope if you use `--group-by team`

Create a token in the [Webex Developer Portal](https://developer.webex.com/docs/getting-started).

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/DissonanceTK/WebexListSpaces.git
   cd WebexListSpaces
   ```

2. (Recommended) Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set your Webex access token:

   ```bash
   export WEBEX_ACCESS_TOKEN="your-personal-access-token"
   ```

   Windows (Command Prompt):

   ```cmd
   set WEBEX_ACCESS_TOKEN=your-personal-access-token
   ```

   Windows (PowerShell):

   ```powershell
   $env:WEBEX_ACCESS_TOKEN = "your-personal-access-token"
   ```

## Usage

Basic export:

```bash
python export_webex_spaces.py
```

Custom output paths:

```bash
python export_webex_spaces.py --txt my-spaces.txt --csv my-spaces.csv
```

Group spaces by Webex team, creator, or both:

```bash
python export_webex_spaces.py --group-by team
python export_webex_spaces.py --group-by creator
python export_webex_spaces.py --group-by team,creator
```

Progress is printed while spaces are fetched (one line per API page). Use `--quiet` to disable it.

### Eurl links (optional)

[Eurl](https://eurl.io) gives a space a join link like `https://eurl.io/#<shortId>`. The ID is assigned by the Eurl bot, so it can't be derived from the Webex room ID. To include it:

1. Sign in at https://eurl.io (it asks for your email), then open https://eurl.io/api/spaces in the same browser and save the JSON, e.g. as `eurl.json`.
2. Run:

   ```bash
   python export_webex_spaces.py --eurl-file eurl.json
   ```

This adds an `Eurl` column to the CSV and an `Eurl:` line to the TXT. Matching is by space title, so only spaces with `list` enabled in Eurl will match, and titles shared by more than one space are left blank (with a warning). Nothing is posted to Webex or Eurl.

### Output files

**`WebexSpaces.txt`** — plain text listing of space names and deep links.

Without grouping:

```
Space Name: Project Alpha
Space Link: webexteams://im?space=...
Space Web Link: https://web.webex.com/spaces/...

Space Name: Support Queue
Space Link: webexteams://im?space=...
Space Web Link: https://web.webex.com/spaces/...
```

With `--group-by team,creator`:

```
=== Team: Engineering ===

--- Created by me ---

Space Name: Project Alpha
Space Link: webexteams://im?space=...
Space Web Link: https://web.webex.com/spaces/...

--- Created by others ---

Space Name: Support Queue
Space Link: webexteams://im?space=...
Space Web Link: https://web.webex.com/spaces/...
```

**`WebexSpaces.md`** — optional (`--md`). Grouping becomes `##`/`###` headings, and each space is a bullet with App, Web and (if available) Eurl links:

```markdown
## Team: Engineering

### Created by me

- **Project Alpha** — [App](webexteams://im?space=...) · [Web](https://web.webex.com/spaces/...) · [Eurl](https://eurl.io/#...)
```

**`WebexSpaces.csv`** — tab-separated values with a header row.

| Mode | CSV columns |
| --- | --- |
| Default | `Space Name`, `Space Link`, `Space Web Link` |
| `--group-by team` | `Team`, `Space Name`, `Space Link`, `Space Web Link` |
| `--group-by creator` | `Creator`, `Space Name`, `Space Link`, `Space Web Link` |
| `--group-by team,creator` | `Team`, `Creator`, `Space Name`, `Space Link`, `Space Web Link` |

### Grouping behavior

- **Team** — spaces are grouped under their Webex Team name. Spaces with no team appear under `No team`.
- **Creator** — spaces you created are labeled `Created by me`; all others are `Created by others`.
- **Team + creator** — nested groups: team first, then creator within each team.

Webex App **space sections** (personal folders you create in the client) are not available through the Webex API and cannot be exported by this script.

### Command-line options

| Option | Default | Description |
| --- | --- | --- |
| `--txt` | `WebexSpaces.txt` | Output text file path |
| `--csv` | `WebexSpaces.csv` | Output CSV file path |
| `--md` | _(off)_ | Also write Markdown; optional path (default `WebexSpaces.md`) |
| `--group-by` | _(none)_ | Comma-separated fields: `team`, `creator` |
| `--sort-by` | `id` | API sort order: `id`, `lastactivity`, or `created` |
| `--page-size` | `100` | Rooms requested per API page |
| `--max-pages` | `1000` | Safety limit on API pages fetched |
| `--max-empty-pages` | `25` | Stop after this many consecutive empty pages |
| `--eurl-file` | _(none)_ | JSON saved from `eurl.io/api/spaces`; adds an `Eurl` column |
| `--quiet` | off | Disable progress output |

By default, spaces are sorted by room ID during API pagination for reliable results on large accounts. Use `--sort-by lastactivity` if you prefer activity order, though Webex documents limitations for accounts in thousands of spaces.

Example with additional options:

```bash
python export_webex_spaces.py --group-by team,creator --sort-by id --page-size 100 --max-pages 1000
```

### Large accounts and interruptions

The script fetches all spaces from the Webex API with pagination guardrails to avoid infinite loops. If you press Ctrl+C while fetching, any spaces retrieved up to that point are written to the output files before the script exits.

## Security Note

Do not hardcode your Webex access token in source code or commit it to version control. Use environment variables or another secure secret store. Rotate tokens if they are exposed.

## Contributing

Contributions are welcome. Fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License.
