from app import app
from rest import rest

app = app
app.register_blueprint(rest, url_prefix='/rest')
