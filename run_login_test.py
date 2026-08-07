from app import app, db, seed_data

with app.app_context():
    db.create_all()
    seed_data()

    client = app.test_client()

    def try_login(email, password):
        resp = client.post('/login', data={'email': email, 'password': password}, follow_redirects=False)
        print(f'Trying login: {email} / {password}')
        print('Status code:', resp.status_code)
        if 'Location' in resp.headers:
            print('Location:', resp.headers['Location'])
        else:
            print('No redirect; response length:', len(resp.data))
        print('-' * 40)

    try_login('admin@learntogether.com', 'admin123')
    try_login('Admin@LearnTogether.com', 'admin123')
    try_login('teacher@learntogether.com', 'teacher123')
    try_login('student@learntogether.com', 'student123')
