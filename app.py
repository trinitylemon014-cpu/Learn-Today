from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, get_flashed_messages
from flask_socketio import SocketIO, join_room, leave_room
from models import db, User, Course, Enrollment, Group, GroupMember, Message, MessageVisibility, MessageDelivery, Progress, ActivityLog, Attendance, AttendanceSession, CourseContent, Notification, ApplicationPageConfig, ScheduledLesson, CalendarEvent, SiteMedia
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None

import os
from datetime import datetime, date, time, timedelta
from sqlalchemy import text, create_engine
from sqlalchemy.exc import OperationalError
import calendar
import random
import string
import secrets
from werkzeug.utils import secure_filename
import uuid
import hashlib

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'ogg'}
ALLOWED_PRESENTATION_EXTENSIONS = {'pdf', 'ppt', 'pptx'}
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv'}

app = Flask(__name__)
app.secret_key = 'learntogether2030secretkey'
socketio = SocketIO(app)
instance_path = os.path.join(app.root_path, 'instance')
if load_dotenv is not None:
    load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_DB_URL = os.getenv('SUPABASE_DB_URL') or os.getenv('DATABASE_URL')
SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'media')
USE_SUPABASE = bool(SUPABASE_DB_URL or (SUPABASE_URL and SUPABASE_ANON_KEY))
SUPABASE_ENABLED = bool(SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY))
supabase_client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
) if SUPABASE_ENABLED and create_client else None

# In-memory throttle map for typing events: {(group_id, sender): timestamp}
typing_last_by_sender = {}

@socketio.on('join')
def handle_join(data):
    group_id = data.get('groupId')
    if group_id:
        join_room(f'group_{group_id}')

@socketio.on('leave')
def handle_leave(data):
    group_id = data.get('groupId')
    if group_id:
        leave_room(f'group_{group_id}')

@socketio.on('connect')
def handle_connect():
    return

@socketio.on('disconnect')
def handle_disconnect():
    return


@socketio.on('typing')
def handle_typing(data):
    try:
        group_id = int(data.get('groupId'))
    except Exception:
        group_id = None
    sender = data.get('sender')
    key = (group_id, sender)
    now = datetime.utcnow().timestamp()
    last = typing_last_by_sender.get(key, 0)
    # server-side throttle: allow once per 0.7s
    if now - last < 0.7:
        return
    typing_last_by_sender[key] = now
    if group_id:
        socketio.emit('group-typing', {'groupId': group_id, 'sender': sender}, room=f'group_{group_id}', include_self=False)


@socketio.on('message-delivered')
def handle_message_delivered(data):
    try:
        group_id = int(data.get('groupId'))
        message_id = int(data.get('messageId'))
        user_id = int(data.get('userId'))
    except Exception:
        return
    with app.app_context():
        md = db.session.query(MessageDelivery).filter_by(message_id=message_id, user_id=user_id).first()
        if md and not md.delivered_at:
            md.delivered_at = datetime.utcnow()
            db.session.commit()
            # notify sender that this user has delivered
            msg = {'messageId': message_id, 'userId': user_id, 'status': 'delivered'}
            socketio.emit('message-status', msg, room=f'group_{group_id}', include_self=False)


@socketio.on('message-seen')
def handle_message_seen(data):
    try:
        group_id = int(data.get('groupId'))
        message_id = int(data.get('messageId'))
        user_id = int(data.get('userId'))
    except Exception:
        return
    with app.app_context():
        md = db.session.query(MessageDelivery).filter_by(message_id=message_id, user_id=user_id).first()
        if md and not md.seen_at:
            md.seen_at = datetime.utcnow()
            db.session.commit()
            # notify room about seen status so sender can update UI
            msg = {'messageId': message_id, 'userId': user_id, 'status': 'seen'}
            socketio.emit('message-status', msg, room=f'group_{group_id}', include_self=False)
os.makedirs(instance_path, exist_ok=True)
if USE_SUPABASE and SUPABASE_DB_URL:
    database_url = SUPABASE_DB_URL
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    elif database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    db_path = os.path.join(instance_path, 'database.db').replace('\\', '/')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.logger.info('Supabase mode enabled' if USE_SUPABASE else 'Using local SQLite fallback')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def attachment_type_for(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return 'image'
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return 'video'
    if ext in {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'zip', 'rar'}:
        return 'document'
    return 'file'


def attachment_extension(filename):
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def attachment_icon_label(filename, attachment_type):
    ext = attachment_extension(filename)
    if attachment_type == 'image':
        return 'IMG'
    if attachment_type == 'video':
        return 'VID'
    if ext:
        return ext.upper()
    return 'FILE'


def attachment_icon_class(filename, attachment_type):
    ext = attachment_extension(filename)
    if ext == 'pdf':
        return 'file-icon-pdf'
    if ext in {'doc', 'docx'}:
        return 'file-icon-doc'
    if ext in {'ppt', 'pptx'}:
        return 'file-icon-ppt'
    if ext in {'xls', 'xlsx'}:
        return 'file-icon-xls'
    if ext in {'py', 'js', 'ts', 'java', 'c', 'cpp', 'rb', 'go', 'php'}:
        return 'file-icon-code'
    if attachment_type == 'image':
        return 'file-icon-image'
    if attachment_type == 'video':
        return 'file-icon-video'
    return 'file-icon-file'


def attachment_meta_label(filename, attachment_type):
    ext = attachment_extension(filename)
    if attachment_type == 'image':
        return 'Image'
    if attachment_type == 'video':
        return 'Video'
    if ext == 'pdf':
        return 'PDF'
    if ext in {'doc', 'docx'}:
        return 'Word file'
    if ext in {'ppt', 'pptx'}:
        return 'Presentation'
    if ext in {'xls', 'xlsx'}:
        return 'Spreadsheet'
    if ext in {'py', 'js', 'ts', 'java', 'c', 'cpp', 'rb', 'go', 'php'}:
        return 'Code file'
    if ext:
        return f'{ext.upper()} file'
    if attachment_type:
        return attachment_type.capitalize()
    return 'Attachment'


def save_uploaded_file(upload, folder, allowed_extensions):
    if upload and upload.filename and allowed_file(upload.filename, allowed_extensions):
        filename = secure_filename(upload.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        unique_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
        storage_path = f"{folder}/{unique_name}"

        if USE_SUPABASE and supabase_client:
            content = upload.read()
            if not content:
                return None
            content_type = upload.mimetype or upload.content_type or 'application/octet-stream'
            try:
                supabase_client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
                    storage_path,
                    content,
                    file_options={'content-type': content_type}
                )
                return supabase_client.storage.from_(SUPABASE_STORAGE_BUCKET).get_public_url(storage_path)
            except Exception as exc:
                raise RuntimeError(f'Supabase storage upload failed: {exc}') from exc

        dest_folder = os.path.join(app.config['UPLOAD_FOLDER'], folder)
        os.makedirs(dest_folder, exist_ok=True)
        path = os.path.join(dest_folder, unique_name)
        upload.save(path)
        return f'uploads/{folder}/{unique_name}'
    return None


db.init_app(app)


def _ensure_sqlalchemy_engine():
    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        if not uri:
            raise RuntimeError('SQLALCHEMY_DATABASE_URI is not set')
        engine = db.engines.get(None)
        if engine is None:
            engine = create_engine(uri)
            db.engines[None] = engine
            db.session.bind = engine
        return engine


_original_create_all = db.create_all
_original_drop_all = db.drop_all


def _create_all(*args, **kwargs):
    _ensure_sqlalchemy_engine()
    db.session.remove()
    return _original_create_all(*args, **kwargs)


def _drop_all(*args, **kwargs):
    _ensure_sqlalchemy_engine()
    db.session.remove()
    return _original_drop_all(*args, **kwargs)


db.create_all = _create_all
db.drop_all = _drop_all


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, stored_password):
    if not password or not stored_password:
        return False
    if stored_password == password:
        return True
    if stored_password == hash_password(password):
        return True
    return False


