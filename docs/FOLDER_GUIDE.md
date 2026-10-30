# Where things live

Keep the project shallow: one place for the screens, one for calculations, one for checks.

```text
bat-activity-analysis-platform/
|-- app.py                 Streamlit screens and user workflow
|-- bat_activity/          Calculation, validation, mapping and export code
|-- tests/                 Calculation and screen checks
|   `-- data/willow_beck/   Two synthetic CSV fixtures for the 1,000-contact check
|-- static/brand/          Logos, local font and its licence
|-- .streamlit/config.toml App appearance and static-file settings
|-- docs/                  Short project documentation
|-- requirements.txt       Packages needed by the project
|-- README.md              Project introduction and running instructions
`-- .gitignore             Files that stay off GitHub
```

Within `bat_activity`, filenames describe their job: `contacts` handles source rows and counting, `analysis` builds reporting tables, `figures` draws charts, and `word_results` creates the Word output. `models` stores the project structure, `workflow` applies version-one rules, and `word_project` saves/reloads settings.

## Local-only folders

`outputs/` holds generated files and manual trial materials. `tmp/` holds scratch work, logs and backups. `references/` holds reading material. These stay on the local computer, along with `.venv/`, caches, secrets and the development handover Markdown files.

The original worked example and trial files are preserved locally. Automated tests use the synthetic copies under `tests/data/`, so a GitHub checkout does not depend on local outputs.

Use `docs/` for future public explanations or selected screenshots. There is no need for more folders until they contain something useful.
