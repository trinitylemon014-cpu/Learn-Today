import unittest
import uuid

from app import app, db, User


class TemplateLayoutTests(unittest.TestCase):
    def test_login_template_renders_with_base_layout(self):
        with app.test_request_context('/login'):
            template = app.jinja_env.get_template('login.html')
            rendered = template.render()

            self.assertIn('Learn Together', rendered)

    def test_public_courses_page_renders_course_list(self):
        with app.test_client() as client:
            response = client.get('/courses')

            self.assertEqual(response.status_code, 200)
            self.assertIn('All Courses', response.get_data(as_text=True))

    def test_teacher_courses_page_renders_course_list(self):
        with app.app_context():
            teacher = User(name='Teacher User', email=f'teacher-page-{uuid.uuid4().hex}@example.com', password='pw', role='teacher')
            db.session.add(teacher)
            db.session.commit()

            with app.test_client() as client:
                with client.session_transaction() as session:
                    session['user_id'] = teacher.id
                    session['role'] = teacher.role

                response = client.get('/courses')

                self.assertEqual(response.status_code, 200)
                self.assertIn('All Courses', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
