"""Device Loan Tracker v4 - Flask + SQLite, single file.  Created by Touqeer.

Features: student / staff / other categories with availability counts, device types,
bulk edit & delete, edit device page, automatic loan/return timestamps, optional due date,
in-app alerts (overdue / due today / due soon), light/dark theme, optional email reminders.

Run:  pip install flask && python app.py
Open: http://localhost:5000
"""
import csv
import io
import os
import smtplib
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, url_for)
from jinja2 import DictLoader
from markupsafe import Markup

# ======================= SETTINGS (edit these) =======================
SOON_DAYS = 2            # loans due within this many days show as "due soon"

# Optional email reminders. Leave SMTP_USER empty to turn email off.
# Gmail: create an app password at https://myaccount.google.com/apppasswords
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))      # 587 = STARTTLS, 465 = SSL
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MAIL_TO = os.environ.get("MAIL_TO", SMTP_USER)
REMIND_HOUR = int(os.environ.get("REMIND_HOUR", "9"))    # send on due date from this hour (24h)
CHECK_EVERY_MIN = 30

# Public demo mode (for hosting a live link on your CV): loads sample data and wipes
# everything back to it every hour. Turn on with the environment variable DEMO_MODE=1.
DEMO = os.environ.get("DEMO_MODE") == "1"
DEMO_RESET_MIN = 60
# =====================================================================

CATEGORIES = [("staff", "Staff device"), ("student", "Student device"), ("other", "Other")]
CAT_LABEL = dict(CATEGORIES)

FROZEN = getattr(sys, "frozen", False)      # True when running as a packaged .exe


def data_dir():
    """Script: next to app.py.  Packaged .exe: a per-user folder, so data survives updates
    and works even when installed in a protected folder."""
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "DeviceLoans")
    else:
        path = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(path, exist_ok=True)
    return path


BASE_DIR = data_dir()
DB_PATH = os.path.join(BASE_DIR, "loans.db")

app = Flask(__name__)
app.secret_key = "change-me"  # only used for flash messages

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    serial_number TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    device_type   TEXT DEFAULT '',
    category      TEXT DEFAULT 'other',
    owner         TEXT DEFAULT '',
    date_added    TEXT,
    notes         TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS loans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    borrower      TEXT NOT NULL,
    contact       TEXT DEFAULT '',
    loaned_at     TEXT NOT NULL,
    due_date      TEXT,
    returned_at   TEXT,
    reminder_sent INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);
-- a device can have only one open (not yet returned) loan
CREATE UNIQUE INDEX IF NOT EXISTS one_open_loan
    ON loans(device_id) WHERE returned_at IS NULL;
"""


# ---------- icons (inline SVG, no internet needed) ----------
def _svg(body, size=18):
    return Markup(f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
                  f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                  f'stroke-linejoin="round" aria-hidden="true">{body}</svg>')


ICONS = {
    "history": _svg('<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>', 20),
    "edit": _svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>', 18),
    "trash": _svg('<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/>', 16),
    "alert": _svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
                  '<path d="M12 9v4M12 17h.01"/>', 20),
    "laptop": _svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/>', 22),
    "mail": _svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>', 16),
    "download": _svg('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>', 16),
    "theme": _svg('<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>', 16),
    "check": _svg('<path d="m5 12 5 5 9-10"/>', 20),
    "plus": _svg('<path d="M12 5v14M5 12h14"/>', 16),
    "search": _svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 16),
}

TEMPLATES = {
    "base.html": """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Device Loans{% endblock %}</title>
<script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}</script>
<style>
:root{
  --bg:#f4f5fa; --surface:#ffffff; --surface2:#f8f9fd; --text:#0f172a; --muted:#64748b; --line:#e4e7f0;
  --primary:#4f46e5; --primary-h:#4338ca; --hist:#0f766e; --hist-h:#115e59; --ok:#15803d; --ok-h:#166534;
  --bad:#dc2626; --bad-bg:#fef2f2; --warn:#b45309; --warn-bg:#fffbeb; --info:#1d4ed8; --info-bg:#eff6ff;
  --stu:#7e22ce; --stu-bg:#f5ecff;
  --ok-bg:#f0fdf4; --mute-bg:#f1f5f9; --shadow:0 1px 2px rgba(15,23,42,.06),0 4px 16px rgba(15,23,42,.05);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0b1020; --surface:#141a2e; --surface2:#182039; --text:#e8ecf7; --muted:#94a3c0; --line:#26304d;
    --primary:#6366f1; --primary-h:#7c7ff5; --hist:#0d9488; --hist-h:#14b8a6; --ok:#22a559; --ok-h:#34c071;
    --bad:#f87171; --bad-bg:#2a1620; --warn:#fbbf24; --warn-bg:#2a2214; --info:#7aa2ff; --info-bg:#14213d;
    --stu:#c4a1ff; --stu-bg:#261a3d;
    --ok-bg:#12261c; --mute-bg:#1b2440; --shadow:0 1px 2px rgba(0,0,0,.4),0 6px 20px rgba(0,0,0,.25);
  }
}
:root[data-theme="dark"]{
  --bg:#0b1020; --surface:#141a2e; --surface2:#182039; --text:#e8ecf7; --muted:#94a3c0; --line:#26304d;
  --primary:#6366f1; --primary-h:#7c7ff5; --hist:#0d9488; --hist-h:#14b8a6; --ok:#22a559; --ok-h:#34c071;
  --bad:#f87171; --bad-bg:#2a1620; --warn:#fbbf24; --warn-bg:#2a2214; --info:#7aa2ff; --info-bg:#14213d;
  --stu:#c4a1ff; --stu-bg:#261a3d;
  --ok-bg:#12261c; --mute-bg:#1b2440; --shadow:0 1px 2px rgba(0,0,0,.4),0 6px 20px rgba(0,0,0,.25);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:24px 20px 30px}
a{color:var(--primary);text-decoration:none}
code{font:12.5px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted)}

