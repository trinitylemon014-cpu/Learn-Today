import unittest

from app import group_identity, initials_for_name, user_identity


class IdentityHelperTests(unittest.TestCase):
    def test_initials_for_name(self):
        self.assertEqual(initials_for_name('Jane Smith'), 'JS')
        self.assertEqual(initials_for_name('Solo'), 'SO')
        self.assertEqual(initials_for_name(''), '?')

    def test_user_identity_uses_name_and_color(self):
        class DummyUser:
            def __init__(self):
                self.id = 7
                self.name = 'Alex Rivera'
                self.avatar = None

        identity = user_identity(DummyUser())
        self.assertEqual(identity['name'], 'Alex Rivera')
        self.assertEqual(identity['initials'], 'AR')
        self.assertIn('hsl(', identity['color'])

    def test_group_identity_uses_avatar_path(self):
        class DummyGroup:
            def __init__(self):
                self.id = 12
                self.name = 'Math Group'
                self.avatar = 'uploads/group_avatars/demo.png'

        identity = group_identity(DummyGroup())
        self.assertEqual(identity['name'], 'Math Group')
        self.assertEqual(identity['initials'], 'MG')
        self.assertEqual(identity['avatar'], 'uploads/group_avatars/demo.png')
        self.assertEqual(identity['avatar_url'], '/static/uploads/group_avatars/demo.png')


if __name__ == '__main__':
    unittest.main()
