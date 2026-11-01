import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import uuid

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import load_workbook
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "campcore.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-before-deployment"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ---------------- LOST & FOUND PHOTO UPLOADS ----------------

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(
    BASE_DIR, "static", "uploads", "lost_found"
)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# ---------------- LOST & FOUND HELPERS ----------------

def allowed_image(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def valid_image_content(file):
    header = file.read(12)
    file.seek(0)

    is_jpeg = header.startswith(b"\xff\xd8\xff")
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = (
        header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    )

    return is_jpeg or is_png or is_webp

# ---------------- DATABASE CONNECTION ----------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------- BUS EXPIRY ----------------

def expire_old_bus_updates():
    # A bus update expires 2 minutes after its departure time.
    cutoff = (
        datetime.now() - timedelta(minutes=2)
    ).isoformat(timespec="seconds")

    with get_db() as db:
        db.execute("""
            UPDATE bus_updates
            SET active = 0
            WHERE active = 1
            AND departure_at <= ?
        """, (cutoff,))


# ---------------- DATABASE INITIALIZATION ----------------

def init_db():

    with get_db() as db:

        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK(role IN ('student','contractor','admin')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS buses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_number TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contractor_id INTEGER NOT NULL REFERENCES users(id),
            bus_id INTEGER NOT NULL REFERENCES buses(id),
            UNIQUE(contractor_id, bus_id)
        );

        CREATE TABLE IF NOT EXISTS bus_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id INTEGER NOT NULL REFERENCES buses(id),
            destination TEXT NOT NULL,
            parking TEXT NOT NULL,
            departure_at TEXT NOT NULL,
            updated_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
                CREATE TABLE IF NOT EXISTS lost_found (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            bus_number TEXT NOT NULL,
            date_found TEXT NOT NULL,
            image_filename TEXT,
            reported_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unclaimed'
                CHECK(status IN ('unclaimed', 'claimed'))
        );
                -- CLASSROOM TRACKER
        CREATE TABLE IF NOT EXISTS classroom_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block TEXT NOT NULL DEFAULT 'Block 1',
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            classroom TEXT NOT NULL,
            subject TEXT NOT NULL,
            faculty TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
           # Settings: profile and contact information
        user_columns = [
            row["name"]
            for row in db.execute("PRAGMA table_info(users)").fetchall()
        ]

        if "phone" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN phone TEXT")

        if "location" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN location TEXT")
                    # Add collection location to Lost & Found reports
        lost_found_columns = [
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(lost_found)"
            ).fetchall()
        ]

        if "collection_location" not in lost_found_columns:
            db.execute("""
                ALTER TABLE lost_found
                ADD COLUMN collection_location TEXT
            """)
        # Rebuild options table so the same location can exist
        # separately as a destination and as a parking location.

        db.execute("""
            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                label TEXT NOT NULL UNIQUE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS options_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                UNIQUE(kind, label)
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO options_new(kind, label)
            SELECT kind, label FROM options
        """)

        db.execute("DROP TABLE options")
        db.execute("ALTER TABLE options_new RENAME TO options")

        # Remove old default options.
        # Custom locations entered by contractors are preserved.

        db.execute("""
            DELETE FROM options
            WHERE kind = 'destination'
            AND label = 'Zirakpur'
        """)

        db.execute("""
            DELETE FROM options
            WHERE kind = 'parking'
            AND label IN (
                'Main Gate',
                'Parking Area A',
                'Parking Area B',
                'Hostel Gate'
            )
        """)
        # New default destinations and parking locations.

        default_options = {
            "destination": [
                "Landran hostel",
                "City hostel 1",
                "City hostel 2",
                "Chandigarh",
                "Mohali",
                "Kharar",
                "Other"
            ],

            "parking": [
                "Block 3 backside",
                "Block 7 parking",
                "Bus parking",
                "Other"
            ]
        }

        for kind, labels in default_options.items():
            for label in labels:
                db.execute("""
                    INSERT OR IGNORE INTO options(kind, label)
                    VALUES(?, ?)
                """, (kind, label))


# ---------------- USER HELPERS ----------------

