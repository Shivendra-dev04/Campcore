# Campcore

A beginner-friendly college bus information platform built with **Python, Flask, SQLite, HTML and CSS**.

## What is included

- Student registration and login
- Role-based dashboards for students, contractors and admins
- Admin-created contractor accounts
- Admin bus registration and contractor assignment
- Contractor dashboard showing only assigned buses
- Quick destination, parking and departure selections
- Publish-once workflow for student bus updates
- Student search by bus number and destination filter
- Password hashing and backend role/assignment checks

## Run locally

### 1. Open this folder in VS Code

Open the `campcore` folder (the one containing `app.py`) in VS Code.

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once in that terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
py -m pip install -r requirements.txt
```

### 4. Create the first admin account

```powershell
flask --app app create-admin
```

Follow the prompts. Use a strong password and remember it.

### 5. Start Campcore

```powershell
flask --app app run --debug
```

Open the local address printed in the terminal (usually `http://127.0.0.1:5000`).

## First-time setup flow

1. Log in with the admin account.
2. Create a contractor account from the admin dashboard.
3. Register a bus and assign it to that contractor.
4. Create a student account from the registration page.
5. Log in as the contractor in a separate browser/private window and publish a bus update.
6. Log in as the student to see the update.

## Important notes

- The database (`campcore.db`) is created automatically in this folder the first time the app runs.
- Contractor accounts cannot self-register. An admin creates them.
- Students can only view updates. Contractors can publish only for buses assigned to them.
- The sample destination and parking options are seeded in `app.py` inside `init_db()`. Change them to match your college.
- This is a hackathon MVP/prototype. Before public deployment, set a strong `SECRET_KEY`, turn off debug mode, add CSRF protection and rate limiting, use HTTPS, and choose a production-ready database/backup strategy.
- Bus updates are retained as history in the database, while the latest active update is shown on the student dashboard. For a real deployment, agree on expiry rules with the college/contractors and add an admin review screen.

## Suggested GitHub description

Campcore is a college bus information platform that helps students check the latest bus destination, parking location and departure time. Contractors publish updates through a simple dashboard, while admins manage contractor accounts, buses and assignments.