def parse_date_input(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        # try ISO parse
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def password_meets_policy(pw: str) -> bool:
    if not pw or len(pw) < 8:
        return False
    import re
    if not re.search(r'[A-Z]', pw):
        return False
    if not re.search(r'[^A-Za-z0-9]', pw):
        return False
    return True


def initials_for_name(name):
    parts = [part for part in (name or '').split() if part]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def build_static_url(path):
    if not path:
        return None
    if isinstance(path, str) and path.startswith(('http://', 'https://')):
        return path
    try:
        return url_for('static', filename=path)
    except Exception:
        return f"/static/{path}"


TABLE_NAME_BY_MODEL = {
    User: 'users',
    Notification: 'notifications',
    ApplicationPageConfig: 'application_page_config',
    SiteMedia: 'site_media',
    Course: 'courses',
    CourseContent: 'course_contents',
    Enrollment: 'enrollments',
    Group: 'groups',
    GroupMember: 'group_members',
    Message: 'messages',
    MessageVisibility: 'message_visibility',
    Progress: 'progress',
    ActivityLog: 'activity_logs',
    AttendanceSession: 'attendance_sessions',
    Attendance: 'attendance',
    ScheduledLesson: 'scheduled_lessons',
    CalendarEvent: 'calendar_events',
}


def _model_to_payload(obj):
    """
    Build a {db_column_name: value} payload for Supabase sync.

    IMPORTANT: we iterate the SQLAlchemy *mapper's* column attributes
    (which know both the Python attribute name and the real DB column
    name) rather than raw obj.__table__.columns. This matters whenever
    a model's Python attribute name differs from its DB column name
    (e.g. Notification.extra_data is mapped to the DB column
    "metadata"). Using getattr(obj, column.name) directly would be
    wrong in that case, since "metadata" as a bare attribute on a
    db.Model resolves to SQLAlchemy's reserved internal metadata
    object, not your data.
    """
    if obj is None:
        return {}
    payload = {}
    mapper = db.inspect(obj.__class__)
    for column_attr in mapper.column_attrs:
        python_attr_name = column_attr.key
        db_column_name = column_attr.columns[0].name
        value = getattr(obj, python_attr_name, None)
        if value is None:
            payload[db_column_name] = None
            continue
        if isinstance(value, (datetime, date, time)):
            payload[db_column_name] = value.isoformat()
        elif isinstance(value, bool):
            payload[db_column_name] = value
        else:
            payload[db_column_name] = value
    return payload


def sync_model_to_supabase(obj):
    if not USE_SUPABASE or not supabase_client or not obj:
        return
    table_name = TABLE_NAME_BY_MODEL.get(type(obj))
    if not table_name:
        return
    try:
        payload = _model_to_payload(obj)
        if getattr(obj, 'id', None) is None:
            supabase_client.table(table_name).insert(payload).execute()
        else:
            supabase_client.table(table_name).upsert(payload, on_conflict='id').execute()
    except Exception as exc:
        app.logger.warning('Supabase sync failed for %s: %s', table_name, exc)


_original_session_commit = db.session.commit


def _commit_with_supabase(*args, **kwargs):
    pending_objects = list(db.session.new) + list(db.session.dirty)
    result = _original_session_commit(*args, **kwargs)
    for obj in pending_objects:
        sync_model_to_supabase(obj)
    return result


db.session.commit = _commit_with_supabase


def user_identity(user):
    if not user:
        return {'name': 'Guest', 'initials': '?', 'avatar': None, 'avatar_url': None, 'color': 'hsl(225 70% 55%)'}
    seed = str(user.id or user.name)
    digest = hashlib.md5(seed.encode()).hexdigest()
    hue = int(digest[:2], 16) % 360
    return {
        'name': user.name or 'User',
        'initials': initials_for_name(user.name),
        'avatar': user.avatar,
        'avatar_url': build_static_url(user.avatar),
        'color': f'hsl({hue} 70% 46%)'
    }


def group_identity(group):
    if not group:
        return {'name': 'Group', 'initials': 'G', 'avatar': None, 'avatar_url': None, 'color': 'hsl(260 70% 55%)'}
    seed = str(group.id or group.name)
    digest = hashlib.md5(seed.encode()).hexdigest()
    hue = int(digest[:2], 16) % 360
    group_avatar = getattr(group, 'avatar', None)
    return {
        'name': group.name or 'Group',
        'initials': initials_for_name(group.name),
        'avatar': group_avatar,
        'avatar_url': build_static_url(group_avatar),
        'color': f'hsl({hue} 70% 46%)'
    }


def ensure_database_schema():
    with app.app_context():
        try:
            _ensure_sqlalchemy_engine()
            inspector = db.inspect(db.engine)
        except Exception as exc:
            app.logger.warning('Supabase/Postgres schema inspection failed, using local SQLite fallback: %s', exc)
            db_path = os.path.join(instance_path, 'database.db').replace('\\', '/')
            app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
            db.session.remove()
            db.engines.pop(None, None)
            _ensure_sqlalchemy_engine()
            inspector = db.inspect(db.engine)

        existing_tables = inspector.get_table_names()
        try:
            db.create_all()
        except Exception as exc:
            if 'already exists' not in str(exc).lower():
                app.logger.warning('Schema creation skipped: %s', exc)
        inspector = db.inspect(db.engine)
        existing_tables = inspector.get_table_names()

        if 'users' not in existing_tables:
            try:
                db.create_all()
            except Exception as exc:
                if 'already exists' not in str(exc).lower():
                    app.logger.warning('Schema creation skipped: %s', exc)
            inspector = db.inspect(db.engine)
            existing_tables = inspector.get_table_names()

        if 'groups' in existing_tables:
            columns = {column['name'] for column in inspector.get_columns('groups')}
            if 'avatar' not in columns:
                db.session.execute(text("ALTER TABLE groups ADD COLUMN avatar VARCHAR(200)"))
                db.session.commit()
        if 'messages' in inspector.get_table_names():
            columns = {column['name'] for column in inspector.get_columns('messages')}
            for column_name, column_type in [
                ('attachment_type', 'VARCHAR(20)'),
                ('attachment_url', 'VARCHAR(500)'),
                ('attachment_name', 'VARCHAR(255)'),
                ('attachment_mime', 'VARCHAR(100)'),
                ('is_pinned', 'BOOLEAN'),
                ('deleted_for_all', 'BOOLEAN'),
            ]:
                if column_name not in columns:
                    db.session.execute(text(f"ALTER TABLE messages ADD COLUMN {column_name} {column_type}"))
                    db.session.commit()
        # Ensure notifications table has extended columns for group-message support
        if 'notifications' in inspector.get_table_names():
            columns = {column['name'] for column in inspector.get_columns('notifications')}
            for column_name, column_type in [
                ('sender_id', 'INTEGER'),
                ('group_id', 'INTEGER'),
                ('message_id', 'INTEGER'),
                ('read_at', 'TIMESTAMP'),
                ('target_url', 'VARCHAR(300)'),
                ('metadata', 'JSON'),
            ]:
                if column_name not in columns:
                    try:
                        db.session.execute(text(f"ALTER TABLE notifications ADD COLUMN {column_name} {column_type}"))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
            # Create uniqueness index to prevent duplicate notifications for same recipient+message+kind
            try:
                db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_message_kind ON notifications (user_id, message_id, kind)"))
                db.session.commit()
            except Exception:
                db.session.rollback()
        if 'scheduled_lessons' in existing_tables:
            columns = {column['name'] for column in inspector.get_columns('scheduled_lessons')}
            if 'poster_url' not in columns:
                db.session.execute(text("ALTER TABLE scheduled_lessons ADD COLUMN poster_url VARCHAR(300)"))
                db.session.commit()
        if 'users' in existing_tables:
            columns = {column['name'] for column in inspector.get_columns('users')}
            for column_name, column_type in [
                ('status', 'VARCHAR(20)'),
                ('date_of_birth', 'DATE'),
                ('previous_school', 'VARCHAR(200)'),
                ('courses_interest', 'TEXT'),
                ('cv_path', 'VARCHAR(300)'),
                ('parent_name', 'VARCHAR(100)'),
            ]:
                if column_name not in columns:
                    db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))
                    db.session.commit()
            db.session.execute(text("UPDATE users SET status='approved' WHERE status IS NULL"))
            db.session.commit()


@app.before_request
def ensure_schema_on_request():
    ensure_database_schema()
    ensure_demo_accounts_exist()


def get_current_user():
    try:
        ensure_database_schema()
    except Exception:
        return None

    if 'user_id' in session:
        try:
            return db.session.get(User, session['user_id'])
        except Exception:
            return None
    return None


def is_group_member(user, group_id):
    if not user:
        return False
    return GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first() is not None


def can_manage_message(user, message):
    if not user or not message:
        return False
    if user.role == 'admin':
        return True
    group_member = GroupMember.query.filter_by(group_id=message.group_id, user_id=user.id).first()
    if group_member and group_member.role == 'admin':
        return True
    return message.sender_id == user.id


def message_is_visible(message, user_id):
    if not message:
        return False
    if message.deleted_for_all:
        return False
    if not user_id:
        return True
    return MessageVisibility.query.filter_by(message_id=message.id, user_id=user_id).first() is None


@app.context_processor
def inject_user():
    user = get_current_user()
    unread_count = 0
    user_group_ids = []
    if user:
        unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
        user_group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=user.id).all()]
    return {
        'current_user': user,
        'identity_for_user': user_identity,
        'identity_for_group': group_identity,
        'can_manage_message': can_manage_message,
        'unread_notification_count': unread_count,
        'user_group_ids': user_group_ids,
        'SUPABASE_URL': SUPABASE_URL,
        'SUPABASE_ANON_KEY': SUPABASE_ANON_KEY,
    }


ensure_database_schema()

# ─── AUTH ROUTES ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    courses = Course.query.limit(6).all()
    return render_template('index.html', courses=courses)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.status == 'pending':
            return redirect(url_for('application_status', email=email))
        if user and user.status == 'denied':
            return redirect(url_for('application_status', email=email))
        if user and user.status == 'approved' and user.password == hash_password(''):
            return redirect(url_for('application_status', email=email))
        if user and verify_password(password, user.password):
            is_legacy_plaintext = user.password == password and user.password != hash_password(password)
            if user.status in ('approved', None) or is_legacy_plaintext:
                if user.password != password and user.password != hash_password(password):
                    user.password = hash_password(password)
                    db.session.commit()
                session['user_id'] = user.id
                session['role'] = user.role
                flash(f'Welcome back, {user.name}!', 'success')
                return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    
    # Get active login media
    login_media = SiteMedia.query.filter_by(media_type='login_image', is_active=True).first()
    return render_template('login.html', login_media=login_media)

@app.route('/application-status')
def application_status():
    email = request.args.get('email', '').strip().lower()
    config = ApplicationPageConfig.query.first()
    if not config:
        config = ApplicationPageConfig(
            headline='Application status',
            subtitle='Track your application and next steps for Learn Together.',
            main_text='Your application status is visible on this page. If your account is approved, you may return to login and sign in using your approved email.',
            details_text='Admin can update this page with announcements, guidance, and next steps for applicants.',
            promo_text='Learn Together helps students, teachers, and parents stay connected and make progress with every step.',
            footer_text='Applications are usually reviewed within one hour. Approval may happen sooner based on application details.',
        )
        db.session.add(config)
        db.session.commit()

    user = User.query.filter_by(email=email).first() if email else None
    if not user:
        status_text = 'Your application is being processed. Please use the email you applied with and check again shortly.'
        show_setup_link = False
    elif user.status == 'pending':
        status_text = 'Your application is pending review by the Learn Together admin team. Please allow up to one hour for a response.'
        show_setup_link = False
    elif user.status == 'approved':
        if user.password == hash_password(''):
            status_text = 'Your application has been approved. Your account is ready. Set your password now using the approved email address.'
            show_setup_link = True
        else:
            status_text = 'Your application has been approved. Return to the login page and sign in using your approved email.'
            show_setup_link = False
    elif user.status == 'denied':
        status_text = 'Your application has been denied. Please contact the admin for details or to request a review.'
        show_setup_link = False
    else:
        status_text = 'Your application is being processed. Please use the email you applied with and check again shortly.'
        show_setup_link = False

    return render_template('application_status.html', config=config, status_text=status_text, show_setup_link=show_setup_link, email=email)

@app.route('/setup-password', methods=['GET', 'POST'])
def setup_password():
    email = request.args.get('email', '').strip().lower()
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No approved account found for this email.', 'error')
            return redirect(url_for('application_status', email=email))
        if user.status != 'approved' and user.password != hash_password(''):
            flash('This account is not ready for password setup yet.', 'error')
            return redirect(url_for('application_status', email=email))
        if user.status != 'approved' and user.password == hash_password(''):
            user.status = 'approved'
            db.session.commit()
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('setup_password.html', email=email)
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('setup_password.html', email=email)
        user.password = hash_password(password)
        db.session.commit()
        flash('Your password has been set. You may now log in.', 'success')
        return redirect(url_for('login'))

    # Get active media for the page
    login_media = SiteMedia.query.filter_by(media_type='login_image', is_active=True).first()
    return render_template('setup_password.html', email=email, login_media=login_media)