def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE id=? AND active=1",
            (user_id,)
        ).fetchone()

    if not user:
        session.clear()

    return user


@app.context_processor
def inject_user():
    return {"current_user": current_user()}

def login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))

        return view(*args, **kwargs)

    return wrapped

def role_required(*roles):

    def decorator(view):

        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):

            user = current_user()

            if user["role"] not in roles:
                abort(403)

            return view(*args, **kwargs)

        return wrapped

    return decorator


def dashboard_for(role):

    return {
        "student": "student_dashboard",
        "contractor": "contractor_dashboard",
        "admin": "admin_dashboard"
    }[role]


# ---------------- DEPARTURE TIME HELPERS ----------------

def departure_label(value):

    try:
        dt = datetime.fromisoformat(value)
        now = datetime.now()

        if dt <= now:
            return "Departed"

        minutes = int(
            (dt - now).total_seconds() // 60
        )

        if minutes <= 1:
            return "Leaving now"

        return f"In {minutes} min"

    except (ValueError, TypeError):
        return "Time not set"


@app.template_filter("departure")
def departure_filter(value):
    return departure_label(value)


@app.template_filter("clock")
def clock_filter(value):

    try:
        return datetime.fromisoformat(value).strftime("%I:%M %p")

    except (ValueError, TypeError):
        return value


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():

    if current_user():
        return redirect(url_for(dashboard_for(current_user()["role"])))

    # Remove expired bus updates
    expire_old_bus_updates()

    with get_db() as db:

        buses = db.execute("""
            SELECT
                b.bus_number,
                u.destination,
                u.parking,
                u.departure_at,
                u.created_at

            FROM buses b

            JOIN bus_updates u
                ON u.bus_id = b.id

            WHERE b.active = 1
            AND u.active = 1

            AND u.id = (
                SELECT MAX(u2.id)
                FROM bus_updates u2
                WHERE u2.bus_id = b.id
                AND u2.active = 1
            )

            ORDER BY u.created_at DESC
        """).fetchall()

    return render_template(
        "home.html",
        buses=buses,
        active_bus_count=len(buses)
    )


# ---------------- STUDENT REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 8:

            flash(
                "Enter your name, a valid email, and a password of at least 8 characters.",
                "danger"
            )

            return render_template("register.html")

        try:

            with get_db() as db:

                db.execute("""
                    INSERT INTO users(
                        name, email, password_hash, role, created_at
                    )
                    VALUES(?,?,?,?,?)
                """, (
                    name,
                    email,
                    generate_password_hash(password),
                    "student",
                    datetime.now().isoformat(timespec="seconds")
                ))

            flash(
                "Account created. You can now log in.",
                "success"
            )

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash(
                "That email is already registered.",
                "danger"
            )

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():

    # Remember the page the user wanted before login
    next_page = request.args.get("next")

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        next_page = request.form.get("next") or next_page

        with get_db() as db:
            user = db.execute("""
                SELECT * FROM users
                WHERE email=? AND active=1
            """, (email,)).fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):

            session.clear()
            session["user_id"] = user["id"]

            # Return to the requested page after login
            if next_page and next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)

            return redirect(
                url_for(dashboard_for(user["role"]))
            )

        flash(
            "Email or password is incorrect.",
            "danger"
        )

    return render_template(
        "login.html",
        next=next_page
    )
# ---------------- SETTINGS ----------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():

    user = current_user()

    if request.method == "POST":

        action = request.form.get("action")

        if action == "profile":

            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            location = request.form.get("location", "").strip()

            if not name:
                flash("Username cannot be empty.", "danger")
                return redirect(url_for("settings"))

            if len(phone) > 20 or len(location) > 100:
                flash("Please check your phone number or location.", "danger")
                return redirect(url_for("settings"))

            with get_db() as db:
                db.execute("""
                    UPDATE users
                    SET name=?, phone=?, location=?
                    WHERE id=?
                """, (name, phone, location, user["id"]))

            flash("Profile updated successfully.", "success")
            return redirect(url_for("settings"))

        elif action == "password":

            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not check_password_hash(
                user["password_hash"], current_password
            ):
                flash("Your current password is incorrect.", "danger")

            elif len(new_password) < 8:
                flash("New password must contain at least 8 characters.", "danger")

            elif new_password != confirm_password:
                flash("New passwords do not match.", "danger")

            else:
                with get_db() as db:
                    db.execute("""
                        UPDATE users
                        SET password_hash=?
                        WHERE id=?
                    """, (
                        generate_password_hash(new_password),
                        user["id"]
                    ))

                flash("Password changed successfully.", "success")

            return redirect(url_for("settings"))

    with get_db() as db:

        contractors = db.execute("""
            SELECT name, phone
            FROM users
            WHERE role='contractor'
            AND active=1
            ORDER BY name
        """).fetchall()

    return render_template(
        "settings.html",
        user=user,
        contractors=contractors
    )
# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("home"))


# ---------------- STUDENT DASHBOARD ----------------

@app.route("/student")
@role_required("student")
def student_dashboard():

    expire_old_bus_updates()

    search = request.args.get("q", "").strip()
    destination = request.args.get("destination", "").strip()

    with get_db() as db:

        sql = """
            SELECT
                b.bus_number,
                u.destination,
                u.parking,
                u.departure_at,
                u.created_at,
                p.name AS publisher

            FROM buses b

            JOIN bus_updates u
                ON u.bus_id = b.id

            JOIN users p
                ON p.id = u.updated_by

            WHERE b.active = 1
            AND u.active = 1

            AND u.id = (
                SELECT MAX(u2.id)
                FROM bus_updates u2
                WHERE u2.bus_id = b.id
                AND u2.active = 1
            )
        """

        params = []

        if search:

            sql += " AND b.bus_number LIKE ?"
            params.append(f"%{search}%")

        if destination:

            sql += " AND u.destination = ?"
            params.append(destination)

        sql += " ORDER BY u.created_at DESC"

        buses = db.execute(sql, params).fetchall()

        # Includes default and custom destinations.

        destinations = db.execute("""
            SELECT label
            FROM options
            WHERE kind = 'destination'
            ORDER BY label
        """).fetchall()

    return render_template(
        "student.html",
        buses=buses,
        destinations=destinations,
        search=search,
        selected=destination
    )


# ---------------- CONTRACTOR DASHBOARD ----------------

@app.route("/contractor")
@role_required("contractor")
def contractor_dashboard():

    expire_old_bus_updates()

    user = current_user()

    with get_db() as db:

        buses = db.execute("""
            SELECT
                b.id,
                b.bus_number,
                u.destination,
                u.parking,
                u.departure_at,
                u.created_at

            FROM assignments a

            JOIN buses b
                ON b.id = a.bus_id

            LEFT JOIN bus_updates u
                ON u.id = (
                    SELECT MAX(id)
                    FROM bus_updates
                    WHERE bus_id = b.id
                    AND active = 1
                )

            WHERE a.contractor_id = ?
            AND b.active = 1

            ORDER BY b.bus_number

        """, (user["id"],)).fetchall()

        destinations = db.execute("""
            SELECT label
            FROM options
            WHERE kind = 'destination'
            ORDER BY label
        """).fetchall()

        parking = db.execute("""
            SELECT label
            FROM options
            WHERE kind = 'parking'
            ORDER BY label
        """).fetchall()

    return render_template(
        "contractor.html",
        buses=buses,
        destinations=destinations,
        parking=parking
    )


# ---------------- UPDATE BUS INFORMATION ----------------

