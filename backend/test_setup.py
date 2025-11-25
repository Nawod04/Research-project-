from flask import Flask
from flask_cors import CORS
import PyPDF2
import requests

app = Flask(__name__)
CORS(app)

@app.route('/')
def hello():
    return "Python Flask is working!"

@app.route('/test-pdf')
def test_pdf():
    return "PDF processing ready!"

if __name__ == '__main__':
    print("All imports successful!")
    print("Starting Flask server...")
    app.run(debug=True, port=5000)