@app.route('/parent-setup-password/<token>', methods=['GET', 'POST'])
def parent_setup_password(token):
    parent = User.query.filter_by(password_reset_token=token, role='parent').first()
    
    if not parent:
        flash('Invalid or expired setup link.', 'error')
        return redirect(url_for('login'))
    
    # Check if token is expired (24 hours)
    if parent.token_expiry and parent.token_expiry < datetime.utcnow():
        flash('Setup link has expired. Please contact the administrator.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('parent_setup_password.html', token=token)
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('parent_setup_password.html', token=token)
        
        # Set parent password and status
        parent.password = hash_password(password)
        parent.status = 'approved'
        parent.password_reset_token = None
        parent.token_expiry = None
        db.session.commit()
        
        flash('Your password has been set. You may now log in with your email.', 'success')
        return redirect(url_for('login'))
    
    # Get active media for the page
    login_media = SiteMedia.query.filter_by(media_type='login_image', is_active=True).first()
    return render_template('parent_setup_password.html', token=token, parent_email=parent.email, login_media=login_media)

    return render_template('setup_password.html', email=email)

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        role = request.form.get('role', 'student')
        parent_email = request.form.get('parent_email', '').strip().lower()
        parent_name = request.form.get('parent_name', '').strip()
        date_of_birth = request.form.get('date_of_birth', '').strip()
        previous_school = request.form.get('previous_school', '').strip()
        courses_interest = request.form.get('courses_interest', '').strip()
        cv_file = request.files.get('cv_file')
        cv_path = save_uploaded_file(cv_file, 'documents', ALLOWED_DOCUMENT_EXTENSIONS | {'pdf'}) if cv_file else None
        signup_media = SiteMedia.query.filter_by(media_type='signup_image', is_active=True).first()

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return render_template('register.html', signup_media=signup_media)

        user = User(
            name=name,
            email=email,
            password=hash_password(''),
            role=role,
            status='pending',
            date_of_birth=datetime.strptime(date_of_birth, '%Y-%m-%d').date() if date_of_birth else None,
            previous_school=previous_school if role == 'student' else None,
            courses_interest=courses_interest if role == 'student' else None,
            cv_path=cv_path if role == 'teacher' else None,
            parent_name=parent_name if role == 'student' else None,
            parent_email=parent_email if role == 'student' else None,
        )
        db.session.add(user)
        db.session.commit()

        if role == 'student' and parent_email:
            parent = User.query.filter_by(email=parent_email, role='parent').first()
            if parent:
                user.parent_id = parent.id
                db.session.commit()

        flash('Your application has been submitted. An admin will review it shortly.', 'success')
        return redirect(url_for('application_status', email=email))
    signup_media = SiteMedia.query.filter_by(media_type='signup_image', is_active=True).first()
    return render_template('register.html', signup_media=signup_media)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ─── DASHBOARD ──────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if user.role == 'student':
        enrollments = Enrollment.query.filter_by(student_id=user.id).all()
        courses = [e.course for e in enrollments]
        groups = GroupMember.query.filter_by(user_id=user.id).all()
        recent_activity = ActivityLog.query.filter_by(student_id=user.id).order_by(ActivityLog.timestamp.desc()).limit(5).all()
        progress_list = Progress.query.filter_by(student_id=user.id).all()
        completed = sum(1 for p in progress_list if p.progress_percent >= 100)
        return render_template('dashboard_student.html', courses=courses, groups=groups,
                               recent_activity=recent_activity, progress_list=progress_list,
                               completed=completed)

    elif user.role == 'teacher':
        my_courses = Course.query.filter_by(teacher_id=user.id).all()
        total_students = sum(len(c.enrollments) for c in my_courses)
        groups = Group.query.filter_by(created_by=user.id).all()
        recent_activity = ActivityLog.query.join(Course).filter(Course.teacher_id == user.id).order_by(ActivityLog.timestamp.desc()).limit(8).all()

        today = date.today()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        today_events = CalendarEvent.query.filter(
            CalendarEvent.user_id == user.id,
            CalendarEvent.start_at >= today_start,
            CalendarEvent.start_at <= today_end
        ).order_by(CalendarEvent.start_at).all()

        today_reminders = Notification.query.filter(
            Notification.user_id == user.id,
            Notification.kind == 'reminder',
            Notification.reminder_for >= today_start,
            Notification.reminder_for <= today_end
        ).order_by(Notification.reminder_for).all()

        return render_template('dashboard_teacher.html', courses=my_courses,
                               total_students=total_students, groups=groups,
                               recent_activity=recent_activity,
                               today_events=today_events,
                               today_reminders=today_reminders)

    elif user.role == 'parent':
        # Find linked students
        students = User.query.filter_by(parent_email=user.email).all()
        # Also find by parent_id
        students2 = User.query.filter_by(parent_id=user.id).all()
        all_students = list({s.id: s for s in students + students2}.values())
        student_data = []
        for s in all_students:
            enrollments = Enrollment.query.filter_by(student_id=s.id).all()
            progress_list = Progress.query.filter_by(student_id=s.id).all()
            avg_progress = sum(p.progress_percent for p in progress_list) / len(progress_list) if progress_list else 0
            attendance = Attendance.query.filter_by(student_id=s.id).all()
            att_rate = sum(1 for a in attendance if a.status == 'present') / len(attendance) * 100 if attendance else 0
            student_data.append({'user': s, 'courses': len(enrollments), 'avg_progress': round(avg_progress, 1), 'att_rate': round(att_rate, 1)})
        return render_template('dashboard_parent.html', student_data=student_data)

    elif user.role == 'admin':
        users = User.query.all()
        courses = Course.query.all()
        groups = Group.query.all()
        teachers = [u for u in users if u.role == 'teacher']
        students = [u for u in users if u.role == 'student']
        return render_template('dashboard_admin.html', users=users, courses=courses,
                               groups=groups, teachers=teachers, students=students)

    return redirect(url_for('index'))

# ─── COURSES ────────────────────────────────────────────────────────────────
@app.route('/courses')
def courses():
    user = get_current_user()
    all_courses = Course.query.all()
    enrolled_ids = []
    if user and user.role == 'student':
        enrolled_ids = [e.course_id for e in Enrollment.query.filter_by(student_id=user.id).all()]
    return render_template('courses.html', courses=all_courses, enrolled_ids=enrolled_ids)

@app.route('/courses/create', methods=['GET', 'POST'])
def create_course():
    user = get_current_user()
    if not user or user.role != 'teacher':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        level = request.form.get('level', 'beginner')
        thumbnail = request.form.get('thumbnail', '').strip()
        thumbnail_file = request.files.get('thumbnail_file')
        saved_thumbnail = save_uploaded_file(thumbnail_file, 'thumbnails', ALLOWED_IMAGE_EXTENSIONS)
        if saved_thumbnail:
            thumbnail = saved_thumbnail

        course = Course(title=title, description=description, teacher_id=user.id,
                        category=category, level=level, thumbnail=thumbnail)
        db.session.add(course)
        db.session.flush()

        # Auto-create course group
        group = Group(name=f"{title} - Class Group", course_id=course.id,
                      created_by=user.id, group_type='course')
        db.session.add(group)
        gm = GroupMember(group_id=group.id, user_id=user.id, role='admin')
        db.session.add(gm)
        db.session.commit()
        flash('Course created!', 'success')
        return redirect(url_for('course_detail', course_id=course.id))
    return render_template('create_course.html')

@app.route('/courses/<int:course_id>')
def course_detail(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    is_enrolled = False
    if user and user.role == 'student':
        is_enrolled = Enrollment.query.filter_by(student_id=user.id, course_id=course_id).first() is not None
    contents = CourseContent.query.filter_by(course_id=course_id).order_by(CourseContent.order).all()
    lessons = ScheduledLesson.query.filter_by(course_id=course_id).order_by(ScheduledLesson.scheduled_at.asc()).all()
    progress = None
    if user and user.role == 'student':
        progress = Progress.query.filter_by(student_id=user.id, course_id=course_id).first()
    group = Group.query.filter_by(course_id=course_id).first()
    return render_template('course_detail.html', course=course, is_enrolled=is_enrolled,
                          contents=contents, progress=progress, group=group, lessons=lessons)

@app.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
def edit_course(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    if not user or user.role != 'teacher' or course.teacher_id != user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))

    if request.method == 'POST':
        course.title = request.form.get('title', '').strip()
        course.description = request.form.get('description', '').strip()
        course.category = request.form.get('category', '').strip()
        course.level = request.form.get('level', 'beginner')
        thumbnail = request.form.get('thumbnail', '').strip()
        thumbnail_file = request.files.get('thumbnail_file')
        saved_thumbnail = save_uploaded_file(thumbnail_file, 'thumbnails', ALLOWED_IMAGE_EXTENSIONS)
        if saved_thumbnail:
            # remove old thumbnail file if it was uploaded
            if course.thumbnail and course.thumbnail.startswith('uploads/'):
                try:
                    old_path = os.path.join('static', course.thumbnail)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
            course.thumbnail = saved_thumbnail
        elif thumbnail:
            course.thumbnail = thumbnail
        db.session.commit()
        flash('Course updated successfully.', 'success')
        return redirect(url_for('course_detail', course_id=course.id))

    return render_template('edit_course.html', course=course)

@app.route('/courses/<int:course_id>/delete', methods=['POST'])
def delete_course(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)

    if not user:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))

    is_authorized = user.role == 'admin' or (user.role == 'teacher' and course.teacher_id == user.id)
    if not is_authorized:
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course.id))

    if course.thumbnail and course.thumbnail.startswith('uploads/'):
        try:
            thumbnail_path = os.path.join('static', course.thumbnail)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
        except Exception:
            pass

    course_groups = Group.query.filter_by(course_id=course.id).all()
    group_ids = [g.id for g in course_groups]

    if group_ids:
        Message.query.filter(Message.group_id.in_(group_ids)).delete(synchronize_session=False)
        GroupMember.query.filter(GroupMember.group_id.in_(group_ids)).delete(synchronize_session=False)

    Group.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    CourseContent.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Enrollment.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Progress.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    ActivityLog.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Attendance.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    AttendanceSession.query.filter_by(course_id=course.id).delete(synchronize_session=False)

    db.session.delete(course)
    db.session.commit()

    flash('Course deleted successfully.', 'success')
    return redirect(url_for('courses'))

