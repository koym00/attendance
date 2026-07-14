from flask import Flask
from main.routes import bp_main
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.register_blueprint(bp_main, url_prefix='')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
