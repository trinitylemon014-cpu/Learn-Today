import unittest
from app import app, db, get_current_user, seed_data, hash_password, User
from sqlalchemy import text


class DatabaseInitTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_get_current_user_recreates_schema_when_tables_missing(self):
        with self.app.app_context():
            db.session.execute(text('DROP TABLE users'))
            db.session.commit()

            with self.app.test_request_context('/') as ctx:
                ctx.session['user_id'] = 1
                user = get_current_user()

                self.assertIsNone(user)

    def test_seed_data_creates_default_accounts_even_when_other_users_exist(self):
        with self.app.app_context():
            db.session.add(User(name='Custom User', email='custom@example.com', password='temp', role='student'))
            db.session.commit()

            seed_data(create_demo_accounts=True)

            admin = User.query.filter_by(email='admin@learntogether.com').first()
            teacher = User.query.filter_by(email='teacher@learntogether.com').first()
            student = User.query.filter_by(email='student@learntogether.com').first()
            parent = User.query.filter_by(email='parent@learntogether.com').first()

            self.assertIsNotNone(admin)
            self.assertEqual(admin.role, 'admin')
            self.assertEqual(admin.password, hash_password('admin123'))
            self.assertIsNotNone(teacher)
            self.assertEqual(teacher.role, 'teacher')
            self.assertIsNotNone(student)
            self.assertEqual(student.role, 'student')
            self.assertIsNotNone(parent)
            self.assertEqual(parent.role, 'parent')

    def test_seed_data_creates_demo_accounts_when_requested(self):
        with self.app.app_context():
            seed_data(create_demo_accounts=True)

            demo_accounts = User.query.filter(
                User.email.in_([
                    'admin@learntogether.com',
                    'teacher@learntogether.com',
                    'student@learntogether.com',
                    'sarah@learntogether.com',
                    'parent@learntogether.com',
                ])
            ).all()

            self.assertEqual(5, len(demo_accounts))
            self.assertEqual(hash_password('admin123'), User.query.filter_by(email='admin@learntogether.com').first().password)
            self.assertEqual(hash_password('teacher123'), User.query.filter_by(email='teacher@learntogether.com').first().password)
            self.assertEqual(hash_password('student123'), User.query.filter_by(email='student@learntogether.com').first().password)

    def test_login_accepts_legacy_plaintext_passwords(self):
        with self.app.app_context():
            user = User(name='Legacy User', email='legacy@example.com', password='legacy123', role='student')
            db.session.add(user)
            db.session.commit()

            with self.app.test_client() as client:
                response = client.post('/login', data={'email': 'legacy@example.com', 'password': 'legacy123'}, follow_redirects=False)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers['Location'], '/dashboard')
                with client.session_transaction() as session:
                    self.assertEqual(session['user_id'], user.id)


if __name__ == '__main__':
    unittest.main()