.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px;color:var(--text)}
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;
  display:grid;place-items:center;box-shadow:0 4px 14px rgba(99,102,241,.4)}
.brand h1{margin:0;font-size:20px;letter-spacing:-.02em;line-height:1.1}
.brand span{font-size:13px;color:var(--muted)}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.tools form{margin:0}

.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);padding:16px}
.section{margin-top:16px}
h2.sec{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:26px 0 10px;font-weight:600}

input,select{padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--surface2);color:var(--text);
  font:inherit;min-width:0;outline:none;transition:border-color .15s, box-shadow .15s}
input:focus,select:focus{border-color:var(--primary);box-shadow:0 0 0 3px rgba(99,102,241,.2)}
input[type=date]{color-scheme:light dark}
input[type=checkbox]{width:17px;height:17px;padding:0;accent-color:var(--primary);cursor:pointer}
.btn,button{padding:9px 16px;border:0;border-radius:10px;background:var(--primary);color:#fff;font:inherit;font-weight:600;
  cursor:pointer;display:inline-flex;align-items:center;gap:7px;transition:background .15s, transform .05s;white-space:nowrap}
.btn:hover,button:hover{background:var(--primary-h)}
.btn:active,button:active{transform:translateY(1px)}
.btn.ok{background:var(--ok)} .btn.ok:hover{background:var(--ok-h)}
.btn.danger{background:var(--bad)} .btn.danger:hover{background:var(--bad);filter:brightness(.92)}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line);font-weight:500;padding:7px 12px;font-size:13.5px}
.btn.ghost:hover{background:var(--mute-bg)}
.icon-btn{width:38px;height:38px;border-radius:10px;background:var(--hist);color:#fff;display:inline-grid;place-items:center;
  transition:background .15s, transform .05s;flex:none}
.icon-btn:hover{background:var(--hist-h);color:#fff}
.icon-btn:active{transform:translateY(1px)}
.icon-btn.neutral{background:var(--mute-bg);color:var(--text);border:1px solid var(--line)}
.icon-btn.neutral:hover{background:var(--line);color:var(--text)}

.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.grow{flex:1;min-width:140px}

/* stats */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.cats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:var(--text);
  box-shadow:var(--shadow);transition:border-color .15s;display:block}
.stat:hover{border-color:var(--primary)}
.stat.on{border-color:var(--primary);box-shadow:0 0 0 2px rgba(99,102,241,.25)}
.stat b{display:block;font-size:26px;line-height:1.15;letter-spacing:-.02em}
.stat b span{font-size:14px;font-weight:600;color:var(--muted);letter-spacing:0}
.stat small{color:var(--muted);font-size:13px;display:block}
.stat.bad b{color:var(--bad)}
.stat.cat small:first-child{font-weight:700;color:var(--text);font-size:13.5px}

/* alerts */
.alerts{border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow);overflow:hidden}
.alerts header{display:flex;align-items:center;gap:10px;padding:12px 16px;font-weight:700;border-bottom:1px solid var(--line)}
.alerts header.bad{background:var(--bad-bg);color:var(--bad)}
.alerts header.warn{background:var(--warn-bg);color:var(--warn)}
.alerts header.info{background:var(--info-bg);color:var(--info)}
.alert-row{display:flex;align-items:center;gap:12px;padding:11px 16px;border-top:1px solid var(--line);flex-wrap:wrap}
.alert-row:first-of-type{border-top:0}
.alert-row .who{flex:1;min-width:160px}
.alert-row .who b{display:block}
.alert-row .who span.m{color:var(--muted);font-size:13px}
.allclear{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:14px;background:var(--ok-bg);color:var(--ok);font-weight:600}

/* bulk bar */
.bulk{display:none;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 14px;margin-bottom:12px;border-radius:14px;
  background:var(--info-bg);border:1px solid var(--line)}
.bulk.show{display:flex}
.bulk b{color:var(--info);margin-right:4px}

/* table */
.tbl{overflow-x:auto;padding:0}
table{width:100%;border-collapse:collapse}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600;text-align:left;padding:12px 14px;
  border-bottom:1px solid var(--line);background:var(--surface2)}
