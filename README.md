# Webex Spaces Exporter

This Python script retrieves the Webex group spaces you belong to and writes two files: `WebexSpaces.txt` and `WebexSpaces.csv`. Each file contains space names and deep links that open the space in the Webex app.

## Prerequisites

- Python 3.8 or later
- A Webex personal access token with `spark:rooms_read` scope

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

4. Set your Webex access token as an environment variable.

   You can create a token in the [Webex Developer Portal](https://developer.webex.com/docs/getting-started).

   ```bash
   export WEBEX_ACCESS_TOKEN="your-personal-access-token"
   ```

   On Windows (Command Prompt):

   ```cmd
   set WEBEX_ACCESS_TOKEN=your-personal-access-token
   ```

   On Windows (PowerShell):

   ```powershell
   $env:WEBEX_ACCESS_TOKEN = "your-personal-access-token"
   ```

## Usage

Run the script from the repository directory:

```bash
python export_webex_spaces.py
```

Optional output paths:

```bash
python export_webex_spaces.py --txt my-spaces.txt --csv my-spaces.csv
```

After execution, the script creates:

- `WebexSpaces.txt`: Plain text listing of space names and deep links
- `WebexSpaces.csv`: Tab-separated CSV with a header row (`Space Name`, `Space Link`)

The script paginates through all results from the Webex API and exports group spaces sorted by last activity.

## Security Note

Do not hardcode your Webex access token in source code or commit it to version control. Use environment variables or another secure secret store. Rotate tokens if they are exposed.

## Contributing

Contributions are welcome. Fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License.
