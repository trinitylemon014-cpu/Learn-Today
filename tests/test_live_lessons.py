import io
import unittest
from datetime import datetime
from app import app, db
from models import User, Course, ScheduledLesson, Enrollment, Progress


class ScheduledLessonTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_teacher_can_schedule_lesson_for_course(self):
        teacher = User(name='Teacher', email='teacher@example.com', password='pw', role='teacher')
        student = User(name='Student', email='student@example.com', password='pw', role='student')
        db.session.add_all([teacher, student])
        db.session.commit()

        course = Course(title='Math', description='Math course', teacher_id=teacher.id)
        db.session.add(course)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = teacher.id

        response = self.client.post(
            f'/courses/{course.id}/lessons/schedule',
            data={
                'title': 'Algebra Basics',
                'description': 'Introduction to algebra',
                'meet_link': 'https://vidtrixz.com/meeting/abc123',
                'scheduled_at': '2026-07-10T18:00',
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ScheduledLesson.query.count(), 1)
        lesson = ScheduledLesson.query.first()
        self.assertEqual(lesson.title, 'Algebra Basics')
        self.assertEqual(lesson.course_id, course.id)
        self.assertEqual(lesson.teacher_id, teacher.id)
        self.assertEqual(lesson.meet_link, 'https://vidtrixz.com/meeting/abc123')
        self.assertTrue(lesson.is_active)

    def test_teacher_can_upload_lesson_poster(self):
        teacher = User(name='Teacher', email='teacher5@example.com', password='pw', role='teacher')
        db.session.add(teacher)
        db.session.commit()

        course = Course(title='Design', description='Design course', teacher_id=teacher.id)
        db.session.add(course)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = teacher.id

        image_data = io.BytesIO(b'PNG\r\nPNG data')
        response = self.client.post(
            f'/courses/{course.id}/lessons/schedule',
            data={
                'title': 'Design Review',
                'description': 'Review learning outcomes',
                'meet_link': 'https://vidtrixz.com/meeting/design123',
                'scheduled_at': '2026-07-10T18:00',
                'poster_file': (image_data, 'poster.png'),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ScheduledLesson.query.count(), 1)
        lesson = ScheduledLesson.query.first()
        self.assertIsNotNone(lesson.poster_url)
        self.assertIn('uploads/lesson_posters', lesson.poster_url)

    def test_teacher_can_toggle_lesson_visibility(self):
        teacher = User(name='Teacher', email='teacher2@example.com', password='pw', role='teacher')
        db.session.add(teacher)
        db.session.commit()

        course = Course(title='Science', description='Science course', teacher_id=teacher.id)
        db.session.add(course)
        db.session.commit()

        lesson = ScheduledLesson(
            course_id=course.id,
            teacher_id=teacher.id,
            title='Physics Basics',
            description='Lesson overview',
            meet_link='https://vidtrixz.com/meeting/physics123',
            scheduled_at=datetime.utcnow(),
            is_active=True,
        )
        db.session.add(lesson)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = teacher.id

        response = self.client.post(
            f'/courses/{course.id}/lessons/{lesson.id}/toggle',
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScheduledLesson.query.get(lesson.id).is_active)


    def test_student_can_view_scheduled_meeting_link(self):
        teacher = User(name='Teacher', email='teacher3@example.com', password='pw', role='teacher')
        student = User(name='Student', email='student3@example.com', password='pw', role='student')
        db.session.add_all([teacher, student])
        db.session.commit()

        course = Course(title='English', description='English course', teacher_id=teacher.id)
        db.session.add(course)
        db.session.commit()

        lesson = ScheduledLesson(
            course_id=course.id,
            teacher_id=teacher.id,
            title='Reading Lesson',
            description='Join the meeting',
            meet_link='https://vidtrixz.com/meeting/english123',
            scheduled_at=datetime.utcnow(),
            is_active=True,
        )
        db.session.add(lesson)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = student.id

        response = self.client.get(f'/courses/{course.id}', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Reading Lesson', response.get_data(as_text=True))
        self.assertIn('vidtrixz.com/meeting/english123', response.get_data(as_text=True))

    def test_teacher_can_delete_scheduled_lesson(self):
        teacher = User(name='Teacher', email='teacher4@example.com', password='pw', role='teacher')
        db.session.add(teacher)
        db.session.commit()

        course = Course(title='History', description='History course', teacher_id=teacher.id)
        db.session.add(course)
        db.session.commit()

        lesson = ScheduledLesson(
            course_id=course.id,
            teacher_id=teacher.id,
            title='History Lesson',
            description='Join the meeting',
            meet_link='https://vidtrixz.com/meeting/history123',
            scheduled_at=datetime.utcnow(),
            is_active=True,
        )
        db.session.add(lesson)
        db.session.commit()
        lesson_id = lesson.id

        with self.client.session_transaction() as sess:
            sess['user_id'] = teacher.id

        response = self.client.post(
            f'/courses/{course.id}/lessons/{lesson_id}/delete',
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(ScheduledLesson.query.get(lesson_id))


if __name__ == '__main__':
    unittest.main()
