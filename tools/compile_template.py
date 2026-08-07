from app import app
import traceback
try:
    app.jinja_env.get_template('group_detail.html')
    print('TEMPLATE_OK')
except Exception:
    traceback.print_exc()
