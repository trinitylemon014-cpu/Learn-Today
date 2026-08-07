import unittest

from app import app, db, User, Group, GroupMember, Message


class MessageActionsTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='test-secret', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

        self.user = User(name='Tester', email='tester@example.com', password='x', role='student')
        self.admin = User(name='Teacher', email='teacher@example.com', password='x', role='teacher')
        db.session.add_all([self.user, self.admin])
        db.session.commit()

        self.group = Group(name='Study Group', created_by=self.admin.id, group_type='student')
        db.session.add(self.group)
        db.session.flush()
        db.session.add(GroupMember(group_id=self.group.id, user_id=self.user.id, role='member'))
        db.session.commit()

        self.message = Message(group_id=self.group.id, sender_id=self.user.id, message='Hello there')
        db.session.add(self.message)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['role'] = 'student'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_pin_message_route(self):
        response = self.client.post(f'/groups/{self.group.id}/messages/{self.message.id}/pin', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        self.assertTrue(Message.query.get(self.message.id).is_pinned)

    def test_delete_message_for_me_route(self):
        response = self.client.post(f'/groups/{self.group.id}/messages/{self.message.id}/delete?scope=me', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, len(self.message.visible_to_users))

    def test_leave_group_route_removes_membership(self):
        response = self.client.post(f'/groups/{self.group.id}/leave', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(GroupMember.query.filter_by(group_id=self.group.id, user_id=self.user.id).first())


if __name__ == '__main__':
    unittest.main()