td{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
td.chk,th.chk{width:44px;padding-right:0}
tr:last-child td{border-bottom:0}
tr:hover td{background:var(--surface2)}
tr.s-overdue td:first-child{box-shadow:inset 4px 0 0 var(--bad)}
tr.s-today td:first-child{box-shadow:inset 4px 0 0 var(--warn)}
tr.s-soon td:first-child{box-shadow:inset 4px 0 0 var(--info)}
.dev-name{font-weight:650}
.dev-meta{display:flex;gap:8px;align-items:center;margin-top:3px;flex-wrap:wrap}
.chip{font-size:11.5px;padding:1px 8px;border-radius:99px;background:var(--mute-bg);color:var(--muted);font-weight:600}
.chip.c-staff{background:var(--info-bg);color:var(--info)}
.chip.c-student{background:var(--stu-bg);color:var(--stu)}
.sub{font-size:12.5px;color:var(--muted);margin-top:3px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:650;padding:3px 10px;border-radius:99px;white-space:nowrap}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.p-ok{background:var(--ok-bg);color:var(--ok)}
.p-bad{background:var(--bad-bg);color:var(--bad)}
.p-warn{background:var(--warn-bg);color:var(--warn)}
.p-info{background:var(--info-bg);color:var(--info)}
.p-mute{background:var(--mute-bg);color:var(--muted)}
.p-out{background:var(--warn-bg);color:var(--warn)}
.empty{padding:34px;text-align:center;color:var(--muted)}
.act{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0}
.act input[name=borrower]{width:150px}
.fld{display:flex;flex-direction:column;font-size:11px;color:var(--muted);gap:1px;font-weight:600}
.fld input{padding:6px 9px}

.flash{background:var(--warn-bg);color:var(--warn);border:1px solid var(--line);padding:10px 14px;border-radius:12px;margin-bottom:14px;font-weight:600}
.back{display:inline-block;margin-bottom:14px;font-weight:600}
.dev-head h2{margin:0 0 6px;font-size:22px;letter-spacing:-.02em}
.dev-head .row{margin-top:10px}
.head-line{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.form-grid label{display:flex;flex-direction:column;gap:5px;font-size:12.5px;font-weight:600;color:var(--muted)}
.form-grid .wide{grid-column:1/-1}
.form-grid h3{margin:6px 0 0;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}

.demo{background:var(--info-bg);color:var(--info);border:1px solid var(--line);border-radius:12px;padding:9px 14px;margin-bottom:16px;font-size:13.5px;font-weight:600;text-align:center}
.sig{text-align:center;color:var(--muted);font-size:13px;padding:26px 0 34px;letter-spacing:.02em}
.sig b{color:var(--text)}

@media (max-width:760px){
  .stats{grid-template-columns:repeat(2,1fr)}
  .cats{grid-template-columns:1fr}
  .form-grid{grid-template-columns:1fr}
  .act input[name=borrower]{width:100%}
}
</style></head><body><main>
{% if DEMO %}<div class="demo">Live demo with sample data. Try adding, loaning, editing or deleting devices. Everything resets every hour.</div>{% endif %}
<div class="top">
  <a class="brand" href="{{ url_for('index') }}">
    <div class="logo">{{ I.laptop }}</div>
    <div><h1>Device Loans</h1><span>Know who has what, and when it's due back</span></div>
  </a>
  <div class="tools">
    <button type="button" class="btn ghost" onclick="toggleTheme()" title="Switch light / dark">{{ I.theme }} Theme</button>
    {% if not DEMO %}<form method="post" action="{{ url_for('test_email') }}"><button class="btn ghost" title="Send a test reminder email">{{ I.mail }} Test email</button></form>{% endif %}
    <a class="btn ghost" href="{{ url_for('export_csv') }}">{{ I.download }} Export</a>
  </div>
</div>
{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
{% block body %}{% endblock %}
</main>
<div class="sig">Created by <b>Touqeer</b></div>
<script>
function toggleTheme(){
  var r=document.documentElement;
  var cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  var n=cur==='dark'?'light':'dark';
  r.setAttribute('data-theme',n);
  try{localStorage.setItem('theme',n);}catch(e){}
}
</script>
</body></html>""",

    "index.html": """{% extends "base.html" %}
{% block title %}{% if alert_count %}({{ alert_count }}) {% endif %}Device Loans{% endblock %}
{% block body %}

<div class="stats">
  <a class="stat {{ 'on' if f=='all' }}" href="{{ url_for('index', filter='all', category=ca, q=qa) }}"><b>{{ stats.total }}</b><small>Total devices</small></a>
  <a class="stat {{ 'on' if f=='available' }}" href="{{ url_for('index', filter='available', category=ca, q=qa) }}"><b>{{ stats.available }}</b><small>Available</small></a>
  <a class="stat {{ 'on' if f=='out' }}" href="{{ url_for('index', filter='out', category=ca, q=qa) }}"><b>{{ stats.out }}</b><small>Loaned out</small></a>
  <a class="stat {{ 'bad' if stats.overdue }} {{ 'on' if f=='overdue' }}" href="{{ url_for('index', filter='overdue', category=ca, q=qa) }}"><b>{{ stats.overdue }}</b><small>Overdue</small></a>
</div>

<div class="cats">
  {% for c in cat_stats %}
  <a class="stat cat {{ 'on' if cat==c.key }}" href="{{ url_for('index', category=(None if cat==c.key else c.key), filter=fa, q=qa) }}"
     title="Click to filter by {{ c.label|lower }}">
    <small>{{ c.label }}s</small>
    <b>{{ c.available }} <span>available</span></b>
    <small>{{ c.out }} on loan &middot; {{ c.total }} total</small>
  </a>
  {% endfor %}
</div>

<div class="section">
{% if alerts %}
  <div class="alerts">
    <header class="{{ alert_cls }}">{{ I.alert }}
      <span>Needs attention:
        {% if stats.overdue %}{{ stats.overdue }} overdue{% endif %}{% if stats.overdue and stats.today %}, {% endif %}{% if stats.today %}{{ stats.today }} due today{% endif %}{% if (stats.overdue or stats.today) and stats.soon %}, {% endif %}{% if stats.soon %}{{ stats.soon }} due soon{% endif %}
      </span>
    </header>
    {% for a in alerts %}
    <div class="alert-row">
      <span class="pill p-{{ a.cls }}">{{ a.label }}</span>
      <div class="who"><b>{{ a.name }} <span class="chip c-{{ a.category }}">{{ cat_label[a.category] }}</span></b>
        <span class="m">With {{ a.borrower }} &middot; S/N {{ a.serial_number }} &middot; due {{ a.due_date }}</span></div>
      <form method="post" action="{{ url_for('return_device', device_id=a.id) }}" style="margin:0">
        <button class="btn ok" title="Mark as returned">{{ I.check }} Collected</button>
      </form>
    </div>
    {% endfor %}
  </div>
{% elif stats.out %}
  <div class="allclear">{{ I.check }} All clear. Nothing is due or overdue.</div>
{% endif %}
</div>

<h2 class="sec">Add a device</h2>
<div class="card">
  <form method="post" action="{{ url_for('add_device') }}" class="row">
    <input class="grow" name="serial_number" placeholder="Serial number" required>
    <select name="category" title="Category" required>
      {% for v, l in categories %}<option value="{{ v }}">{{ l }}</option>{% endfor %}
    </select>
    <input class="grow" name="device_type" list="types" placeholder="Type (Laptop, Tablet, iPad...)" required>
    <datalist id="types">
      <option>Laptop</option><option>Tablet</option><option>iPad</option>
      <option>iPhone</option><option>Android phone</option><option>Monitor</option>
      <option>Other</option>
    </datalist>
    <input class="grow" name="name" placeholder="Model / name" required>
    <input class="grow" name="owner" placeholder="Owner (optional)">
    <input class="grow" name="notes" placeholder="Notes (optional)">
    <button>{{ I.plus }} Add device</button>
  </form>
</div>

<h2 class="sec">Devices</h2>
<form method="get" class="row" style="margin-bottom:12px">
  <input type="hidden" name="filter" value="{{ f }}">
  <select name="category" onchange="this.form.submit()" title="Filter by category">
    <option value="all">All categories</option>
    {% for v, l in categories %}<option value="{{ v }}" {{ 'selected' if cat==v }}>{{ l }}</option>{% endfor %}
  </select>
  <input class="grow" name="q" value="{{ q }}" placeholder="Search by serial, type, model, owner or borrower" style="flex:1">
  <button>{{ I.search }} Search</button>
</form>

<form id="bulkform" method="post" action="{{ url_for('bulk_devices') }}"></form>
<div class="bulk" id="bulkbar">
  <b><span id="selCount">0</span> selected</b>
  <select name="category" form="bulkform">
    <option value="">Category: no change</option>
    {% for v, l in categories %}<option value="{{ v }}">{{ l }}</option>{% endfor %}
  </select>
  <input name="device_type" form="bulkform" list="types" placeholder="Type: no change">
  <input name="owner" form="bulkform" placeholder="Owner: no change">
  <button name="action" value="update" form="bulkform">Apply changes</button>
  <button class="btn danger" name="action" value="delete" form="bulkform" onclick="return confirmDelete()">{{ I.trash }} Delete selected</button>
</div>

<div class="card tbl">
<table>
<tr>
  <th class="chk"><input type="checkbox" id="selAll" title="Select all shown"></th>
  <th>Device</th><th>Status</th><th>Due back</th><th>Actions</th>
</tr>
{% for d in devices %}
<tr class="s-{{ d.state }}">
  <td class="chk"><input type="checkbox" class="rowchk" name="ids" value="{{ d.id }}" form="bulkform" aria-label="Select {{ d.name }}"></td>
  <td>
    <div class="dev-name">{{ d.name }}</div>
    <div class="dev-meta">
      <span class="chip c-{{ d.category }}">{{ cat_label[d.category] }}</span>
      <span class="chip">{{ d.device_type or 'Device' }}</span>
      <code>{{ d.serial_number }}</code>
    </div>
    {% if d.owner %}<div class="sub">Owner: {{ d.owner }}</div>{% endif %}
  </td>
  <td>
    {% if d.loan_id %}<span class="pill p-out">With {{ d.borrower }}</span>
      <div class="sub">since {{ d.loaned_at }}</div>
    {% else %}<span class="pill p-ok">Available</span>{% endif %}
  </td>
  <td>
    {% if d.loan_id and d.due_date %}<span class="pill p-{{ d.cls }}">{{ d.label }}</span><div class="sub">{{ d.due_date }}</div>
    {% elif d.loan_id %}<span class="sub">No due date</span>{% endif %}
  </td>
  <td>
    {% if d.loan_id %}
    <form method="post" action="{{ url_for('return_device', device_id=d.id) }}" class="act">
      <button class="btn ok">{{ I.check }} Mark returned</button>
      <a class="icon-btn" href="{{ url_for('device', device_id=d.id) }}" title="Loan history" aria-label="Loan history">{{ I.history }}</a>
      <a class="icon-btn neutral" href="{{ url_for('edit_device', device_id=d.id) }}" title="Edit device" aria-label="Edit device">{{ I.edit }}</a>
    </form>
    {% else %}
    <form method="post" action="{{ url_for('loan_device', device_id=d.id) }}" class="act">
      <input name="borrower" placeholder="Borrower name" required>
      <label class="fld">Due back (optional)<input type="date" name="due_date" min="{{ today }}"></label>
      <button>Loan out</button>
      <a class="icon-btn" href="{{ url_for('device', device_id=d.id) }}" title="Loan history" aria-label="Loan history">{{ I.history }}</a>
      <a class="icon-btn neutral" href="{{ url_for('edit_device', device_id=d.id) }}" title="Edit device" aria-label="Edit device">{{ I.edit }}</a>
    </form>
    {% endif %}
  </td>
</tr>
{% else %}
<tr><td colspan="5" class="empty">Nothing here. Add a device above, or change the filters.</td></tr>
{% endfor %}
</table>
</div>

<script>
(function(){
  var all=document.getElementById('selAll'),
      boxes=[].slice.call(document.querySelectorAll('.rowchk')),
      bar=document.getElementById('bulkbar'),
      cnt=document.getElementById('selCount');
  function upd(){
    var n=boxes.filter(function(b){return b.checked;}).length;
    cnt.textContent=n;
    bar.classList.toggle('show', n>0);
    if(all){all.checked=(n>0&&n===boxes.length);all.indeterminate=(n>0&&n<boxes.length);}
  }
  boxes.forEach(function(b){b.addEventListener('change',upd);});
  if(all){all.addEventListener('change',function(){boxes.forEach(function(b){b.checked=all.checked;});upd();});}
  upd();
})();
function confirmDelete(){
  var n=document.getElementById('selCount').textContent;
  return confirm('Delete '+n+' selected device(s) and their loan history? This cannot be undone.');
}
// keep alerts fresh: reload every 5 minutes unless you're typing or have devices selected
setInterval(function(){
  if(!document.querySelector('input:focus, select:focus, .rowchk:checked')) location.reload();
}, 300000);
</script>
{% endblock %}""",

    "device.html": """{% extends "base.html" %}
{% block title %}{{ d.name }} - Device Loans{% endblock %}
{% block body %}
<a class="back" href="{{ url_for('index') }}">&larr; Back to devices</a>

<div class="card dev-head">
  <div class="head-line">
    <div>
      <h2>{{ d.name }}</h2>
      <div class="dev-meta">
        <span class="chip c-{{ d.category }}">{{ cat_label[d.category] }}</span>
        <span class="chip">{{ d.device_type or 'Device' }}</span>
        <code>S/N {{ d.serial_number }}</code>
      </div>
    </div>
    <a class="btn ghost" href="{{ url_for('edit_device', device_id=d.id) }}">{{ I.edit }} Edit device</a>
  </div>
  <div class="sub">
    {% if d.owner %}Owner: {{ d.owner }}{% endif %}{% if d.owner and d.date_added %} &middot; {% endif %}{% if d.date_added %}Added {{ d.date_added }}{% endif %}
  </div>
  {% if d.notes %}<div class="sub">{{ d.notes }}</div>{% endif %}
  <div class="row">
    {% if current %}
      <span class="pill p-out">With {{ current.borrower }} since {{ current.loaned_at }}</span>
      {% if current.due_date %}<span class="pill p-{{ current.cls }}">{{ current.label }} ({{ current.due_date }})</span>{% endif %}
    {% else %}<span class="pill p-ok">Available</span>{% endif %}
  </div>
</div>

<h2 class="sec">Loan history ({{ loans|length }})</h2>
<div class="card tbl">
<table>
<tr><th>Borrower</th><th>Loaned</th><th>Due back</th><th>Returned</th><th>Result</th></tr>
{% for l in loans %}
<tr>
  <td><b>{{ l.borrower }}</b></td>
  <td>{{ l.loaned_at }}</td>
  <td>{{ l.due_date or "—" }}</td>
  <td>{{ l.returned_at or "—" }}</td>
  <td>
    {% if not l.returned_at %}<span class="pill p-out">Still out</span>
    {% elif l.due_date and l.returned_at[:10] > l.due_date %}<span class="pill p-bad">Returned late</span>
    {% else %}<span class="pill p-ok">Returned</span>{% endif %}
  </td>
</tr>
{% else %}
<tr><td colspan="5" class="empty">This device hasn't been loaned yet.</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}""",

    "edit.html": """{% extends "base.html" %}
{% block title %}Edit {{ d.name }} - Device Loans{% endblock %}
{% block body %}
<a class="back" href="{{ url_for('index') }}">&larr; Back to devices</a>

<div class="card">
  <h2 style="margin:0 0 14px;font-size:22px;letter-spacing:-.02em">Edit device</h2>
  <form method="post" class="form-grid">
    <label>Serial number<input name="serial_number" value="{{ d.serial_number }}" required></label>
    <label>Model / name<input name="name" value="{{ d.name }}" required></label>
    <label>Category
      <select name="category">
        {% for v, l in categories %}<option value="{{ v }}" {{ 'selected' if d.category==v }}>{{ l }}</option>{% endfor %}
      </select>
    </label>
    <label>Device type
      <input name="device_type" list="types" value="{{ d.device_type or '' }}" placeholder="Laptop, Tablet, iPad...">
      <datalist id="types">
        <option>Laptop</option><option>Tablet</option><option>iPad</option>
        <option>iPhone</option><option>Android phone</option><option>Monitor</option><option>Other</option>
      </datalist>
    </label>
    <label>Owner<input name="owner" value="{{ d.owner or '' }}" placeholder="Optional"></label>
    <label>Date added<input type="date" name="date_added" value="{{ d.date_added or '' }}"></label>
    <label class="wide">Notes<input name="notes" value="{{ d.notes or '' }}" placeholder="Optional"></label>

    {% if current %}
    <h3 class="wide">Current loan</h3>
    <label>Borrower<input name="borrower" value="{{ current.borrower }}" required></label>
    <label>Due back (optional, clear to remove)<input type="date" name="due_date" value="{{ current.due_date or '' }}"></label>
    {% endif %}

    <div class="wide row">
      <button>Save changes</button>
      <a class="btn ghost" href="{{ url_for('index') }}">Cancel</a>
    </div>
  </form>
</div>

<form method="post" action="{{ url_for('delete_device', device_id=d.id) }}" style="margin-top:18px"
      onsubmit="return confirm('Delete this device and its entire history?')">
  <button class="btn danger">{{ I.trash }} Delete this device</button>
</form>
{% endblock %}""",
}
app.jinja_loader = DictLoader(TEMPLATES)
app.jinja_env.globals["I"] = ICONS
app.jinja_env.globals["categories"] = CATEGORIES
app.jinja_env.globals["cat_label"] = CAT_LABEL
app.jinja_env.globals["DEMO"] = DEMO


# ---------- database helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _add_column(conn, table, column, ddl):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    """Create tables; upgrade an older loans.db without losing data."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        _add_column(conn, "devices", "device_type", "TEXT DEFAULT ''")
        _add_column(conn, "devices", "category", "TEXT DEFAULT 'other'")
        _add_column(conn, "devices", "owner", "TEXT DEFAULT ''")
        _add_column(conn, "devices", "date_added", "TEXT")
        _add_column(conn, "loans", "due_date", "TEXT")
        _add_column(conn, "loans", "reminder_sent", "INTEGER DEFAULT 0")
        conn.execute("UPDATE devices SET category = 'other' WHERE category IS NULL OR category = ''")


def now_str():
    """Loan-out and return times always come from the system clock."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def parse_date(value):
    value = (value or "").strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def clean_category(value):
    value = (value or "").strip().lower()
    return value if value in CAT_LABEL else "other"


def back():
    """Redirect to the page the form was submitted from (keeps filters), else home."""
    ref = request.referrer
    if ref and ref.startswith(request.host_url):
        return redirect(ref)
    return redirect(url_for("index"))


def due_state(due, on_loan):
    """Work out the alert state, label, colour class and sort rank for a loan."""
    if not on_loan:
        return "available", "Available", "ok", 5
    if not due:
        return "nodue", "No due date", "mute", 4
    days = (date.fromisoformat(due) - date.today()).days
    if days < 0:
        n = -days
        return "overdue", f"{n} day{'s' if n != 1 else ''} overdue", "bad", 0
    if days == 0:
        return "today", "Due today", "warn", 1
    if days == 1:
        return "soon", "Due tomorrow", "info", 2
    if days <= SOON_DAYS:
        return "soon", f"Due in {days} days", "info", 2
    return "ok", f"Due in {days} days", "ok", 3


def decorate(row):
    d = dict(row)
    d["category"] = clean_category(d.get("category"))
    d["state"], d["label"], d["cls"], d["rank"] = due_state(d.get("due_date"), bool(d.get("loan_id")))
    return d


def open_loan(db, device_id):
    return db.execute("SELECT * FROM loans WHERE device_id = ? AND returned_at IS NULL",
                      (device_id,)).fetchone()


# ---------- demo mode ----------
# (serial, category, type, name, owner)
DEMO_DEVICES = [
    ("STF-1001", "staff", "Laptop", "Dell Latitude 5440", "IT Department"),
    ("STF-1002", "staff", "Laptop", "Lenovo ThinkPad T14", "IT Department"),
    ("STF-1003", "staff", "Laptop", "HP EliteBook 840", "IT Department"),
    ("STF-1004", "staff", "Tablet", "Samsung Galaxy Tab S9", "Front Office"),
    ("STF-1005", "staff", "iPad", "iPad Air 11-inch", "Front Office"),
    ("STF-1006", "staff", "Laptop", "MacBook Air M2", "IT Department"),
    ("STU-2001", "student", "Chromebook", "Acer Chromebook 314", "Library"),
    ("STU-2002", "student", "Chromebook", "Acer Chromebook 314", "Library"),
    ("STU-2003", "student", "Tablet", "Lenovo Tab M10", "Library"),
    ("STU-2004", "student", "iPad", "iPad 10th Gen", "Library"),
    ("STU-2005", "student", "Laptop", "HP ProBook 450", "Science Dept"),
    ("STU-2006", "student", "iPad", "iPad 9th Gen", "Library"),
    ("STU-2007", "student", "Chromebook", "Dell Chromebook 3100", "Library"),
    ("OTH-3001", "other", "Monitor", "Dell 27-inch Monitor", "Spare stock"),
    ("OTH-3002", "other", "Android phone", "Google Pixel 8", "Spare stock"),
]
# (serial, borrower, loaned N days ago/ahead, due offset or None, returned offset or None)
DEMO_LOANS = [
    ("STF-1002", "Sarah Khan", -10, -3, None),        # overdue
    ("STF-1004", "James Miller", -5, 0, None),        # due today
    ("STF-1006", "Priya Patel", -2, 1, None),         # due tomorrow
    ("STU-2002", "Class 10B", -4, 3, None),
    ("STU-2004", "Ahmed Ali", -1, None, None),        # no due date
    ("STU-2006", "Emma Brown", -7, 5, None),
    ("STF-1001", "Daniel Lee", -40, -33, -34),        # returned on time
    ("STF-1001", "Maria Garcia", -20, -14, -11),      # returned late
    ("STU-2001", "Noah Wilson", -15, -10, -10),
]


def seed_demo():
    """Wipe everything and load the sample data (demo mode only)."""
    def day(n):
        return (date.today() + timedelta(days=n)).strftime("%Y-%m-%d")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM loans")
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('devices', 'loans')")
        ids = {}
        for serial, cat, typ, name, owner in DEMO_DEVICES:
            cur = conn.execute(
                """INSERT INTO devices (serial_number, name, device_type, category, owner, date_added, notes)
                   VALUES (?,?,?,?,?,?,'')""", (serial, name, typ, cat, owner, day(-90)))
            ids[serial] = cur.lastrowid
        for serial, borrower, loaned, due, returned in DEMO_LOANS:
            conn.execute(
                """INSERT INTO loans (device_id, borrower, loaned_at, due_date, returned_at)
                   VALUES (?,?,?,?,?)""",
                (ids[serial], borrower, f"{day(loaned)} 10:30",
                 day(due) if due is not None else None,
                 f"{day(returned)} 16:05" if returned is not None else None))


def demo_reset_loop():
    while True:
        time.sleep(DEMO_RESET_MIN * 60)
        try:
            seed_demo()
        except Exception as e:  # noqa: BLE001
            print(f"[demo] reset failed: {e}")


# ---------- email reminders (optional) ----------
def send_email(subject, body):
    """Returns (ok, message)."""
    if not (SMTP_USER and SMTP_PASS and MAIL_TO):
        return False, "Email isn't set up. Fill in SMTP_USER, SMTP_PASS and MAIL_TO at the top of app.py (optional)."
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.set_content(body)
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        return True, f"Email sent to {MAIL_TO}."
    except Exception as e:  # noqa: BLE001
        return False, f"Email failed: {e}"


def check_reminders():
    """Email once per loan when its due date arrives (or has passed) and it is still out."""
    if not SMTP_USER:
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT l.id, l.borrower, l.loaned_at, l.due_date,
                      d.serial_number, d.name, d.device_type
               FROM loans l JOIN devices d ON d.id = l.device_id
               WHERE l.returned_at IS NULL
                 AND l.due_date IS NOT NULL AND l.due_date != ''
                 AND COALESCE(l.reminder_sent, 0) = 0
                 AND (l.due_date < ? OR (l.due_date = ? AND ? >= ?))
               ORDER BY l.due_date""",
            (today, today, now.hour, REMIND_HOUR)).fetchall()
        if not rows:
            return
        lines = []
        for r in rows:
            kind = f"{r['device_type']} " if r["device_type"] else ""
            lines.append(f"- {kind}{r['name']} (S/N {r['serial_number']}) loaned to "
                         f"{r['borrower']} on {r['loaned_at']}, due back {r['due_date']}")
        body = "These loans have reached their return date. Please collect the device(s) back:\n\n" \
               + "\n".join(lines)
        ok, info = send_email(f"Loan reminder: {len(rows)} device(s) due for return", body)
        if ok:
            ids = [r["id"] for r in rows]
            conn.execute(f"UPDATE loans SET reminder_sent = 1 WHERE id IN ({','.join('?' * len(ids))})", ids)
            conn.commit()
        print(f"[reminders] {info}")
    finally:
        conn.close()


def reminder_loop():
    while True:
        try:
            check_reminders()
        except Exception as e:  # noqa: BLE001
            print(f"[reminders] error: {e}")
        time.sleep(CHECK_EVERY_MIN * 60)


# ---------- routes ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    f = request.args.get("filter", "all")
    if f not in ("all", "available", "out", "overdue"):
        f = "all"
    cat = request.args.get("category", "all")
    if cat not in CAT_LABEL:
        cat = "all"

    rows = get_db().execute(
        """SELECT d.*, l.id AS loan_id, l.borrower, l.loaned_at, l.due_date
           FROM devices d
           LEFT JOIN loans l ON l.device_id = d.id AND l.returned_at IS NULL""").fetchall()
    items = [decorate(r) for r in rows]

    stats = {
        "total": len(items),
        "available": sum(1 for i in items if i["state"] == "available"),
        "out": sum(1 for i in items if i["loan_id"]),
        "overdue": sum(1 for i in items if i["state"] == "overdue"),
        "today": sum(1 for i in items if i["state"] == "today"),
        "soon": sum(1 for i in items if i["state"] == "soon"),
    }
    cat_stats = []
    for key, label in CATEGORIES:
        in_cat = [i for i in items if i["category"] == key]
        cat_stats.append({
            "key": key, "label": label, "total": len(in_cat),
            "available": sum(1 for i in in_cat if i["state"] == "available"),
            "out": sum(1 for i in in_cat if i["loan_id"]),
        })
    alerts = sorted((i for i in items if i["state"] in ("overdue", "today", "soon")),
                    key=lambda i: (i["rank"], i["due_date"], i["name"].lower()))
    alert_cls = "bad" if stats["overdue"] else ("warn" if stats["today"] else "info")
    alert_count = stats["overdue"] + stats["today"]

    shown = items
    if cat != "all":
        shown = [i for i in shown if i["category"] == cat]
    if f == "available":
        shown = [i for i in shown if i["state"] == "available"]
    elif f == "out":
        shown = [i for i in shown if i["loan_id"]]
    elif f == "overdue":
        shown = [i for i in shown if i["state"] == "overdue"]
    if q:
        ql = q.lower()
        shown = [i for i in shown if ql in " ".join(
            str(i.get(k) or "") for k in ("serial_number", "name", "device_type", "owner", "borrower")).lower()]
    shown.sort(key=lambda i: (i["rank"], i["due_date"] or "9999", (i["device_type"] or "").lower(),
                              i["name"].lower()))

    return render_template("index.html", devices=shown, q=q, f=f, cat=cat, stats=stats,
                           cat_stats=cat_stats, alerts=alerts, alert_cls=alert_cls,
                           alert_count=alert_count, today=today_str(),
                           qa=q or None, ca=None if cat == "all" else cat,
                           fa=None if f == "all" else f)


@app.post("/devices")
def add_device():
    serial = request.form["serial_number"].strip()
    name = request.form["name"].strip()
    dtype = request.form.get("device_type", "").strip()
    category = clean_category(request.form.get("category"))
    owner = request.form.get("owner", "").strip()
    notes = request.form.get("notes", "").strip()
    try:
        with get_db() as db:
            db.execute("""INSERT INTO devices (serial_number, name, device_type, category, owner, date_added, notes)
                          VALUES (?,?,?,?,?,?,?)""",
                       (serial, name, dtype, category, owner, today_str(), notes))
    except sqlite3.IntegrityError:
        flash(f"Serial number {serial} already exists.")
    return back()


@app.get("/devices/<int:device_id>")
def device(device_id):
    db = get_db()
    d = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if d is None:
        abort(404)
    d = dict(d)
    d["category"] = clean_category(d.get("category"))
    loans = db.execute(
        "SELECT * FROM loans WHERE device_id = ? ORDER BY loaned_at DESC, id DESC",
        (device_id,)).fetchall()
    current = None
    if loans and not loans[0]["returned_at"]:
        current = dict(loans[0])
        current["state"], current["label"], current["cls"], _ = due_state(current["due_date"], True)
    return render_template("device.html", d=d, loans=loans, current=current)


@app.route("/devices/<int:device_id>/edit", methods=["GET", "POST"])
def edit_device(device_id):
    db = get_db()
    d = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if d is None:
        abort(404)
    loan = open_loan(db, device_id)

    if request.method == "POST":
        serial = request.form["serial_number"].strip()
        name = request.form["name"].strip()
        try:
            with db:
                db.execute("""UPDATE devices SET serial_number = ?, name = ?, device_type = ?, category = ?,
                                                 owner = ?, date_added = ?, notes = ? WHERE id = ?""",
                           (serial, name, request.form.get("device_type", "").strip(),
                            clean_category(request.form.get("category")),
                            request.form.get("owner", "").strip(),
                            parse_date(request.form.get("date_added")),
                            request.form.get("notes", "").strip(), device_id))
                if loan is not None and "borrower" in request.form:
                    new_due = parse_date(request.form.get("due_date"))
                    reset = 0 if new_due != loan["due_date"] else loan["reminder_sent"]
                    db.execute("UPDATE loans SET borrower = ?, due_date = ?, reminder_sent = ? WHERE id = ?",
                               (request.form["borrower"].strip() or loan["borrower"], new_due, reset, loan["id"]))
        except sqlite3.IntegrityError:
            flash(f"Serial number {serial} is already used by another device.")
            return redirect(url_for("edit_device", device_id=device_id))
        flash("Changes saved.")
        return redirect(url_for("index"))

    d = dict(d)
    d["category"] = clean_category(d.get("category"))
    return render_template("edit.html", d=d, current=loan)


@app.post("/devices/bulk")
def bulk_devices():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    action = request.form.get("action")
    if not ids:
        flash("Select at least one device first.")
        return back()
    marks = ",".join("?" * len(ids))
    with get_db() as db:
        if action == "delete":
            db.execute(f"DELETE FROM devices WHERE id IN ({marks})", ids)
            flash(f"Deleted {len(ids)} device(s).")
        elif action == "update":
            sets, vals = [], []
            cat = request.form.get("category", "").strip()
            if cat in CAT_LABEL:
                sets.append("category = ?")
                vals.append(cat)
            dtype = request.form.get("device_type", "").strip()
            if dtype:
                sets.append("device_type = ?")
                vals.append(dtype)
            owner = request.form.get("owner", "").strip()
            if owner:
                sets.append("owner = ?")
                vals.append(owner)
            if not sets:
                flash("Choose a category, type or owner to apply first.")
            else:
                db.execute(f"UPDATE devices SET {', '.join(sets)} WHERE id IN ({marks})", vals + ids)
                flash(f"Updated {len(ids)} device(s).")
    return back()


@app.post("/devices/<int:device_id>/loan")
def loan_device(device_id):
    borrower = request.form["borrower"].strip()
    due = parse_date(request.form.get("due_date"))   # optional
    try:
        with get_db() as db:
            db.execute("INSERT INTO loans (device_id, borrower, loaned_at, due_date) VALUES (?,?,?,?)",
                       (device_id, borrower, now_str(), due))
    except sqlite3.IntegrityError:
        flash("That device is already loaned out.")
    return back()


@app.post("/devices/<int:device_id>/return")
def return_device(device_id):
    with get_db() as db:
        db.execute("UPDATE loans SET returned_at = ? WHERE device_id = ? AND returned_at IS NULL",
                   (now_str(), device_id))
    return back()


@app.post("/devices/<int:device_id>/delete")
def delete_device(device_id):
    with get_db() as db:
        db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return redirect(url_for("index"))


@app.post("/test-email")
def test_email():
    ok, info = send_email("Device Loans: test email",
                          "Email reminders are working. You will be emailed when a loan reaches its due date.")
    flash(info)
    return back()


@app.get("/export.csv")
def export_csv():
    rows = get_db().execute(
        """SELECT d.serial_number, d.category, d.device_type, d.name, d.owner, l.borrower,
                  l.loaned_at, l.due_date, l.returned_at
           FROM loans l JOIN devices d ON d.id = l.device_id
           ORDER BY l.loaned_at DESC""").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["serial_number", "category", "type", "device", "owner", "borrower",
                "loaned_at", "due_date", "returned_at"])
    w.writerows([tuple(r) for r in rows])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=loan_history.csv"})


def free_port(start=5000):
    """First port from `start` that nothing is listening on."""
    for port in range(start, start + 30):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


init_db()   # runs on import too, so hosts that start the app with gunicorn also get the database
if DEMO:
    seed_demo()
    threading.Thread(target=demo_reset_loop, daemon=True).start()


if __name__ == "__main__":
    if not DEMO:
        threading.Thread(target=reminder_loop, daemon=True).start()
    if FROZEN:
        # Installed copy: only this PC can reach it, and the browser opens by itself.
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        print(f"Device Loans is running at {url}")
        print(f"Your data is stored in: {BASE_DIR}")
        print("Keep this window open while you use the app. Close it to quit.")
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        app.run(host="127.0.0.1", port=port)
    else:
        # host 0.0.0.0 makes it reachable from other devices on your LAN.
        # Use host="127.0.0.1" if you only want it on this machine.
        app.run(host="0.0.0.0", port=5000)
