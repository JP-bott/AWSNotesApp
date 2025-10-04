# Notes App — DynamoDB-backed Notes (CLI + simple Flask UI)

A small command-line tool plus a minimal Flask web UI for creating, reading,
updating and deleting notes stored in a DynamoDB table. This project is
meant for local development and demos.

Contents
- `application.py` — CLI and web UI implementation (uses boto3 and Flask)
- `templates/` — Flask HTML templates used by the web UI
- `requirements.txt` — Python dependencies

Requirements
- Python 3.8 or newer
- AWS credentials configured (environment variables, AWS CLI, or IAM role)
- A DynamoDB table for notes (see Table schema)

Install
Open PowerShell and run:

```powershell
python -m pip install -r .\requirements.txt
```

Configuration
- NOTES_TABLE_NAME — optional environment variable to point to your DynamoDB table. Defaults to `Notes_Table`.
- CLI options supported by `application.py` (examples below): `--key-name`, `--sort-key`, `--user-id`, `--client-id`.

DynamoDB table schema (expected)
- Partition key: string attribute (default name: `id`).
- Optional sort (range) key is supported. If your table has a sort key, pass `--sort-key <name>` when required and include `--user-id` where applicable.

Quick start (CLI)
- Add a note:

```powershell
python .\application.py add --title "Grocery" --content "Buy milk"
```

- Add a note with a client-generated idempotency token:

```powershell
python .\application.py add --title "Grocery" --content "Buy milk" --client-id 1234-abcd
```

- List notes:

```powershell
python .\application.py list
```

- Get a note by id:

```powershell
python .\application.py get --id <note-id>
```

- Update a note (example flags — your script may prompt or accept different args):

```powershell
python .\application.py update --id <note-id> --title "New title" --content "Updated content"
```

- Delete a note:

```powershell
python .\application.py delete --id <note-id>
```

Run the web UI

```powershell
python .\application.py ui
```

By default the Flask UI listens on http://127.0.0.1:5000. Check the CLI output for the exact URL.

Examples with table/key options

- Specify a different table name via environment (PowerShell):

```powershell
$env:NOTES_TABLE_NAME = "MyNotesTable"; python .\application.py list
```

- If the table partition key is named differently:

```powershell
python .\application.py list --key-name my_partition_key
```

Troubleshooting
- No AWS credentials / AccessDenied: make sure AWS credentials are configured (AWS CLI, environment variables, or an IAM role).
- Table not found: confirm `NOTES_TABLE_NAME` matches an existing DynamoDB table in the active AWS region.
- boto3/Flask import errors: ensure dependencies were installed from `requirements.txt`.

Development notes
- This project is intended for local development. For production deployment run the Flask app under a WSGI server (gunicorn, uWSGI, etc.) and follow AWS best practices for credentials and permissions.

Files
- `application.py` — main script (CLI + web UI)
- `templates/` — Jinja2 templates used by the Flask UI (`notes.html`, `edit.html`)
- `requirements.txt` — required Python packages

License
- Public domain

If you'd like, I can also add a short CONTRIBUTING section, example environment files, or inline usage help extracted from `application.py`.