@app.route('/courses/<int:course_id>/enroll', methods=['POST'])
def enroll_course(course_id):
    user = get_current_user()
    if not user or user.role != 'student':
        flash('Only students can enroll.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))
    if not Enrollment.query.filter_by(student_id=user.id, course_id=course_id).first():
        db.session.add(Enrollment(student_id=user.id, course_id=course_id))
        db.session.add(Progress(student_id=user.id, course_id=course_id, progress_percent=0))
        # Auto-join course group
        group = Group.query.filter_by(course_id=course_id).first()
        if group and not GroupMember.query.filter_by(group_id=group.id, user_id=user.id).first():
            db.session.add(GroupMember(group_id=group.id, user_id=user.id, role='member'))
        db.session.commit()
        flash('Enrolled successfully!', 'success')
    return redirect(url_for('course_detail', course_id=course_id))


@app.route('/courses/<int:course_id>/lessons/schedule', methods=['GET', 'POST'])
def schedule_lesson(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    group = Group.query.filter_by(course_id=course.id).first()
    if not user or user.role not in ('teacher', 'student'):
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))
    if user.role == 'teacher':
        if course.teacher_id != user.id:
            flash('Access denied.', 'error')
            return redirect(url_for('course_detail', course_id=course_id))
    else:
        if not group or not GroupMember.query.filter_by(group_id=group.id, user_id=user.id).first():
            flash('Access denied.', 'error')
            return redirect(url_for('course_detail', course_id=course_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        meet_link = request.form.get('meet_link', '').strip()
        scheduled_at = request.form.get('scheduled_at', '').strip()
        notify_group = request.form.get('notify_group') == 'on'

        if not title or not meet_link:
            flash('Title and meeting link are required.', 'error')
            return render_template('schedule_lesson.html', course=course)

        if not meet_link.startswith('http'):
            flash('Please enter a valid link starting with http or https.', 'error')
            return render_template('schedule_lesson.html', course=course)

        poster_url = None
        poster_file = request.files.get('poster_file')
        if poster_file and poster_file.filename:
            saved_poster = save_uploaded_file(poster_file, 'lesson_posters', ALLOWED_IMAGE_EXTENSIONS)
            if saved_poster:
                poster_url = saved_poster
            else:
                flash('Please upload a valid poster image (png, jpg, jpeg, gif, webp, avif).', 'error')
                return render_template('schedule_lesson.html', course=course)

        scheduled_dt = None
        if scheduled_at:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_at)
            except ValueError:
                flash('Invalid date and time.', 'error')
                return render_template('schedule_lesson.html', course=course)

        lesson = ScheduledLesson(
            course_id=course.id,
            teacher_id=user.id,
            title=title,
            description=description or None,
            meet_link=meet_link,
            poster_url=poster_url,
            scheduled_at=scheduled_dt,
            is_active=True,
        )
        db.session.add(lesson)
        db.session.flush()

        if notify_group:
            group = Group.query.filter_by(course_id=course.id).first()
            if group:
                time_str = (scheduled_dt.strftime('%B %d at %I:%M %p') if scheduled_dt else 'soon')
                msg_text = (
                    f"Live lesson scheduled: {title}\n"
                    f"Time: {time_str}\n"
                    f"Join here: {meet_link}"
                )
                db.session.add(Message(
                    group_id=group.id,
                    sender_id=user.id,
                    message=msg_text,
                ))

        db.session.commit()
        flash('Lesson scheduled successfully.', 'success')
        return redirect(url_for('course_detail', course_id=course.id))

    return render_template('schedule_lesson.html', course=course)


@app.route('/courses/<int:course_id>/lessons/<int:lesson_id>/delete', methods=['POST'])
def delete_scheduled_lesson(course_id, lesson_id):
    user = get_current_user()
    lesson = ScheduledLesson.query.get_or_404(lesson_id)
    if not user or (user.role != 'teacher' and user.role != 'admin'):
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))
    db.session.delete(lesson)
    db.session.commit()
    flash('Lesson removed.', 'success')
    return redirect(url_for('course_detail', course_id=course_id))


@app.route('/courses/<int:course_id>/lessons/<int:lesson_id>/toggle', methods=['POST'])
def toggle_scheduled_lesson(course_id, lesson_id):
    user = get_current_user()
    lesson = ScheduledLesson.query.get_or_404(lesson_id)
    if not user or (user.role != 'teacher' and user.role != 'admin'):
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))
    lesson.is_active = not lesson.is_active
    db.session.commit()
    flash('Lesson visibility updated.', 'success')
    return redirect(url_for('course_detail', course_id=course_id))


@app.route('/courses/<int:course_id>/content/add', methods=['GET', 'POST'])
def add_content(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    if not user or user.role != 'teacher' or course.teacher_id != user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content_type = request.form.get('content_type', 'note')
        content_url = request.form.get('content_url', '').strip()
        body = request.form.get('body', '').strip()
        content_file = request.files.get('content_file')
        if content_type == 'video' and content_file and content_file.filename:
            saved_video = save_uploaded_file(content_file, 'videos', ALLOWED_VIDEO_EXTENSIONS)
            if saved_video:
                content_url = url_for('static', filename=saved_video)
        elif content_type == 'presentation' and content_file and content_file.filename:
            saved_presentation = save_uploaded_file(content_file, 'presentations', ALLOWED_PRESENTATION_EXTENSIONS)
            if saved_presentation:
                content_url = url_for('static', filename=saved_presentation)
        elif content_type == 'document' and content_file and content_file.filename:
            saved_document = save_uploaded_file(content_file, 'documents', ALLOWED_DOCUMENT_EXTENSIONS)
            if saved_document:
                content_url = url_for('static', filename=saved_document)
        if content_type == 'video' and not content_url:
            flash('Please provide a video URL or upload a video file.', 'error')
            return render_template('add_content.html', course=course)
        if content_type == 'presentation' and not content_url:
            flash('Please provide a presentation URL or upload a presentation file.', 'error')
            return render_template('add_content.html', course=course)
        if content_type == 'document' and not content_url:
            flash('Please provide a document URL or upload a document file.', 'error')
            return render_template('add_content.html', course=course)

        order = CourseContent.query.filter_by(course_id=course_id).count() + 1
        content = CourseContent(course_id=course_id, title=title, content_type=content_type,
                                content_url=content_url, body=body, order=order)
        db.session.add(content)
        db.session.commit()
        flash('Content added!', 'success')
        return redirect(url_for('course_detail', course_id=course_id))
    return render_template('add_content.html', course=course)

@app.route('/content/<int:content_id>/view')
def view_content(content_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    content = CourseContent.query.get_or_404(content_id)
    # Log activity
    if user.role == 'student':
        log = ActivityLog(student_id=user.id, course_id=content.course_id,
                          content_id=content_id, action='viewed')
        db.session.add(log)
        # Update progress
        total = CourseContent.query.filter_by(course_id=content.course_id).count()
        viewed = ActivityLog.query.filter_by(student_id=user.id, course_id=content.course_id).distinct(ActivityLog.content_id).count()
        progress = Progress.query.filter_by(student_id=user.id, course_id=content.course_id).first()
        if progress and total > 0:
            progress.progress_percent = min(int((viewed / total) * 100), 100)
        db.session.commit()
    course = Course.query.get(content.course_id)
    all_contents = CourseContent.query.filter_by(course_id=content.course_id).order_by(CourseContent.order).all()
    return render_template('view_content.html', content=content, course=course, all_contents=all_contents)

@app.route('/content/<int:content_id>/delete', methods=['POST'])
def delete_content(content_id):
    user = get_current_user()
    content = CourseContent.query.get_or_404(content_id)
    course = Course.query.get_or_404(content.course_id)
    if not user or user.role != 'teacher' or course.teacher_id != user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('course_detail', course_id=course.id))

    if content.content_url and content.content_url.startswith(url_for('static', filename='')):
        # preserve remote URLs; delete only local uploads
        local_path = content.content_url.replace(url_for('static', filename=''), '')
        absolute_path = os.path.join(app.root_path, 'static', local_path)
        if os.path.exists(absolute_path):
            try:
                os.remove(absolute_path)
            except OSError:
                pass
    db.session.delete(content)
    db.session.commit()
    flash('Module removed successfully.', 'success')
    return redirect(url_for('course_detail', course_id=course.id))

# ─── GROUPS ─────────────────────────────────────────────────────────────────
@app.route('/groups')
def groups():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    my_group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=user.id).all()]
    my_groups = Group.query.filter(Group.id.in_(my_group_ids)).all()
    public_groups = Group.query.filter(~Group.id.in_(my_group_ids)).limit(10).all()
    return render_template('groups.html', my_groups=my_groups, public_groups=public_groups)

@app.route('/groups/create', methods=['GET', 'POST'])
def create_group():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        group_type = 'student' if user.role == 'student' else 'teacher'
        group = Group(name=name, description=description, created_by=user.id, group_type=group_type)
        db.session.add(group)
        db.session.flush()
        db.session.add(GroupMember(group_id=group.id, user_id=user.id, role='admin'))
        db.session.commit()
        flash('Group created!', 'success')
        return redirect(url_for('group_detail', group_id=group.id))
    return render_template('create_group.html')

@app.route('/groups/<int:group_id>/avatar', methods=['POST'])
def update_group_avatar(group_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    group = Group.query.get_or_404(group_id)
    can_manage = user.role == 'admin' or group.created_by == user.id or (user.role == 'teacher' and group.group_type in {'course', 'teacher'})
    if not can_manage:
        flash('Only the teacher or admin can update this group picture.', 'error')
        return redirect(url_for('group_detail', group_id=group.id))

    avatar_file = request.files.get('group_avatar')
    saved_path = save_uploaded_file(avatar_file, 'group_avatars', ALLOWED_IMAGE_EXTENSIONS)
    if saved_path:
        if group.avatar:
            try:
                old_path = os.path.join('static', group.avatar)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                pass
        group.avatar = saved_path
        db.session.commit()
        flash('Group picture updated!', 'success')
    else:
        flash('Please upload a valid image file.', 'error')
    return redirect(url_for('group_detail', group_id=group.id))

@app.route('/groups/<int:group_id>')
def group_detail(group_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    group = Group.query.get_or_404(group_id)
    is_member = GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first() is not None
    all_messages = Message.query.filter_by(group_id=group_id).order_by(Message.timestamp.asc()).limit(50).all()
    messages = [m for m in all_messages if message_is_visible(m, user.id)]
    members = GroupMember.query.filter_by(group_id=group_id).all()
    my_group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=user.id).all()]
    other_group_ids = [gid for gid in my_group_ids if gid != group_id]
    my_groups = Group.query.filter(Group.id.in_(other_group_ids)).limit(6).all() if other_group_ids else []
    group_files = []
    for msg in messages:
        if msg.attachment_url:
            file_name = msg.attachment_name or os.path.basename(msg.attachment_url)
            group_files.append({
                'url': build_static_url(msg.attachment_url),
                'name': file_name,
                'icon_label': attachment_icon_label(file_name, msg.attachment_type),
                'icon_class': attachment_icon_class(file_name, msg.attachment_type),
                'meta': attachment_meta_label(file_name, msg.attachment_type),
            })
    return render_template('group_detail.html', group=group, is_member=is_member,
                           messages=messages, members=members, group_files=group_files, my_groups=my_groups)

