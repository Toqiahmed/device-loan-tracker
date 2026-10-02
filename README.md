# Device Loan Tracker

A simple web app for tracking who has borrowed which device (laptops, tablets, iPads and more), when it is due back, and the full loan history of every device. Built for a school / office IT team.

**Live demo:** https://YOUR-APP-NAME.onrender.com  *(sample data, resets every hour; the first load may take about a minute to wake up)*

![Dashboard screenshot](docs/dashboard.png)

## Features
- Track devices by **serial number**, with **category** (Staff / Student / Other), **type** (Laptop, Tablet, iPad...), model and owner
- **Loan out / mark returned** in one click. Date and time are recorded automatically
- Optional **due date**, with **in-app alerts**: overdue, due today and due soon, plus a countdown on each loan
- **Availability counts** per category (for example, "5 staff devices available") and quick filters
- **History** icon on every device: who borrowed it, when, and whether it came back late
- **Bulk edit and delete** with checkboxes, and a full **edit device** page
- Search, **CSV export**, light / dark theme
- Optional email reminders on the due date
- Runs locally, on a home server, or as a Windows `.exe`

## Tech stack
Python, Flask, SQLite, Jinja2, vanilla HTML / CSS / JavaScript (no external dependencies at runtime).

## Run it locally
```bash
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000. Data is stored in `loans.db`.

Try the demo data locally: set `DEMO_MODE=1` before running (PowerShell: `$env:DEMO_MODE="1"; python app.py`).

## Windows installer
Run `build_exe.bat` to create `dist\DeviceLoans.exe`, then compile `installer.iss` with Inno Setup for a Setup installer.

## Deploy a public demo (Render, free)
1. Push this folder to GitHub.
2. On render.com: **New > Web Service**, connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app`
5. Add environment variable `DEMO_MODE` = `1`.

## Note
There is no login system. It is designed for personal or internal use. Do not expose a real-data instance to the public internet.

Created by Touqeer.
