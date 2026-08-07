from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # student/teacher/parent/admin
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/approved/denied
    date_of_birth = db.Column(db.Date, nullable=True)
    previous_school = db.Column(db.String(200), nullable=True)
    courses_interest = db.Column(db.Text, nullable=True)
    cv_path = db.Column(db.String(300), nullable=True)
    parent_name = db.Column(db.String(100), nullable=True)
    parent_email = db.Column(db.String(150), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    avatar = db.Column(db.String(200), nullable=True)
    password_reset_token = db.Column(db.String(256), nullable=True, unique=True)
    token_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    courses_taught = db.relationship('Course', backref='teacher', lazy=True, foreign_keys='Course.teacher_id')
    enrollments = db.relationship('Enrollment', backref='student', lazy=True, foreign_keys='Enrollment.student_id')
    sent_messages = db.relationship('Message', backref='sender', lazy=True, foreign_keys='Message.sender_id')
    activity_logs = db.relationship('ActivityLog', backref='student', lazy=True, foreign_keys='ActivityLog.student_id')
    deleted_message_views = db.relationship('MessageVisibility', backref='user', lazy=True, foreign_keys='MessageVisibility.user_id')
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade='all, delete-orphan', foreign_keys='Notification.user_id')

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300), nullable=True)
    kind = db.Column(db.String(30), nullable=False, default='notification')  # notification/reminder
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reminder_for = db.Column(db.DateTime, nullable=True)

class ApplicationPageConfig(db.Model):
    __tablename__ = 'application_page_config'
    id = db.Column(db.Integer, primary_key=True)
    headline = db.Column(db.String(250), nullable=False, default='Application status')
    subtitle = db.Column(db.String(400), nullable=True)
    main_text = db.Column(db.Text, nullable=True)
    details_text = db.Column(db.Text, nullable=True)
    promo_text = db.Column(db.Text, nullable=True)
    footer_text = db.Column(db.Text, nullable=True)
    banner_image = db.Column(db.String(300), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SiteMedia(db.Model):
    __tablename__ = 'site_media'
    id = db.Column(db.Integer, primary_key=True)
    media_type = db.Column(db.String(50), nullable=False)  # login_image/signup_image/landing_video
    file_path = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    admin = db.relationship('User', foreign_keys=[uploaded_by])

class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    level = db.Column(db.String(50), default='beginner')
    thumbnail = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    enrollments = db.relationship('Enrollment', backref='course', lazy=True)
    contents = db.relationship('CourseContent', backref='course', lazy=True)
    groups = db.relationship('Group', backref='course', lazy=True)

class CourseContent(db.Model):
    __tablename__ = 'course_contents'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content_type = db.Column(db.String(20), default='note')  # video/note/presentation
    content_url = db.Column(db.String(500), nullable=True)
    body = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)

class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_type = db.Column(db.String(20), default='student')  # course/teacher/student
    avatar = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])
    members = db.relationship('GroupMember', backref='group', lazy=True)
    messages = db.relationship('Message', backref='group', lazy=True)

class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # admin/member
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=True)
    attachment_type = db.Column(db.String(20), nullable=True)
    attachment_url = db.Column(db.String(500), nullable=True)
    attachment_name = db.Column(db.String(255), nullable=True)
    attachment_mime = db.Column(db.String(100), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)
    deleted_for_all = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    visible_to_users = db.relationship('MessageVisibility', backref='message', lazy=True, cascade='all, delete-orphan')

class MessageVisibility(db.Model):
    __tablename__ = 'message_visibility'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('message_id', 'user_id', name='uq_message_visibility'),
    )


class MessageDelivery(db.Model):
    __tablename__ = 'message_delivery'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    delivered_at = db.Column(db.DateTime, nullable=True)
    seen_at = db.Column(db.DateTime, nullable=True)

    message = db.relationship('Message', foreign_keys=[message_id])
    user = db.relationship('User', foreign_keys=[user_id])

class Progress(db.Model):
    __tablename__ = 'progress'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    progress_percent = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', foreign_keys=[course_id])

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    content_id = db.Column(db.Integer, db.ForeignKey('course_contents.id'), nullable=True)
    action = db.Column(db.String(50), default='viewed')  # viewed/completed
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', foreign_keys=[course_id])
    content = db.relationship('CourseContent', foreign_keys=[content_id])

class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, default=date.today)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', foreign_keys=[course_id])
    records = db.relationship('Attendance', backref='session', lazy=True)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('attendance_sessions.id'), nullable=True)
    status = db.Column(db.String(20), default='present')  # present/absent/late
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', foreign_keys=[student_id])
    course = db.relationship('Course', foreign_keys=[course_id])


class ScheduledLesson(db.Model):
    __tablename__ = 'scheduled_lessons'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    meet_link = db.Column(db.String(500), nullable=False)
    poster_url = db.Column(db.String(300), nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', foreign_keys=[course_id])
    teacher = db.relationship('User', foreign_keys=[teacher_id])


class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)
    reminder_at = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    event_type = db.Column(db.String(50), nullable=False, default='goal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