@app.route(
    "/contractor/bus/<int:bus_id>/update",
    methods=["POST"]
)
@role_required("contractor")
def update_bus(bus_id):

    user = current_user()

    # Get the selected options
    destination_choice = request.form.get("destination", "").strip()
    parking_choice = request.form.get("parking", "").strip()

    # Check whether Other was selected
    destination_is_other = destination_choice == "Other"
    parking_is_other = parking_choice == "Other"

    # Get custom locations if Other was selected
    if destination_is_other:
        destination = request.form.get(
            "destination_other", ""
        ).strip()
    else:
        destination = destination_choice

    if parking_is_other:
        parking = request.form.get(
            "parking_other", ""
        ).strip()
    else:
        parking = parking_choice

    departure_choice = request.form.get("departure", "")
    custom_time = request.form.get("custom_time", "").strip()

    with get_db() as db:

        # Verify contractor owns this bus
        allowed = db.execute("""
            SELECT 1 FROM assignments
            WHERE contractor_id=? AND bus_id=?
        """, (user["id"], bus_id)).fetchone()

        bus = db.execute("""
            SELECT id FROM buses
            WHERE id=? AND active=1
        """, (bus_id,)).fetchone()

        if not allowed or not bus:
            abort(403)

        # Validate location fields
        if (
            not destination
            or not parking
            or len(destination) > 100
            or len(parking) > 100
            or destination.lower() == "other"
            or parking.lower() == "other"
        ):
            flash(
                "Enter a valid destination and parking location.",
                "danger"
            )
            return redirect(url_for("contractor_dashboard"))

        # Only check the database for normal dropdown selections.
        # Custom entries are allowed through Other.

        if not destination_is_other:
            valid_dest = db.execute("""
                SELECT 1 FROM options
                WHERE kind='destination' AND label=?
            """, (destination,)).fetchone()

            if not valid_dest:
                flash("Invalid destination selected.", "danger")
                return redirect(url_for("contractor_dashboard"))

        if not parking_is_other:
            valid_park = db.execute("""
                SELECT 1 FROM options
                WHERE kind='parking' AND label=?
            """, (parking,)).fetchone()

            if not valid_park:
                flash("Invalid parking location selected.", "danger")
                return redirect(url_for("contractor_dashboard"))

        # Calculate departure time
        now = datetime.now()

        if departure_choice == "now":
            departure = now

        elif departure_choice in ("5", "10", "15", "30"):
            departure = now + timedelta(
                minutes=int(departure_choice)
            )

        elif departure_choice == "custom":
            try:
                departure = datetime.strptime(
                    custom_time, "%Y-%m-%dT%H:%M"
                )
            except ValueError:
                flash("Choose a valid departure time.", "danger")
                return redirect(url_for("contractor_dashboard"))

        else:
            flash("Choose a departure time.", "danger")
            return redirect(url_for("contractor_dashboard"))

        # Save custom locations for future use
        db.execute("""
            INSERT OR IGNORE INTO options(kind, label)
            VALUES('destination', ?)
        """, (destination,))

        db.execute("""
            INSERT OR IGNORE INTO options(kind, label)
            VALUES('parking', ?)
        """, (parking,))

        # Deactivate previous update
        db.execute("""
            UPDATE bus_updates
            SET active=0
            WHERE bus_id=?
        """, (bus_id,))

        # Publish new update
        db.execute("""
            INSERT INTO bus_updates(
                bus_id, destination, parking,
                departure_at, updated_by, created_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            bus_id,
            destination,
            parking,
            departure.isoformat(timespec="seconds"),
            user["id"],
            now.isoformat(timespec="seconds")
        ))

    flash(
        "Bus information published successfully.",
        "success"
    )

    return redirect(url_for("contractor_dashboard"))
# ---------------- ADMIN DASHBOARD ----------------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():

    with get_db() as db:

        contractors = db.execute("""
    SELECT id, name, email, phone, active
    FROM users
    WHERE role = 'contractor'
    ORDER BY name
""").fetchall()

        buses = db.execute("""
            SELECT
                b.id,
                b.bus_number,
                b.active,
                u.name AS contractor

            FROM buses b

            LEFT JOIN assignments a
                ON a.bus_id = b.id

            LEFT JOIN users u
                ON u.id = a.contractor_id

            ORDER BY b.bus_number
        """).fetchall()

    return render_template(
        "admin.html",
        contractors=contractors,
        buses=buses
    )
@app.route("/admin/classroom-timetable", methods=["GET", "POST"])
@role_required("admin")
def admin_classroom_timetable():

    if request.method == "POST":

        file = request.files.get("timetable")

        if not file or not file.filename:
            flash("Please select an Excel file.", "danger")
            return redirect(url_for("admin_classroom_timetable"))

        if not file.filename.lower().endswith(".xlsx"):
            flash("Please upload an .xlsx Excel file.", "danger")
            return redirect(url_for("admin_classroom_timetable"))

        try:
            workbook = load_workbook(file, data_only=True)
            sheet = workbook.active

            rows = list(sheet.iter_rows(values_only=True))

            if not rows:
                raise ValueError("The Excel file is empty.")

            headers = [
                str(value).strip().lower() if value else ""
                for value in rows[0]
            ]

            required = [
                "day", "start time", "end time",
                "classroom", "subject", "faculty"
            ]

            if not all(column in headers for column in required):
                raise ValueError(
                    "Required columns: Day, Start Time, End Time, "
                    "Classroom, Subject, Faculty."
                )

            positions = [headers.index(column) for column in required]
            timetable = []

            for row in rows[1:]:
                if not row or all(value is None for value in row):
                    continue

                values = [row[position] for position in positions]

                day, start, end, room, subject, faculty = values

                if any(value is None for value in values):
                    raise ValueError("Some timetable cells are empty.")

                start = start.strftime("%H:%M") if hasattr(start, "strftime") else str(start).strip()
                end = end.strftime("%H:%M") if hasattr(end, "strftime") else str(end).strip()

                if len(start) == 5:
                    pass
                else:
                    raise ValueError("Times must use HH:MM format.")

                if len(end) != 5 or start >= end:
                    raise ValueError("Please check the timetable times.")

                timetable.append((
                    "Block 1",
                    str(day).strip().capitalize(),
                    start,
                    end,
                    str(room).strip(),
                    str(subject).strip(),
                    str(faculty).strip(),
                    datetime.now().isoformat()
                ))

            if not timetable:
                raise ValueError("No timetable entries were found.")

            with get_db() as db:
                db.execute(
                    "DELETE FROM classroom_schedule WHERE block = 'Block 1'"
                )

                db.executemany("""
                    INSERT INTO classroom_schedule
                    (block, day, start_time, end_time,
                     classroom, subject, faculty, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, timetable)

            flash(
                f"Successfully uploaded {len(timetable)} timetable entries!",
                "success"
            )

        except Exception as error:
            flash(f"Upload failed: {error}", "danger")

        return redirect(url_for("admin_classroom_timetable"))

    return render_template("admin_classroom_timetable.html")


# ---------------- CREATE CONTRACTOR ----------------

@app.route("/admin/contractor", methods=["POST"])
@role_required("admin")
def create_contractor():

    name = request.form.get(
        "name", ""
    ).strip()

    email = request.form.get(
        "email", ""
    ).strip().lower()
   
    phone = request.form.get("phone", "").strip()
    
    password = request.form.get(
        "password", ""
    )

    if not name or not email or len(password) < 8:

        flash(
            "Enter all contractor details. Password must be at least 8 characters.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    try:

        with get_db() as db:

            db.execute("""
                INSERT INTO users(
                name,
                email,
                password_hash,
                role,
                created_at,
                phone
)
VALUES(?,?,?,?,?,?)
            """, (
                name,
                email,
                generate_password_hash(password),
                "contractor",
                datetime.now().isoformat(timespec="seconds"),
                phone
            ))

        flash(
            "Contractor account created.",
            "success"
        )

    except sqlite3.IntegrityError:

        flash(
            "That email is already in use.",
            "danger"
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ---------------- CREATE BUS ----------------

@app.route("/admin/bus", methods=["POST"])
@role_required("admin")
def create_bus():

    number = request.form.get(
        "bus_number", ""
    ).strip()

    contractor_id = request.form.get(
        "contractor_id", ""
    ).strip()

    if not number or not contractor_id:

        flash(
            "Enter a bus number and choose a contractor.",
            "danger"
        )

        return redirect(
            url_for("admin_dashboard")
        )

    try:

        with get_db() as db:

            contractor = db.execute("""
                SELECT id
                FROM users
                WHERE id = ?
                AND role = 'contractor'
                AND active = 1
            """, (contractor_id,)).fetchone()

            if not contractor:

                flash(
                    "Select a valid active contractor.",
                    "danger"
                )

                return redirect(
                    url_for("admin_dashboard")
                )

            cur = db.execute("""
                INSERT INTO buses(bus_number)
                VALUES(?)
            """, (number,))

            db.execute("""
                INSERT INTO assignments(
                    contractor_id,
                    bus_id
                )
                VALUES(?,?)
            """, (
                contractor_id,
                cur.lastrowid
            ))

        flash(
            "Bus registered and assigned.",
            "success"
        )

    except sqlite3.IntegrityError:

        flash(
            "That bus number already exists.",
            "danger"
        )

    return redirect(
        url_for("admin_dashboard")
    )

# ---------------- EDIT EXISTING BUS ----------------

@app.route("/admin/bus/<int:bus_id>/edit", methods=["POST"])
@role_required("admin")
def edit_bus(bus_id):

    bus_number = request.form.get(
        "bus_number", ""
    ).strip()

    contractor_id = request.form.get(
        "contractor_id", ""
    ).strip()

    if not bus_number or not contractor_id:
        flash("Enter a bus number and select a contractor.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        with get_db() as db:

            # Check that the bus exists
            bus = db.execute("""
                SELECT id FROM buses
                WHERE id=?
            """, (bus_id,)).fetchone()

            if not bus:
                flash("Bus not found.", "danger")
                return redirect(url_for("admin_dashboard"))

            # Check that the selected contractor exists
            contractor = db.execute("""
                SELECT id FROM users
                WHERE id=?
                AND role='contractor'
                AND active=1
            """, (contractor_id,)).fetchone()

            if not contractor:
                flash("Select a valid active contractor.", "danger")
                return redirect(url_for("admin_dashboard"))

            # Update bus number
            db.execute("""
                UPDATE buses
                SET bus_number=?
                WHERE id=?
            """, (bus_number, bus_id))

            # Replace the old assignment
            db.execute("""
                DELETE FROM assignments
                WHERE bus_id=?
            """, (bus_id,))

            # Assign bus to the selected contractor
            db.execute("""
                INSERT INTO assignments(contractor_id, bus_id)
                VALUES(?,?)
            """, (contractor_id, bus_id))

        flash("Bus details updated successfully.", "success")

    except sqlite3.IntegrityError:
        flash("That bus number is already registered.", "danger")

    return redirect(url_for("admin_dashboard"))
# ---------------- TOGGLE CONTRACTOR ----------------

@app.route(
    "/admin/toggle-contractor/<int:user_id>",
    methods=["POST"]
)
@role_required("admin")
def toggle_contractor(user_id):

    with get_db() as db:

        db.execute("""
            UPDATE users
            SET active = CASE active
                WHEN 1 THEN 0
                ELSE 1
            END
            WHERE id = ?
            AND role = 'contractor'
        """, (user_id,))

    flash(
        "Contractor account status changed.",
        "success"
    )

    return redirect(
        url_for("admin_dashboard")
    )
# ---------------- VIEW LOST & FOUND REPORTS ----------------

@app.route("/lost-found")
@login_required
def lost_found():

    with get_db() as db:

        reports = db.execute("""
            SELECT
                lf.*,
                u.name AS reporter_name
            FROM lost_found lf

            JOIN users u
                ON u.id = lf.reported_by

            ORDER BY
                CASE lf.status
                    WHEN 'unclaimed' THEN 0
                    ELSE 1
                END,
                lf.created_at DESC
        """).fetchall()

    return render_template(
        "lost_found.html",
        reports=reports
    )
# ---------------- MARK ITEM AS CLAIMED ----------------

@app.route(
    "/lost-found/claim/<int:report_id>",
    methods=["POST"]
)
@login_required
def claim_lost_item(report_id):

    user = current_user()

    with get_db() as db:

        report = db.execute("""
            SELECT id, reported_by, status
            FROM lost_found
            WHERE id = ?
        """, (report_id,)).fetchone()

        if not report:
            abort(404)

        # Only the original reporter or an admin can claim it.
        if (
            report["reported_by"] != user["id"]
            and user["role"] != "admin"
        ):
            abort(403)

        if report["status"] == "unclaimed":

            db.execute("""
                UPDATE lost_found
                SET status = 'claimed'
                WHERE id = ?
            """, (report_id,))

            flash("Item marked as claimed.", "success")

        else:
            flash("This item is already marked as claimed.", "warning")

    return redirect(url_for("lost_found"))
# ---------------- DELETE LOST & FOUND REPORT ----------------

@app.route(
    "/lost-found/delete/<int:report_id>",
    methods=["POST"]
)
@role_required("admin")
def delete_lost_item(report_id):

    with get_db() as db:

        report = db.execute("""
            SELECT image_filename
            FROM lost_found
            WHERE id = ?
        """, (report_id,)).fetchone()

        if not report:
            abort(404)

        db.execute("""
            DELETE FROM lost_found
            WHERE id = ?
        """, (report_id,))

    # Delete the associated photo, if one exists.
    if report["image_filename"]:

        filename = os.path.basename(
            report["image_filename"]
        )

        image_path = os.path.join(
            UPLOAD_FOLDER,
            filename
        )

        if os.path.isfile(image_path):
            os.remove(image_path)

    flash("Lost & Found report removed.", "success")

    return redirect(url_for("lost_found"))
# ---------------- REPORT A LOST & FOUND ITEM ----------------

@app.route("/lost-found/report", methods=["GET", "POST"])
@role_required("student")
def report_lost_item():

    if request.method == "POST":

        item_name = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        bus_number = request.form.get("bus_number", "").strip()
        date_found = request.form.get("date_found", "").strip()
        collection_location = request.form.get(
            "collection_location", ""
        ).strip()

        photo = request.files.get("photo")

        # Check required fields
        if (
            not item_name
            or not description
            or not bus_number
            or not date_found
            or not collection_location
        ):
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("report_lost_item"))

        # Check field lengths
        if (
            len(item_name) > 100
            or len(description) > 1000
            or len(bus_number) > 50
            or len(collection_location) > 200
        ):
            flash("One or more fields are too long.", "danger")
            return redirect(url_for("report_lost_item"))

        # Validate date
        try:
            datetime.strptime(date_found, "%Y-%m-%d")
        except ValueError:
            flash("Please select a valid date.", "danger")
            return redirect(url_for("report_lost_item"))

        # Check whether the bus exists
        with get_db() as db:
            bus = db.execute("""
                SELECT bus_number
                FROM buses
                WHERE bus_number = ?
                AND active = 1
            """, (bus_number,)).fetchone()

        if not bus:
            flash("Please select a valid active bus.", "danger")
            return redirect(url_for("report_lost_item"))

        # Handle optional photo
        image_filename = None

        if photo and photo.filename:

            if not allowed_image(photo.filename):
                flash("Only JPG, JPEG, PNG and WEBP images are allowed.", "danger")
                return redirect(url_for("report_lost_item"))

            if not valid_image_content(photo):
                flash("The uploaded file is not a valid image.", "danger")
                return redirect(url_for("report_lost_item"))

            extension = secure_filename(
                photo.filename
            ).rsplit(".", 1)[1].lower()

            image_filename = f"{uuid.uuid4().hex}.{extension}"

            photo.save(
                os.path.join(UPLOAD_FOLDER, image_filename)
            )

        # Save report in database
        try:

            with get_db() as db:

                db.execute("""
                    INSERT INTO lost_found (
                        item_name,
                        description,
                        bus_number,
                        date_found,
                        collection_location,
                        image_filename,
                        reported_by,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ? ,?)
                """, (
                    item_name,
                    description,
                    bus_number,
                    date_found,
                    collection_location,
                    image_filename,
                    current_user()["id"],
                    datetime.now().isoformat(timespec="seconds")
                ))

        except Exception:

            if image_filename:
                image_path = os.path.join(
                    UPLOAD_FOLDER,
                    image_filename
                )

                if os.path.exists(image_path):
                    os.remove(image_path)

            raise

        flash("Your Lost & Found report has been published.", "success")
        return redirect(url_for("lost_found"))

    # Load active buses for the report form
    with get_db() as db:

        buses = db.execute("""
            SELECT bus_number
            FROM buses
            WHERE active = 1
            ORDER BY bus_number
        """).fetchall()

    return render_template(
        "lost_found_report.html",
        buses=buses
    )

# ---------------- ERROR PAGES ----------------

@app.errorhandler(403)
def forbidden(_error):

    return render_template(
        "message.html",
        title="Access restricted",
        message="Your account does not have permission to open this page."
    ), 403

@app.route("/classroom-tracker")
@role_required("student", "admin")
def classroom_tracker():
  return render_template("classroom_tracker.html", user=current_user())


@app.route("/classroom-tracker/availability", methods=["GET", "POST"])
@login_required
def classroom_availability():
    db = get_db()

    # Add demo timetable if no timetable has been uploaded yet
    count = db.execute(
        "SELECT COUNT(*) FROM classroom_schedule"
    ).fetchone()[0]

    if count == 0:
        sample_data = [
            ("Monday", "09:00", "10:00", "B1-101", "Mathematics", "Mr Sharma"),
            ("Monday", "10:00", "11:00", "B1-102", "Physics", "Ms Verma"),
            ("Monday", "11:00", "12:00", "B1-103", "Computer Science", "Mr Singh"),
            ("Tuesday", "09:00", "10:00", "B1-102", "Chemistry", "Ms Kaur"),
            ("Tuesday", "11:00", "12:00", "B1-104", "English", "Mr Gupta"),
            ("Wednesday", "10:00", "11:00", "B1-101", "Programming", "Mr Singh"),
            ("Thursday", "09:00", "10:00", "B1-103", "Physics", "Ms Verma"),
            ("Friday", "12:00", "13:00", "B1-104", "Mathematics", "Mr Sharma"),
        ]

        for item in sample_data:
            db.execute("""
                INSERT INTO classroom_schedule
                (day, start_time, end_time, classroom,
                 subject, faculty, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (*item, datetime.now().isoformat()))

        db.commit()

    searched = False
    free_rooms = []
    occupied_rooms = []

    if request.method == "POST":
        day = request.form.get("day", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")

        valid_days = [
            "Monday", "Tuesday", "Wednesday",
            "Thursday", "Friday", "Saturday", "Sunday"
        ]

        if (
            day not in valid_days
            or not start_time
            or not end_time
            or start_time >= end_time
        ):
            flash("Please select a valid day and time range.", "error")
        else:
            searched = True

            all_rooms = db.execute("""
                SELECT DISTINCT classroom
                FROM classroom_schedule
                WHERE block = 'Block 1'
                ORDER BY classroom
            """).fetchall()

            occupied_rooms = db.execute("""
                SELECT classroom, subject, faculty
                FROM classroom_schedule
                WHERE block = 'Block 1'
                AND day = ?
                AND start_time < ?
                AND end_time > ?
                ORDER BY classroom
            """, (day, end_time, start_time)).fetchall()

            occupied_names = {
                room["classroom"] for room in occupied_rooms
            }

            free_rooms = [
                room["classroom"]
                for room in all_rooms
                if room["classroom"] not in occupied_names
            ]

    return render_template(
        "classroom_availability.html",
        searched=searched,
        free_rooms=free_rooms,
        occupied_rooms=occupied_rooms
    )
@app.errorhandler(404)
def not_found(_error):

    return render_template(
        "message.html",
        title="Page not found",
        message="That page does not exist."
    ), 404


# ---------------- CREATE ADMIN COMMAND ----------------

@app.cli.command("create-admin")
def create_admin():

    """Create the first administrator."""

    import getpass

    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()

    password = getpass.getpass(
        "Admin password (8+ characters): "
    )

    if len(password) < 8:

        print(
            "Password must be at least 8 characters."
        )

        return

    try:

        with get_db() as db:

            db.execute("""
                INSERT INTO users(
                    name,
                    email,
                    password_hash,
                    role,
                    created_at
                )
                VALUES(?,?,?,?,?)
            """, (
                name,
                email,
                generate_password_hash(password),
                "admin",
                datetime.now().isoformat(timespec="seconds")
            ))

        print(
            "Admin created. Start the app and log in."
        )

    except sqlite3.IntegrityError:

        print(
            "That email is already registered."
        )


# ---------------- START APPLICATION ----------------

init_db()

if __name__ == "__main__":
    app.run(debug=True) 