@app.route('/groups/<int:group_id>/join', methods=['POST'])
def join_group(group_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    if not GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first():
        db.session.add(GroupMember(group_id=group_id, user_id=user.id, role='member'))
        db.session.commit()
        flash('Joined group!', 'success')
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/groups/<int:group_id>/leave', methods=['POST'])
def leave_group(group_id):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    membership = GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first()
    if membership:
        db.session.delete(membership)
        db.session.commit()
        flash('You left the group.', 'success')
    else:
        flash('You are not a member of this group.', 'warning')

    return redirect(url_for('dashboard'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')
    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Please enter your email address.', 'warning')
        return render_template('forgot_password.html')
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('If an account with that email exists, you will receive instructions.', 'info')
        return render_template('forgot_password.html')
    # prepare questions based on role
    role = user.role or 'student'
    questions = []
    if role == 'student' or role == 'parent':
        questions = [
            {'key': 'email', 'label': 'Email'},
            {'key': 'date_of_birth', 'label': 'Date of birth (YYYY-MM-DD)'},
            {'key': 'previous_school', 'label': 'Former school'},
            {'key': 'courses_interest', 'label': 'Courses of interest'},
        ]
    elif role == 'teacher':
        questions = [
            {'key': 'email', 'label': 'Email'},
            {'key': 'courses_teaching', 'label': 'Name of a course you teach'},
            {'key': 'date_of_birth', 'label': 'Date of birth (YYYY-MM-DD)'},
            {'key': 'two_students', 'label': 'Two students in any of your courses (comma separated)'}
        ]
    else:
        # admin or other roles: ask basic checks
        questions = [
            {'key': 'email', 'label': 'Email'},
            {'key': 'date_of_birth', 'label': 'Date of birth (YYYY-MM-DD)'},
            {'key': 'previous_school', 'label': 'Former school'},
        ]
    return render_template('forgot_password_questions.html', user_id=user.id, role=role, questions=questions)


@app.route('/forgot-password/verify', methods=['POST'])
def forgot_password_verify():
    user_id = request.form.get('user_id')
    if not user_id:
        flash('Invalid request.', 'error')
        return redirect(url_for('forgot_password'))
    user = User.query.filter_by(id=int(user_id)).first()
    if not user:
        flash('Invalid request.', 'error')
        return redirect(url_for('forgot_password'))
    role = user.role or 'student'
    # verify answers against authoritative records
    # email is always included and must match
    email_input = (request.form.get('email') or '').strip().lower()
    if email_input != (user.email or '').lower():
        flash('Answers did not match our records.', 'error')
        return redirect(url_for('forgot_password'))

    # date of birth check
    dob_input = request.form.get('date_of_birth')
    dob = parse_date_input(dob_input)
    if user.date_of_birth:
        if not dob or user.date_of_birth != dob:
            flash('Answers did not match our records.', 'error')
            return redirect(url_for('forgot_password'))

    # role-specific authoritative checks
    if role in ('student', 'parent'):
        # previous school must match stored value if present
        prev_input = (request.form.get('previous_school') or '').strip().lower()
        stored_prev = (user.previous_school or '').strip().lower()
        if stored_prev:
            if not prev_input or prev_input != stored_prev:
                flash('Answers did not match our records.', 'error')
                return redirect(url_for('forgot_password'))

        # courses of interest: check against enrollments and stored courses_interest
        ci_input = (request.form.get('courses_interest') or '').strip().lower()
        matched_course = False
        # check explicit enrollments for the user
        enrolls = Enrollment.query.filter_by(student_id=user.id).all()
        for en in enrolls:
            if en.course and ci_input and ci_input in (en.course.title or '').lower():
                matched_course = True
                break
        # also check stored free-text courses_interest
        stored_ci = (user.courses_interest or '').strip().lower()
        if not matched_course and stored_ci and ci_input:
            if ci_input in stored_ci or stored_ci in ci_input:
                matched_course = True
        if stored_ci and not matched_course:
            flash('Answers did not match our records.', 'error')
            return redirect(url_for('forgot_password'))

    elif role == 'teacher':
        # verify course taught
        course_input = (request.form.get('courses_teaching') or '').strip().lower()
        taught_courses = Course.query.filter_by(teacher_id=user.id).all()
        if taught_courses:
            if not course_input or not any(course_input in (c.title or '').lower() for c in taught_courses):
                flash('Answers did not match our records.', 'error')
                return redirect(url_for('forgot_password'))

        # verify two students: must match enrolled students in teacher's courses
        students_input = (request.form.get('two_students') or '').strip()
        if students_input:
            names = [n.strip().lower() for n in students_input.split(',') if n.strip()]
            if len(names) < 2:
                flash('Please provide two student names.', 'error')
                return redirect(url_for('forgot_password'))
            taught_course_ids = [c.id for c in taught_courses]
            if not taught_course_ids:
                flash('Answers did not match our records.', 'error')
                return redirect(url_for('forgot_password'))
            enrolls = Enrollment.query.filter(Enrollment.course_id.in_(taught_course_ids)).all()
            student_names = set((en.student.name or '').strip().lower() for en in enrolls if en.student)
            match_count = sum(1 for n in names if any(n == s or n in s or s in n for s in student_names))
            if match_count < 2:
                flash('Answers did not match our records.', 'error')
                return redirect(url_for('forgot_password'))

    else:
        # fallback checks for admin/other
        prev_input = (request.form.get('previous_school') or '').strip().lower()
        stored_prev = (user.previous_school or '').strip().lower()
        if stored_prev and prev_input != stored_prev:
            flash('Answers did not match our records.', 'error')
            return redirect(url_for('forgot_password'))

    # passed verification — render reset form
    return render_template('reset_password.html', user_id=user.id)


@app.route('/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    user_id = request.form.get('user_id')
    password = request.form.get('password')
    password_confirm = request.form.get('password_confirm')
    if not user_id or not password:
        flash('Invalid request.', 'error')
        return redirect(url_for('forgot_password'))
    if password != password_confirm:
        flash('Passwords do not match.', 'error')
        return render_template('reset_password.html', user_id=user_id)
    if not password_meets_policy(password):
        flash('Password must be at least 8 characters, include an uppercase letter and a special character.', 'error')
        return render_template('reset_password.html', user_id=user_id)
    user = User.query.filter_by(id=int(user_id)).first()
    if not user:
        flash('Invalid user.', 'error')
        return redirect(url_for('forgot_password'))
    user.password = hash_password(password)
    user.password_reset_token = None
    user.token_expiry = None
    db.session.commit()
    flash('Your password has been reset. You can now log in.', 'success')
    return redirect(url_for('login'))

@app.route('/groups/<int:group_id>/message', methods=['POST'])
def send_message(group_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    text = request.form.get('message', '').strip()
    if not text and not request.files.get('attachment'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Empty message'}), 400
        return redirect(url_for('group_detail', group_id=group_id))

    attachment = request.files.get('attachment')
    attachment_url = None
    attachment_type = None
    attachment_name = None
    attachment_mime = None
    if attachment and attachment.filename:
        attachment_url = save_uploaded_file(attachment, 'group_attachments', ALLOWED_IMAGE_EXTENSIONS.union(ALLOWED_VIDEO_EXTENSIONS, ALLOWED_PRESENTATION_EXTENSIONS))
        if attachment_url:
            attachment_type = attachment_type_for(attachment.filename)
            attachment_name = attachment.filename
            attachment_mime = attachment.mimetype

    msg = Message(group_id=group_id, sender_id=user.id, message=text or None,
                  attachment_type=attachment_type, attachment_url=attachment_url,
                  attachment_name=attachment_name, attachment_mime=attachment_mime)
    db.session.add(msg)
    db.session.commit()

    # Create MessageDelivery rows for group members (unread tracking / receipts)
    try:
        members = GroupMember.query.filter_by(group_id=group_id).all()
        for m in members:
            if m.user_id == user.id:
                continue
            md = MessageDelivery(message_id=msg.id, user_id=m.user_id)
            db.session.add(md)
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Create notifications for other group members (server-side, prevent duplicates)
    try:
        group = Group.query.get(group_id)
        notifications_to_add = []
        for m in members:
            if m.user_id == user.id:
                continue
            # Prevent duplicate notification for same recipient + message + kind
            exists = Notification.query.filter_by(user_id=m.user_id, message_id=msg.id, kind='group_message').first()
            if exists:
                continue
            title = f"New message in {group.name if group else 'Group'}"
            preview = (msg.message or '')
            if len(preview) > 240:
                preview = preview[:237] + '...'
            body = f"{user.name}: {preview}"
            link = url_for('group_detail', group_id=group_id) + f"#message-{msg.id}"
            n = Notification(
                user_id=m.user_id,
                sender_id=user.id,
                group_id=group_id,
                message_id=msg.id,
                title=title,
                body=body,
                link=link,
                kind='group_message',
            )
            notifications_to_add.append(n)
        if notifications_to_add:
            db.session.add_all(notifications_to_add)
            db.session.commit()
    except Exception:
        db.session.rollback()

    sender_identity = user_identity(user)
    # preserve any client-provided id for deduping optimistic render
    client_id = request.form.get('clientId') or request.form.get('client_id')
    message_payload = {
        'id': msg.id,
        'clientId': client_id,
        'sender': sender_identity['name'],
        'sender_initials': sender_identity['initials'],
        'sender_avatar': sender_identity['avatar_url'],
        'sender_color': sender_identity['color'],
        'sender_role': user.role if hasattr(user, 'role') else None,
        'message': msg.message,
        'attachment_url': build_static_url(msg.attachment_url),
        'attachment_type': msg.attachment_type,
        'attachment_name': msg.attachment_name,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'sender_id': user.id,
        'is_pinned': msg.is_pinned,
        'deleted_for_all': msg.deleted_for_all,
    }
    socketio.emit('group-message', {'groupId': group_id, 'message': message_payload}, room=f'group_{group_id}')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': message_payload})

    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/groups/<int:group_id>/messages/<int:message_id>/pin', methods=['POST'])
def pin_message(group_id, message_id):
    user = get_current_user()
    if not user:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))
    msg = Message.query.filter_by(id=message_id, group_id=group_id).first_or_404()
    if not can_manage_message(user, msg):
        flash('You cannot pin this message.', 'error')
        return redirect(url_for('group_detail', group_id=group_id))
    msg.is_pinned = not msg.is_pinned
    db.session.commit()
    flash('Message updated.', 'success')
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/groups/<int:group_id>/messages/<int:message_id>/delete', methods=['POST'])
def delete_message(group_id, message_id):
    user = get_current_user()
    if not user:
        flash('Please log in first.', 'error')
        return redirect(url_for('login'))
    msg = Message.query.filter_by(id=message_id, group_id=group_id).first_or_404()
    scope = request.args.get('scope', 'me')
    if scope == 'all':
        if not can_manage_message(user, msg):
            flash('You cannot delete this message for everyone.', 'error')
            return redirect(url_for('group_detail', group_id=group_id))
        msg.deleted_for_all = True
        MessageVisibility.query.filter_by(message_id=msg.id).delete(synchronize_session=False)
        db.session.commit()
        flash('Message deleted for everyone.', 'success')
        return redirect(url_for('group_detail', group_id=group_id))

    if msg.sender_id != user.id and not can_manage_message(user, msg):
        flash('You cannot delete this message for yourself.', 'error')
        return redirect(url_for('group_detail', group_id=group_id))
    if MessageVisibility.query.filter_by(message_id=msg.id, user_id=user.id).first() is None:
        visibility = MessageVisibility(message_id=msg.id, user_id=user.id)
        db.session.add(visibility)
        db.session.commit()
    flash('Message removed from your view.', 'success')
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/api/groups/<int:group_id>/messages')
def get_messages(group_id):
    after = request.args.get('after', 0, type=int)
    user = get_current_user()
    messages = Message.query.filter(Message.group_id == group_id, Message.id > after).order_by(Message.timestamp.asc()).all()
    visible_messages = [m for m in messages if message_is_visible(m, user.id if user else None)]
    return jsonify([{
        'id': m.id,
        'sender': m.sender.name,
        'sender_role': getattr(m.sender, 'role', None),
        'sender_initials': initials_for_name(m.sender.name),
        'sender_avatar': build_static_url(m.sender.avatar) if m.sender.avatar else None,
        'sender_color': user_identity(m.sender)['color'],
        'message': m.message,
        'attachment_url': build_static_url(m.attachment_url) if m.attachment_url else None,
        'attachment_type': m.attachment_type,
        'attachment_name': m.attachment_name,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'sender_id': m.sender_id,
        'is_pinned': m.is_pinned,
        'deleted_for_all': m.deleted_for_all,
    } for m in visible_messages])


@app.route('/api/groups/<int:group_id>/presence')
def get_group_presence(group_id):
    members = GroupMember.query.filter_by(group_id=group_id).all()
    users = []
    for member in members:
        if not member.user:
            continue
        users.append({
            'user_id': member.user.id,
            'user_name': member.user.name,
            'user_role': member.user.role,
        })
    return jsonify({'group_id': group_id, 'users': users})

# ─── NOTIFICATIONS & CALENDAR ───────────────────────────────────────────
@app.route('/notifications')
def notifications():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    notification_items = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).all()
    notifications = []
    for item in notification_items:
        notifications.append({
            'id': item.id,
            'title': item.title,
            'body': item.body,
            'link': item.link,
            'kind': item.kind,
            'channel': 'Calendar' if item.kind == 'reminder' else 'General',
            'time': item.created_at.strftime('%b %d, %Y %H:%M'),
            'unread': not item.is_read,
            'reminder_for': item.reminder_for.strftime('%b %d, %Y %H:%M') if item.reminder_for else None,
        })

    selected_id = request.args.get('notification_id', type=int)
    selected = None
    if selected_id:
        selected = next((item for item in notifications if item['id'] == selected_id), None)
    if not selected and notifications:
        selected = notifications[0]

    if selected:
        target = Notification.query.get(selected['id'])
        if target and not target.is_read:
            target.is_read = True
            db.session.commit()

    return render_template('notifications.html', notifications=notifications, selected=selected)


@app.route('/api/notifications')
def api_notifications():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    limit = request.args.get('limit', 40, type=int)
    items = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(limit).all()
    data = []
    for it in items:
        data.append({
            'id': it.id,
            'title': it.title,
            'body': it.body,
            'link': it.link or it.target_url,
            'kind': it.kind,
            'is_read': bool(it.is_read),
            'created_at': it.created_at.isoformat() if it.created_at else None,
            'sender_id': it.sender_id,
            'group_id': it.group_id,
            'message_id': it.message_id,
        })
    unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return jsonify({'notifications': data, 'unread_count': unread})


@app.route('/api/notifications/<int:notif_id>/mark_read', methods=['POST'])
def api_mark_notification_read(notif_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    n = Notification.query.filter_by(id=notif_id, user_id=user.id).first()
    if not n:
        return jsonify({'error': 'Not found'}), 404
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.utcnow()
        db.session.commit()
    return jsonify({'success': True})


@app.route('/api/notifications/mark_all_read', methods=['POST'])
def api_mark_all_read():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        Notification.query.filter_by(user_id=user.id, is_read=False).update({'is_read': True, 'read_at': datetime.utcnow()}, synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Failed to mark all read'}), 500
    return jsonify({'success': True})

@app.route('/calendar', methods=['GET', 'POST'])
def calendar_view():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    requested_date = request.args.get('date')
    try:
        selected_date = datetime.strptime(requested_date, '%Y-%m-%d').date() if requested_date else date.today()
    except ValueError:
        selected_date = date.today()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        location = request.form.get('location', '').strip()
        event_type = request.form.get('event_type', 'goal')
        start_at_raw = request.form.get('start_at', '').strip()
        end_at_raw = request.form.get('end_at', '').strip()
        reminder_at_raw = request.form.get('reminder_at', '').strip()

        if not title or not start_at_raw:
            flash('Please provide a title and start time for your event.', 'error')
            return redirect(url_for('calendar_view', date=selected_date.strftime('%Y-%m-%d')))

        try:
            start_at = datetime.fromisoformat(start_at_raw)
        except ValueError:
            flash('Start date/time is invalid.', 'error')
            return redirect(url_for('calendar_view', date=selected_date.strftime('%Y-%m-%d')))

        end_at = None
        if end_at_raw:
            try:
                end_at = datetime.fromisoformat(end_at_raw)
            except ValueError:
                flash('End date/time is invalid.', 'error')
                return redirect(url_for('calendar_view', date=selected_date.strftime('%Y-%m-%d')))

        reminder_at = None
        if reminder_at_raw:
            try:
                reminder_at = datetime.fromisoformat(reminder_at_raw)
            except ValueError:
                flash('Reminder date/time is invalid.', 'error')
                return redirect(url_for('calendar_view', date=selected_date.strftime('%Y-%m-%d')))

        event = CalendarEvent(
            user_id=user.id,
            title=title,
            description=description,
            location=location,
            event_type=event_type,
            start_at=start_at,
            end_at=end_at,
            reminder_at=reminder_at,
        )
        db.session.add(event)

        if reminder_at:
            notification_title = f'Reminder: {title}'
            notification_body = description or f'Your event "{title}" is scheduled for {start_at.strftime("%b %d %Y %I:%M %p")}.'
            db.session.add(Notification(
                user_id=user.id,
                title=notification_title,
                body=notification_body,
                link=url_for('calendar_view', date=start_at.date().strftime('%Y-%m-%d')),
                kind='reminder',
                reminder_for=reminder_at,
            ))

        db.session.commit()
        flash('Event scheduled successfully.', 'success')
        return redirect(url_for('calendar_view', date=start_at.date().strftime('%Y-%m-%d')))

    month_start = selected_date.replace(day=1)
    if selected_date.month == 12:
        month_end = selected_date.replace(year=selected_date.year + 1, month=1, day=1)
    else:
        month_end = selected_date.replace(month=selected_date.month + 1, day=1)

    calendar_events = CalendarEvent.query.filter(
        CalendarEvent.user_id == user.id,
        CalendarEvent.start_at >= month_start,
        CalendarEvent.start_at < month_end
    ).order_by(CalendarEvent.start_at).all()

    month_days = calendar.monthcalendar(selected_date.year, selected_date.month)
    day_events = {}
    for event in calendar_events:
        day_events.setdefault(event.start_at.day, []).append({
            'id': event.id,
            'title': event.title,
            'time': event.start_at.strftime('%H:%M'),
            'date': event.start_at.date(),
            'location': event.location,
            'type': event.event_type,
            'description': event.description,
            'end_at': event.end_at.strftime('%H:%M') if event.end_at else None,
            'reminder_for': event.reminder_at.strftime('%b %d %Y %I:%M %p') if event.reminder_at else None,
        })

    selected_events = day_events.get(selected_date.day, [])
    prev_date = (selected_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_date = (selected_date.replace(day=28) + timedelta(days=4)).replace(day=1)

    return render_template(
        'calendar.html',
        selected_date=selected_date,
        month_days=month_days,
        day_events=day_events,
        selected_events=selected_events,
        month_label=selected_date.strftime('%B %Y'),
        prev_date=prev_date,
        next_date=next_date,
        today_date=date.today(),
    )

# ─── ANALYTICS ──────────────────────────────────────────────────────────────
@app.route('/analytics/<int:course_id>')
def analytics(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    if not user or (user.role == 'teacher' and course.teacher_id != user.id):
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    enrollments = Enrollment.query.filter_by(course_id=course_id).all()
    students = [User.query.get(e.student_id) for e in enrollments]
    progress_data = []
    for s in students:
        prog = Progress.query.filter_by(student_id=s.id, course_id=course_id).first()
        activity = ActivityLog.query.filter_by(student_id=s.id, course_id=course_id).count()
        attendance = Attendance.query.filter_by(student_id=s.id, course_id=course_id).all()
        att_rate = sum(1 for a in attendance if a.status == 'present') / len(attendance) * 100 if attendance else 0
        progress_data.append({
            'student': s,
            'progress': prog.progress_percent if prog else 0,
            'activity': activity,
            'attendance': round(att_rate, 1)
        })

    total_contents = CourseContent.query.filter_by(course_id=course_id).count()
    avg_progress = sum(p['progress'] for p in progress_data) / len(progress_data) if progress_data else 0
    active_students = sum(1 for p in progress_data if p['activity'] > 0)
    completion_rate = sum(1 for p in progress_data if p['progress'] >= 100) / len(progress_data) * 100 if progress_data else 0

    return render_template('analytics.html', course=course, progress_data=progress_data,
                           avg_progress=round(avg_progress, 1), active_students=active_students,
                           completion_rate=round(completion_rate, 1), total_students=len(students))

# ─── ATTENDANCE ──────────────────────────────────────────────────────────────
@app.route('/attendance/<int:course_id>')
def attendance(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    if not user or (user.role == 'teacher' and course.teacher_id != user.id):
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    sessions = AttendanceSession.query.filter_by(course_id=course_id).order_by(AttendanceSession.date.desc()).all()
    enrollments = Enrollment.query.filter_by(course_id=course_id).all()
    students = [User.query.get(e.student_id) for e in enrollments]
    attendance_data = []
    for s in students:
        records = Attendance.query.filter_by(student_id=s.id, course_id=course_id).all()
        present = sum(1 for r in records if r.status == 'present')
        total = len(records)
        attendance_data.append({'student': s, 'present': present, 'total': total,
                                'rate': round(present / total * 100, 1) if total else 0})
    return render_template('attendance.html', course=course, sessions=sessions,
                           students=students, attendance_data=attendance_data)

@app.route('/attendance/<int:course_id>/session/create', methods=['POST'])
def create_session(course_id):
    user = get_current_user()
    course = Course.query.get_or_404(course_id)
    if not user or user.role != 'teacher' or course.teacher_id != user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    session_name = request.form.get('session_name', f'Session {date.today()}')
    att_session = AttendanceSession(course_id=course_id, name=session_name, date=date.today(), created_by=user.id)
    db.session.add(att_session)
    db.session.commit()
    # Mark all enrolled students absent by default
    for e in Enrollment.query.filter_by(course_id=course_id).all():
        db.session.add(Attendance(student_id=e.student_id, course_id=course_id,
                                  session_id=att_session.id, status='absent'))
    db.session.commit()
    flash('Session created!', 'success')
    return redirect(url_for('attendance', course_id=course_id))

@app.route('/attendance/mark/<int:session_id>/<int:student_id>/<status>', methods=['POST'])
def mark_attendance(session_id, student_id, status):
    user = get_current_user()
    if not user or user.role != 'teacher':
        return jsonify({'error': 'Access denied'}), 403
    record = Attendance.query.filter_by(session_id=session_id, student_id=student_id).first()
    if record:
        record.status = status
        db.session.commit()
    return jsonify({'success': True})

# ─── PARENT ROUTES ──────────────────────────────────────────────────────────
@app.route('/parent/student/<int:student_id>')
def parent_student_detail(student_id):
    user = get_current_user()
    if not user or user.role != 'parent':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    student = User.query.get_or_404(student_id)
    if student.parent_email != user.email and student.parent_id != user.id:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    enrollments = Enrollment.query.filter_by(student_id=student_id).all()
    courses = [e.course for e in enrollments]
    progress_list = Progress.query.filter_by(student_id=student_id).all()
    progress_map = {p.course_id: p.progress_percent for p in progress_list}
    attendance_data = []
    for c in courses:
        records = Attendance.query.filter_by(student_id=student_id, course_id=c.id).all()
        present = sum(1 for r in records if r.status == 'present')
        total = len(records)
        attendance_data.append({'course': c, 'rate': round(present/total*100,1) if total else 0})
    recent = ActivityLog.query.filter_by(student_id=student_id).order_by(ActivityLog.timestamp.desc()).limit(10).all()
    return render_template('parent_student.html', student=student, courses=courses,
                           progress_map=progress_map, attendance_data=attendance_data, recent=recent)

# ─── ADMIN ROUTES ───────────────────────────────────────────────────────────
@app.route('/admin/users')
def admin_users():
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/application-page', methods=['GET', 'POST'])
def admin_application_page():
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    config = ApplicationPageConfig.query.first()
    if not config:
        config = ApplicationPageConfig(
            headline='Application status',
            subtitle='Track your application and next steps for Learn Together.',
            main_text='Your application status is visible on this page. If your account is approved, you may set your password and sign in using the approved email.',
            details_text='Admin can update this page with the latest announcements, guidance, or application reviews.',
            promo_text='Learn Together helps students, teachers, and parents stay connected and make progress with every step.',
            footer_text='Please allow up to one hour for a review. The admin may approve earlier based on application details.',
        )
        db.session.add(config)
        db.session.commit()

    if request.method == 'POST':
        config.headline = request.form.get('headline', config.headline).strip()
        config.subtitle = request.form.get('subtitle', config.subtitle).strip()
        config.main_text = request.form.get('main_text', config.main_text).strip()
        config.details_text = request.form.get('details_text', config.details_text).strip()
        config.promo_text = request.form.get('promo_text', config.promo_text).strip()
        config.footer_text = request.form.get('footer_text', config.footer_text).strip()

        banner_file = request.files.get('banner_image')
        if banner_file and banner_file.filename:
            saved_path = save_uploaded_file(banner_file, 'application_page', ALLOWED_IMAGE_EXTENSIONS)
            if saved_path:
                config.banner_image = saved_path

        db.session.commit()
        flash('Application page content updated.', 'success')
        return redirect(url_for('admin_application_page'))

    return render_template('admin_application_page.html', config=config)

@app.route('/admin/users/<int:user_id>/review', methods=['POST'])
def review_user(user_id):
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    applicant = User.query.get_or_404(user_id)
    action = request.form.get('action', 'approve')

    if action == 'deny':
        applicant.status = 'denied'
        applicant.password = hash_password('')
        db.session.commit()
        flash(f'{applicant.name} was denied.', 'info')
    else:
        applicant.status = 'approved'
        applicant.password = hash_password('')
        
        # If student with parent email, create parent account
        if applicant.role == 'student' and applicant.parent_email:
            parent_email = applicant.parent_email.lower().strip()
            
            # Check if parent already exists
            parent = User.query.filter_by(email=parent_email, role='parent').first()
            
            if not parent:
                # Create new parent account
                parent = User(
                    name=applicant.parent_name or 'Parent',
                    email=parent_email,
                    password=hash_password(''),
                    role='parent',
                    status='pending'  # Will be activated after setting password
                )
                db.session.add(parent)
                db.session.flush()  # Get the ID
            
            # Link student to parent
            applicant.parent_id = parent.id
            
            # Generate token for parent to set password
            token = secrets.token_urlsafe(32)
            parent.password_reset_token = token
            parent.token_expiry = datetime.utcnow() + timedelta(hours=24)
            
            # TODO: Send email to parent with setup link
            # For now, just show the link in the flash message
            setup_link = url_for('parent_setup_password', token=token, _external=True)
            flash(f'{applicant.name} was approved. Parent account created for {parent_email}. Share this setup link: {setup_link}', 'success')
        else:
            flash(f'{applicant.name} was approved.', 'success')
        
        db.session.commit()

    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    u = User.query.get_or_404(user_id)
    if u.id == user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_users'))

    backup_owner = User.query.filter_by(role='admin').filter(User.id != u.id).first()
    fallback_owner_id = backup_owner.id if backup_owner else user.id

    if u.role == 'student':
        Enrollment.query.filter_by(student_id=u.id).delete(synchronize_session=False)
        Progress.query.filter_by(student_id=u.id).delete(synchronize_session=False)
        Attendance.query.filter_by(student_id=u.id).delete(synchronize_session=False)
        ActivityLog.query.filter_by(student_id=u.id).delete(synchronize_session=False)
        GroupMember.query.filter_by(user_id=u.id).delete(synchronize_session=False)
        Message.query.filter_by(sender_id=u.id).delete(synchronize_session=False)
    else:
        Course.query.filter_by(teacher_id=u.id).update({'teacher_id': fallback_owner_id}, synchronize_session=False)
        Group.query.filter_by(created_by=u.id).update({'created_by': fallback_owner_id}, synchronize_session=False)
        GroupMember.query.filter_by(user_id=u.id).delete(synchronize_session=False)
        Message.query.filter_by(sender_id=u.id).delete(synchronize_session=False)

    User.query.filter_by(parent_id=u.id).update({'parent_id': None}, synchronize_session=False)
    db.session.delete(u)
    db.session.commit()
    flash('User deleted.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/courses')
def admin_courses():
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    courses = Course.query.all()
    return render_template('admin_courses.html', courses=courses)

# ─── ADMIN MEDIA MANAGEMENT ────────────────────────────────────────────────────
@app.route('/admin/media')
def admin_media():
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    media = SiteMedia.query.order_by(SiteMedia.uploaded_at.desc()).all()
    login_images = SiteMedia.query.filter_by(media_type='login_image').all()
    signup_images = SiteMedia.query.filter_by(media_type='signup_image').all()
    landing_videos = SiteMedia.query.filter_by(media_type='landing_video').all()
    return render_template('admin_media.html', media=media, login_images=login_images, signup_images=signup_images, landing_videos=landing_videos)

@app.route('/admin/media/upload', methods=['POST'])
def admin_media_upload():
    user = get_current_user()
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    media_type = request.form.get('media_type')
    if not media_type or media_type not in ['login_image', 'signup_image', 'landing_video']:
        return jsonify({'success': False, 'error': 'Invalid media type'}), 400
    
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    # Determine allowed extensions based on media type
    if media_type == 'landing_video':
        allowed_extensions = {'mp4', 'webm', 'mov', 'avi'}
    else:
        allowed_extensions = ALLOWED_IMAGE_EXTENSIONS
    
    # Save file
    subfolder = 'site_media'
    saved_path = save_uploaded_file(file, subfolder, allowed_extensions)
    
    if not saved_path:
        return jsonify({'success': False, 'error': 'File upload failed'}), 400
    
    # Deactivate previous media of this type
    SiteMedia.query.filter_by(media_type=media_type, is_active=True).update({'is_active': False})
    
    # Create new media record
    media = SiteMedia(
        media_type=media_type,
        file_path=saved_path,
        title=request.form.get('title', ''),
        description=request.form.get('description', ''),
        is_active=True,
        uploaded_by=user.id
    )
    db.session.add(media)
    db.session.commit()
    
    return jsonify({'success': True, 'media_id': media.id, 'file_path': saved_path})

@app.route('/admin/media/<int:media_id>/delete', methods=['POST'])
def admin_media_delete(media_id):
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('admin_media'))
    
    media = SiteMedia.query.get_or_404(media_id)
    
    # Delete file
    try:
        file_path = os.path.join('static', media.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    
    db.session.delete(media)
    db.session.commit()
    flash(f'Media "{media.title or "Untitled"}" deleted.', 'success')
    return redirect(url_for('admin_media'))

@app.route('/admin/media/<int:media_id>/activate', methods=['POST'])
def admin_media_activate(media_id):
    user = get_current_user()
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    media = SiteMedia.query.get_or_404(media_id)
    media_type = media.media_type
    
    # Deactivate other media of same type
    SiteMedia.query.filter_by(media_type=media_type, is_active=True).update({'is_active': False})
    
    # Activate this one
    media.is_active = True
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'{media_type.replace("_", " ").title()} activated'})

# ─── ADMIN APPLICATIONS ────────────────────────────────────────────────────────
@app.route('/admin/applications')
def admin_applications():
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    # Get all applications (students, teachers, parents with pending/approved/denied status)
    applications = User.query.filter(User.role.in_(['student', 'teacher', 'parent'])).order_by(User.created_at.desc()).all()
    
    return render_template('admin_applications.html', applications=applications)

@app.route('/admin/applications/<int:app_id>')
def admin_application_detail(app_id):
    user = get_current_user()
    if not user or user.role != 'admin':
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    application = User.query.get_or_404(app_id)
    
    # Get parent info if this is a student
    parent = None
    if application.role == 'student' and application.parent_id:
        parent = User.query.get(application.parent_id)
    
    return render_template('admin_application_detail.html', application=application, parent=parent)

# ─── PROFILE ────────────────────────────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        user.name = request.form.get('name', user.name).strip()
        if user.role == 'student':
            user.parent_email = request.form.get('parent_email', '').strip()
            parent = User.query.filter_by(email=user.parent_email, role='parent').first()
            if parent:
                user.parent_id = parent.id
        # handle avatar upload
        if 'avatar' in request.files:
            avatar_file = request.files.get('avatar')
            saved_path = save_uploaded_file(avatar_file, 'avatars', ALLOWED_IMAGE_EXTENSIONS)
            if saved_path:
                # remove old avatar file if present
                if user.avatar:
                    try:
                        old_path = os.path.join('static', user.avatar)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    except Exception:
                        pass
                user.avatar = saved_path
            elif avatar_file and avatar_file.filename:
                flash('Unsupported avatar format. Please upload PNG, JPG, JPEG, GIF, WEBP, or AVIF.', 'error')
        db.session.commit()
        if not get_flashed_messages(with_categories=True):
            flash('Profile updated!', 'success')
    return render_template('profile.html', user=user)

# ─── SEED DATA ──────────────────────────────────────────────────────────────
def seed_notifications_for_user(user):
    if not user:
        return

    existing_titles = {n.title for n in Notification.query.filter_by(user_id=user.id).all()}
    now = datetime.utcnow()

    reminders = [
        {
            'title': 'Assignment due tomorrow',
            'body': 'Your Python project is due tomorrow. Review the rubric and submit before 11:59 PM.',
            'link': '/courses',
            'kind': 'reminder',
            'reminder_for': now + timedelta(days=1),
        },
        {
            'title': 'New group message',
            'body': 'A new message arrived in your class group. Open the conversation to reply.',
            'link': '/groups',
            'kind': 'notification',
            'reminder_for': None,
        },
        {
            'title': 'Attendance check',
            'body': 'Your attendance for today was recorded. Open the course page to review it.',
            'link': '/attendance/1',
            'kind': 'notification',
            'reminder_for': None,
        },
    ]

    for item in reminders:
        if item['title'] not in existing_titles:
            db.session.add(Notification(user_id=user.id, title=item['title'], body=item['body'], link=item['link'], kind=item['kind'], reminder_for=item['reminder_for']))

    db.session.commit()


def seed_data(create_demo_accounts=False):
    demo_emails = {
        'admin@learntogether.com',
        'teacher@learntogether.com',
        'student@learntogether.com',
        'sarah@learntogether.com',
        'parent@learntogether.com',
    }

    if create_demo_accounts:
        ensure_database_schema()

    if not create_demo_accounts:
        demo_users = User.query.filter(User.email.in_(list(demo_emails))).all()
        for user in demo_users:
            db.session.delete(user)
        db.session.commit()
        return

    defaults = [
        {
            'key': 'admin',
            'name': 'Admin User',
            'email': 'admin@learntogether.com',
            'password': 'admin123',
            'role': 'admin',
            'parent_email': None,
        },
        {
            'key': 'teacher',
            'name': 'Mr. Smith',
            'email': 'teacher@learntogether.com',
            'password': 'teacher123',
            'role': 'teacher',
            'parent_email': None,
        },
        {
            'key': 'student1',
            'name': 'John Doe',
            'email': 'student@learntogether.com',
            'password': 'student123',
            'role': 'student',
            'parent_email': 'parent@learntogether.com',
        },
        {
            'key': 'student2',
            'name': 'Sarah Johnson',
            'email': 'sarah@learntogether.com',
            'password': 'student123',
            'role': 'student',
            'parent_email': None,
        },
        {
            'key': 'parent',
            'name': 'Mrs. Johnson',
            'email': 'parent@learntogether.com',
            'password': 'parent123',
            'role': 'parent',
            'parent_email': None,
        },
    ]

    users = {}
    created_any = False

    for defaults_user in defaults:
        existing = User.query.filter_by(email=defaults_user['email']).first()
        expected_password = hash_password(defaults_user['password'])
        if not existing:
            existing = User(
                name=defaults_user['name'],
                email=defaults_user['email'],
                password=expected_password,
                role=defaults_user['role'],
                status='approved',
                parent_email=defaults_user['parent_email'],
            )
            db.session.add(existing)
            created_any = True
        else:
            if existing.name != defaults_user['name']:
                existing.name = defaults_user['name']
                created_any = True
            if existing.role != defaults_user['role']:
                existing.role = defaults_user['role']
                created_any = True
            if existing.password != expected_password:
                existing.password = expected_password
                created_any = True
            if existing.status != 'approved':
                existing.status = 'approved'
                created_any = True
            if existing.parent_email != defaults_user['parent_email']:
                existing.parent_email = defaults_user['parent_email']
                created_any = True
        users[defaults_user['key']] = existing

    if created_any:
        db.session.flush()

    if users.get('student1') and users.get('parent'):
        if users['student1'].parent_id != users['parent'].id:
            users['student1'].parent_id = users['parent'].id
            created_any = True

    admin = users.get('admin')
    teacher = users.get('teacher')
    student1 = users.get('student1')
    student2 = users.get('student2')
    parent = users.get('parent')

    if not Course.query.first():
        # Courses
        courses_data = [
            ('Python for Beginners', 'Learn Python from scratch with hands-on projects', 'Programming', 'beginner'),
            ('Mathematics Grade 10', 'Complete grade 10 math curriculum', 'Mathematics', 'intermediate'),
            ('Physics Fundamentals', 'Core physics concepts made easy', 'Science', 'beginner'),
            ('English Literature', 'Explore great works of English literature', 'English', 'intermediate'),
        ]
        courses = []
        for title, desc, cat, level in courses_data:
            c = Course(title=title, description=desc, teacher_id=teacher.id, category=cat, level=level)
            db.session.add(c)
            courses.append(c)

        db.session.flush()

        # Course contents
        for course in courses:
            for i in range(1, 5):
                db.session.add(CourseContent(
                    course_id=course.id, title=f'Module {i}: Introduction to {course.title}',
                    content_type='note', body=f'This is the content for module {i} of {course.title}.',
                    order=i
                ))
            # Auto course group
            group = Group(name=f"{course.title} - Class Group", course_id=course.id,
                          created_by=teacher.id, group_type='course',
                          description=f'Official discussion group for {course.title}')
            db.session.add(group)
            db.session.flush()
            db.session.add(GroupMember(group_id=group.id, user_id=teacher.id, role='admin'))

        db.session.flush()

        # Enroll students
        for course in courses[:3]:
            db.session.add(Enrollment(student_id=student1.id, course_id=course.id))
            db.session.add(Progress(student_id=student1.id, course_id=course.id,
                                    progress_percent=[75, 68, 42][courses.index(course) % 3]))
            db.session.add(Enrollment(student_id=student2.id, course_id=course.id))
            db.session.add(Progress(student_id=student2.id, course_id=course.id,
                                    progress_percent=[92, 85, 70][courses.index(course) % 3]))
            group = Group.query.filter_by(course_id=course.id).first()
            if group:
                db.session.add(GroupMember(group_id=group.id, user_id=student1.id, role='member'))
                db.session.add(GroupMember(group_id=group.id, user_id=student2.id, role='member'))

        db.session.flush()

        # Attendance sessions
        course1 = courses[0]
        session1 = AttendanceSession(course_id=course1.id, name='Session 1', date=date.today(), created_by=teacher.id)
        db.session.add(session1)
        db.session.flush()
        db.session.add(Attendance(student_id=student1.id, course_id=course1.id, session_id=session1.id, status='present'))
        db.session.add(Attendance(student_id=student2.id, course_id=course1.id, session_id=session1.id, status='present'))

        # Seed messages
        group = Group.query.filter_by(course_id=course1.id).first()
        if group:
            db.session.add(Message(group_id=group.id, sender_id=teacher.id,
                                   message='Welcome everyone! Feel free to ask any questions here.'))
            db.session.add(Message(group_id=group.id, sender_id=student1.id,
                                   message='Thank you! I have a question about loops.'))
            db.session.add(Message(group_id=group.id, sender_id=teacher.id,
                                   message="Great question! I'll explain with an example."))

    for user in [admin, teacher, student1, student2, parent]:
        if user:
            seed_notifications_for_user(user)

    db.session.commit()
    print("✅ Seed data created!")

with app.app_context():
    ensure_database_schema()


def ensure_demo_accounts_exist():
    with app.app_context():
        ensure_database_schema()
        demo_emails = {
            'admin@learntogether.com',
            'teacher@learntogether.com',
            'student@learntogether.com',
            'sarah@learntogether.com',
            'parent@learntogether.com',
        }
        existing_emails = {user.email for user in User.query.filter(User.email.in_(list(demo_emails))).all()}
        if len(existing_emails) < len(demo_emails):
            seed_data(create_demo_accounts=True)


ensure_demo_accounts_exist()

# Debug-only helper: rebuild database and reseed default accounts when app.debug is True.
@app.route('/_dev/reset-defaults', methods=['GET', 'POST'])
def _dev_reset_defaults():
    if not app.debug:
        return ('Not allowed', 403)
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_data(create_demo_accounts=True)
    return ('Default accounts reset', 200)

if __name__ == '__main__':
    with app.app_context():
        ensure_database_schema()
        seed_data(create_demo_accounts=True)
    socketio.run(app, debug=True, port=5000)
