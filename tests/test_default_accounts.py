import unittest

from app import app, db, ensure_database_schema, User


class DefaultAccountTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update(TESTING=True)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_default_accounts_are_seeded_and_can_log_in(self):
        ensure_database_schema()

        with self.app.test_client() as client:
            response = client.post(
                '/login',
                data={'email': 'admin@learntogether.com', 'password': 'admin123'},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['Location'], '/dashboard')

        with self.app.app_context():
            self.assertGreaterEqual(User.query.filter_by(email='admin@learntogether.com').count(), 1)
            self.assertGreaterEqual(User.query.filter_by(email='student@learntogether.com').count(), 1)


if __name__ == '__main__':
    unittest.main()
