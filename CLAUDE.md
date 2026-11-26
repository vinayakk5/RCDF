# RCDF Supply

Read `HANDOFF.md` first: it has the business workflow, code map, branches, how to run the app,
what was done so far and the open items.

- Run: `cd backend; ..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`
- Tests: `cd backend; python -m unittest discover -s tests` (SQLite only, never touches MySQL)
- Take a MySQL backup before any migration or bulk change on the live database.
- Quantities are quintals even where columns say `_mt`.
