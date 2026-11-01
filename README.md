# 🚀 CampCore – Smart Campus Management Platform

**CampCore** is a smart campus management platform built using Python, Flask, SQLite, HTML and CSS. It integrates essential college services into one platform, making campus life more organised, accessible and convenient.

## 🌟 Key Features

### 🚌 1. Transport Management
- Separate dashboards for Students, Contractors and Admins.
- Student registration and secure login.
- Admin-created contractor accounts.
- Admin bus registration and contractor assignment.
- Contractors can manage only their assigned buses.
- Publish bus destination, parking location and departure time.
- Quick departure options and custom departure times.
- Custom destination and parking options.
- Automatic expiry of outdated bus updates.
- Students can search buses by bus number and filter by destination.

### 🏫 2. Classroom Availability Tracker
- Check classroom availability for a selected day and time.
- Displays available and occupied classrooms.
- Admin can upload classroom timetables through Excel files.
- Automatic timetable data processing.
- Sample timetable data for initial demonstration.

### 🔎 3. Lost & Found System
- Students can report lost or found items.
- Upload photographs of reported items.
- Include bus number and collection location.
- View reported items in a shared listing.
- Mark items as claimed.
- Admin can remove reports.

### 👤 4. User Profile & Settings
- Update profile information.
- Change username, phone number and location.
- Change account password.
- View contractor contact information.

## 👥 User Roles

| Role | Responsibilities |
|---|---|
| Student | Track buses, check classroom availability and access Lost & Found. |
| Contractor | Publish transport updates for assigned buses. |
| Admin | Manage contractors, buses, assignments and classroom timetables. |

## 🛠️ Technologies Used

- **Backend:** Python, Flask
- **Database:** SQLite
- **Frontend:** HTML5, CSS3
- **Excel Processing:** OpenPyXL
- **Authentication:** Werkzeug Password Hashing

## ⚙️ Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/Shivendra-dev04/Campcore
cd campcore
```

### 2. Create a virtual environment

For Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
py -m pip install -r requirements.txt
```

### 4. Create the first administrator account

```bash
flask --app app create-admin
```

Follow the instructions in the terminal to create your admin credentials.

### 5. Run the application

```bash
flask --app app run --debug
```

Open the following address in your browser:

`http://127.0.0.1:5000`

## 🔄 Initial Setup Workflow

1. Create an administrator account.
2. Log in to the Admin Dashboard.
3. Create contractor accounts.
4. Register buses and assign them to contractors.
5. Students can create their accounts through registration.
6. Contractors log in and publish bus updates.
7. Students can view the latest published bus information.
8. Admins can upload classroom timetables for classroom availability tracking.

## 🔐 Security Features

- Password hashing using Werkzeug.
- Role-based authentication and authorization.
- Backend permission checks.
- Contractor-to-bus assignment verification.
- Image file type and content validation.
- Session-based authentication.

## 📌 Project Status

CampCore is a **Hackathon MVP (Minimum Viable Product)** developed to demonstrate the integration of multiple campus services into one web application.

The current version runs locally and can be extended with cloud deployment, additional campus modules and production-level security improvements.

## 🔮 Future Improvements

- Live cloud deployment.
- Mobile-friendly interface improvements.
- Real-time notifications for bus updates.
- GPS-based bus tracking.
- More advanced classroom scheduling.
- Improved admin analytics and reporting.

---

### CampCore
**Making Campus Management Smarter, Simpler and More Connected.**
