import unittest

from app import app, db, User, Enrollment, Progress, Attendance, Group, GroupMember, Message


class DeleteUserTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='test-secret', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

        self.admin = User(name='Admin', email='admin@example.com', password='x', role='admin')
        self.student = User(name='Student', email='student@example.com', password='x', role='student')
        db.session.add_all([self.admin, self.student])
        db.session.commit()

        self.course = None
        self.group = None

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_admin_can_delete_student_without_integrity_error(self):
        # Create dependent records that used to block deletion.
        enrollment = Enrollment(student_id=self.student.id, course_id=1)
        db.session.add(enrollment)
        db.session.add(Progress(student_id=self.student.id, course_id=1, progress_percent=20))
        db.session.add(Attendance(student_id=self.student.id, course_id=1, status='present'))

        group = Group(name='Test Group', created_by=self.admin.id, group_type='student')
        db.session.add(group)
        db.session.flush()
        db.session.add(GroupMember(group_id=group.id, user_id=self.student.id, role='member'))
        db.session.add(Message(group_id=group.id, sender_id=self.student.id, message='hello'))
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.admin.id
            sess['role'] = 'admin'

        response = self.client.post(f'/admin/users/{self.student.id}/delete', follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(User.query.get(self.student.id))
        self.assertEqual(Enrollment.query.filter_by(student_id=self.student.id).count(), 0)
        self.assertEqual(Progress.query.filter_by(student_id=self.student.id).count(), 0)
        self.assertEqual(Attendance.query.filter_by(student_id=self.student.id).count(), 0)
        self.assertEqual(GroupMember.query.filter_by(user_id=self.student.id).count(), 0)
        self.assertEqual(Message.query.filter_by(sender_id=self.student.id).count(), 0)


if __name__ == '__main__':
    unittest.main()
