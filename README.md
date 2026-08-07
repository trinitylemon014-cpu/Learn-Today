# 🎓 Learn Together — Next-Gen LMS (2030 Edition)

A fully functional Learning Management System built with Flask, featuring real-time group chat, teacher analytics, parent monitoring, and a modern 2030-style UI.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd learn-together
pip install -r requirements.txt
```

### 2. Run the App
```bash
python app.py
```

### 3. Open in Browser
```
http://localhost:5000
```

The database is **auto-created** with seed data on first run.

---

## 🔑 Demo Accounts

| Role    | Email                        | Password    |
|---------|------------------------------|-------------|
| Student | student@learntogether.com    | student123  |
| Teacher | teacher@learntogether.com    | teacher123  |
| Parent  | parent@learntogether.com     | parent123   |
| Admin   | admin@learntogether.com      | admin123    |

---

## 👥 User Roles & Features

### 🎓 Student
- Browse and enroll in courses
- Watch videos, read notes, view presentations
- Track personal progress with visual bars
- Join and chat in discussion groups
- Link parent account via profile settings

### 👨‍🏫 Teacher
- Create courses with multi-type content (video, note, presentation)
- Auto-generated course discussion group on creation
- Full analytics dashboard per course (progress, engagement, attendance)
- Create and manage attendance sessions
- Moderate discussion groups

### 👨‍👩‍👧 Parent
- Link to student via shared email
- View student progress across all courses
- See attendance rates per course
- Full activity timeline

### 🛡️ Admin
- Manage all users (view, filter, delete)
- Overview of all courses and analytics
- Platform health dashboard

---

## 💬 Discussion Groups

- **Course Groups** — Auto-created when a teacher creates a course; students auto-join on enrollment
- **Teacher Groups** — Created by teachers for revision, Q&A sessions
- **Student Groups** — Created by students for peer study
- Real-time polling chat (refreshes every 3 seconds)
- Member list with roles

---

## 📊 Analytics Features

- Per-student progress tracking
- Visual bar chart of class performance
- Top performers leaderboard
- Students needing attention alerts
- Attendance rate per student
- Activity log (views, completions)

---

## 📅 Attendance System

- **Session-based**: Teacher creates a session → marks each student Present / Absent / Late
- **Activity-based**: Automatically logged when students view content

---

## 🗂️ Project Structure

```
learn-together/
├── app.py              # All Flask routes & app logic
├── models.py           # SQLAlchemy database models
├── requirements.txt
├── database.db         # Auto-created SQLite database
├── static/
│   ├── css/
│   │   └── style.css   # Full design system
│   └── js/
│       └── main.js     # Chat polling, UI interactions
└── templates/
    ├── base.html               # Sidebar + topbar layout
    ├── index.html              # Landing page
    ├── login.html
    ├── register.html
    ├── dashboard_student.html
    ├── dashboard_teacher.html
    ├── dashboard_parent.html
    ├── dashboard_admin.html
    ├── courses.html
    ├── course_detail.html
    ├── create_course.html
    ├── add_content.html
    ├── view_content.html
    ├── groups.html
    ├── group_detail.html
    ├── create_group.html
    ├── analytics.html
    ├── attendance.html
    ├── parent_student.html
    ├── profile.html
    ├── admin_users.html
    └── admin_courses.html
```

---

## 🎨 Design System

| Token       | Value             | Usage                     |
|-------------|-------------------|---------------------------|
| `--navy`    | `#0F1F3D`         | Primary UI, sidebar       |
| `--blue`    | `#2563EB`         | Buttons, links, active    |
| `--green`   | `#10B981`         | Success, progress         |
| `--purple`  | `#7C3AED`         | Groups, highlights        |
| `--white`   | `#FFFFFF`         | Background, cards         |

**Fonts**: Outfit (display/headings) + Inter (body)

---

## 🛠️ Tech Stack

- **Backend**: Python 3 + Flask 3
- **Database**: SQLite via Flask-SQLAlchemy
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (no framework)
- **Chat**: AJAX polling every 3 seconds
- **Auth**: Session-based with SHA-256 password hashing

---

## 📝 Adding Content

As a teacher, you can add three types of content:

1. **📄 Note** — Rich text lesson written directly in the app
2. **🎬 Video** — YouTube embed URL (auto-embeds) or external link
3. **📊 Presentation** — Link to Google Slides or any presentation URL

---

Built with ❤️ for the future of education.
