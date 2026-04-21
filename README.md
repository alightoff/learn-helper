# Learn Helper

Minimal MVP scaffold for a local self-study web application built with FastAPI, SQLite, SQLAlchemy, Alembic, Jinja2, and HTMX-ready server-rendered templates.

## Current Scope

This repository currently contains only the application skeleton:

- FastAPI application entrypoint
- configuration layer
- SQLAlchemy database layer with the first domain schema
- Alembic migration scaffold with the initial revision
- Jinja2 base layout and dashboard placeholder
- static assets and local data directories

Implemented now:

- course creation
- module creation inside a course
- PDF upload into a module
- local file persistence under `data/uploads`
- automatic `Resource` creation
- page count extraction
- best-effort PDF outline extraction
- resource rendering on the course page

## Project Layout

```text
app/
  config.py
  main.py
  db/
  routers/
  services/
  static/
  templates/
alembic/
data/
requirements.txt
```

## Quick Start

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Optional: create a local environment file:

```powershell
Copy-Item .env.example .env
```

Environment variables use the `LEARN_HELPER_` prefix.

4. Run the database migration and start the application:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

5. Open the local app:

```text
http://127.0.0.1:8000
```

## Notes

- The app creates the local storage directories under `data/` on startup.
- SQLite is configured by default with a local database file at `data/app.db`.
- The initial Alembic revision creates the core course/resource/annotation/progress/session schema.
- PDF uploads are stored below `data/uploads/courses/<course_slug>/resources/module-<id>/`.
- If a PDF has no outline, the import still succeeds and the course page shows the resource without parsed structure.
