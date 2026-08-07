import unittest

from app import app, db, User


class RegistrationFlowTests(unittest.TestCase):
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

    def test_student_registration_creates_pending_account(self):
        with self.app.test_client() as client:
            response = client.post('/register', data={
                'role': 'student',
                'name': 'New Student',
                'email': 'student@example.com',
                'date_of_birth': '2008-05-10',
                'previous_school': 'St. Mary School',
                'courses_interest': 'Mathematics, Science',
                'parent_name': 'Parent Name',
                'parent_email': 'parent@example.com',
            }, follow_redirects=False)

            self.assertEqual(response.status_code, 302)
            user = User.query.filter_by(email='student@example.com').first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role, 'student')
            self.assertEqual(user.status, 'pending')
            self.assertEqual(user.previous_school, 'St. Mary School')


if __name__ == '__main__':
    unittest.main()
