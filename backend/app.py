from flask import Flask, request
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import io
from PyPDF2 import PdfReader
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app)

# Initialize Firebase Admin SDK
cred = credentials.Certificate("serviceAccountKey.json")  # Path to your service account key
firebase_admin.initialize_app(cred)

# Initialize Firestore Database
db = firestore.client()

from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/')
def hello():
    return "Python Flask is working!"

@app.route('/test-pdf')
def test_pdf():
    return "PDF processing ready!"

@app.route('/verify-firebase', methods=['GET'])
def verify_firebase():
    try:
        # Add a test document to Firestore
        test_data = {"status": "connected", "timestamp": firestore.SERVER_TIMESTAMP}
        doc_ref = db.collection('test-connection').document('test-doc')
        doc_ref.set(test_data)

        # Read the document back
        doc = doc_ref.get()
        if doc.exists:
            return {"message": "Successfully connected to Firebase!", "data": doc.to_dict()}, 200
        else:
            return {"message": "Failed to read test document from Firestore."}, 500
    except Exception as e:
        return {"message": "Error connecting to Firebase.", "error": str(e)}, 500

@app.route('/analyze-certificates/<tutor_id>', methods=['GET', 'POST'])
def analyze_certificates(tutor_id):
    try:
        # Check if this is a POST request for single certificate analysis
        if request.method == 'POST':
            data = request.get_json()
            certificate_id = data.get('certificate_id')
            file_url = data.get('fileUrl')

            if not certificate_id or not file_url:
                return {"message": "Missing certificate_id or fileUrl", "error": "Invalid request"}, 400

            logging.info(f"Analyzing single certificate {certificate_id} for tutor {tutor_id}")

            # Get tutor data
            tutor_ref = db.collection('tutors').document(tutor_id)
            tutor_doc = tutor_ref.get()

            if not tutor_doc.exists:
                return {"message": f"Tutor {tutor_id} not found", "error": "Tutor does not exist"}, 404

            tutor_data = tutor_doc.to_dict()

            # Download and analyze the specific certificate
            try:
                response = requests.get(file_url)
                response.raise_for_status()
                pdf_bytes = io.BytesIO(response.content)
                logging.info(f"Downloaded PDF for certificate {certificate_id}")
            except Exception as e:
                logging.error(f"Failed to download PDF for certificate {certificate_id}: {str(e)}")
                return {"message": "Failed to download certificate", "error": str(e)}, 500

            # Extract text using PyPDF2
            try:
                reader = PdfReader(pdf_bytes)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                logging.info(f"Extracted text from PDF for certificate {certificate_id}, length: {len(text)}")
            except Exception as e:
                logging.error(f"Failed to extract text from PDF for certificate {certificate_id}: {str(e)}")
                return {"message": "Failed to extract text from certificate", "error": str(e)}, 500

            # Identify details
            extracted = {
                "tutor_id": tutor_id,
                "tutor_name": tutor_data.get('name', 'Unknown'),
                "certificate_id": certificate_id,
                "reference_number": extract_after(text, "My Ref."),
                "title": "General Certificate of Education (Advanced Level) Examination, Sri Lanka." if "General Certificate of Education (Advanced Level) Examination, Sri Lanka." in text else None,
                "name": extract_after(text, "Name in Full"),
                "index_number": extract_after(text, "Index Number"),
                "year": extract_after(text, "Year of Examination"),
            }
            logging.info(f"Extracted data for certificate {certificate_id}: {extracted}")

            # Verify certificate completeness and generate appropriate message
            required_fields = ["reference_number", "title", "name", "index_number", "year"]
            missing_fields = [field for field in required_fields if extracted.get(field) is None]

            if missing_fields:
                verification_message = f"Your certificate has an issue. Missing fields: {', '.join(missing_fields)}"
                verification_status = "not verified"
            else:
                verification_message = "Verification passed"
                verification_status = "verified"

            extracted["verification_status"] = verification_status
            extracted["verification_message"] = verification_message

            # Store extracted data in the certificate document
            try:
                update_data = {
                    'extractedText': text,
                    'reference_number': extracted.get("reference_number"),
                    'title': extracted.get("title"),
                    'name': extracted.get("name"),
                    'index_number': extracted.get("index_number"),
                    'year': extracted.get("year"),
                    'verification_status': verification_status,
                    'verification_message': verification_message,
                    'analyzedAt': firestore.SERVER_TIMESTAMP,
                }

                # Update the certificate document with extracted data
                cert_ref = db.collection('tutors').document(tutor_id).collection('certificates').document(certificate_id)
                cert_ref.update(update_data)
                logging.info(f"Updated certificate {certificate_id} with extracted data")

            except Exception as e:
                logging.error(f"Failed to update certificate {certificate_id} with extracted data: {str(e)}")

            return {"message": verification_message, "data": [extracted]}, 200

        # GET request - analyze all certificates for the tutor
        logging.info(f"Starting certificate analysis for tutor: {tutor_id}")

        # Step 1: Get tutor data
        tutor_ref = db.collection('tutors').document(tutor_id)
        tutor_doc = tutor_ref.get()

        if not tutor_doc.exists:
            return {"message": f"Tutor {tutor_id} not found", "error": "Tutor does not exist"}, 404

        tutor_data = tutor_doc.to_dict()
        logging.info(f"Found tutor {tutor_id}")

        # Step 2: Get all certificate docs for this tutor
        certs_ref = db.collection('tutors').document(tutor_id).collection('certificates')
        certs = certs_ref.stream()
        certs_list = list(certs)
        logging.info(f"Found {len(certs_list)} certificates for tutor {tutor_id}")

        results = []

        # Step 3: Loop through each certificate
        for cert in certs_list:
            cert_data = cert.to_dict()
            logging.info(f"Certificate {cert.id} data: {cert_data}")
            pdf_url = cert_data.get('fileUrl')  # Note: it's 'fileUrl' not 'fileURL'
            logging.info(f"Processing certificate {cert.id}, URL: {pdf_url}")

            if not pdf_url:
                logging.warning(f"No URL found for certificate {cert.id}")
                continue  # Skip if no URL found

            # Step 4: Download PDF
            try:
                response = requests.get(pdf_url)
                response.raise_for_status()
                pdf_bytes = io.BytesIO(response.content)
                logging.info(f"Downloaded PDF for certificate {cert.id}")
            except Exception as e:
                logging.error(f"Failed to download PDF for certificate {cert.id}: {str(e)}")
                continue

            # Step 5: Extract text using PyPDF2
            try:
                reader = PdfReader(pdf_bytes)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                logging.info(f"Extracted text from PDF for certificate {cert.id}, length: {len(text)}")
            except Exception as e:
                logging.error(f"Failed to extract text from PDF for certificate {cert.id}: {str(e)}")
                continue

            # Step 6: Identify details
            extracted = {
                "tutor_id": tutor_id,
                "tutor_name": tutor_data.get('name', 'Unknown'),
                "certificate_id": cert.id,
                "reference_number": extract_after(text, "My Ref."),
                "title": "General Certificate of Education (Advanced Level) Examination, Sri Lanka." if "General Certificate of Education (Advanced Level) Examination, Sri Lanka." in text else None,
                "name": extract_after(text, "Name in Full"),
                "index_number": extract_after(text, "Index Number"),
                "year": extract_after(text, "Year of Examination"),
            }
            logging.info(f"Extracted data for certificate {cert.id}: {extracted}")

            # Step 7: Verify certificate completeness and generate appropriate message
            required_fields = ["reference_number", "title", "name", "index_number", "year"]
            missing_fields = [field for field in required_fields if extracted.get(field) is None]

            if missing_fields:
                verification_message = f"Your certificate has an issue. Missing fields: {', '.join(missing_fields)}"
                verification_status = "not verified"
            else:
                verification_message = "Verification passed"
                verification_status = "verified"

            extracted["verification_status"] = verification_status
            extracted["verification_message"] = verification_message

            # Store extracted data in the certificate document
            try:
                update_data = {
                    'extractedText': text,
                    'reference_number': extracted.get("reference_number"),
                    'title': extracted.get("title"),
                    'name': extracted.get("name"),
                    'index_number': extracted.get("index_number"),
                    'year': extracted.get("year"),
                    'verification_status': verification_status,
                    'verification_message': verification_message,
                    'analyzedAt': firestore.SERVER_TIMESTAMP,
                }

                # Update the certificate document with extracted data
                cert_ref = db.collection('tutors').document(tutor_id).collection('certificates').document(cert.id)
                cert_ref.update(update_data)
                logging.info(f"Updated certificate {cert.id} with extracted data")

            except Exception as e:
                logging.error(f"Failed to update certificate {cert.id} with extracted data: {str(e)}")

            results.append(extracted)

        logging.info(f"Completed analysis for tutor {tutor_id}, returning {len(results)} results")
        return {"message": f"Certificate data extracted successfully for tutor {tutor_id}!", "data": results}, 200

    except Exception as e:
        logging.error(f"Error analyzing certificates for tutor {tutor_id}: {str(e)}")
        return {"message": "Error analyzing certificates", "error": str(e)}, 500

# Helper function
def extract_after(text, keyword):
    """Finds the text after a given keyword (up to the next newline or period)."""
    if keyword in text:
        start = text.find(keyword) + len(keyword)
        end = text.find("\n", start)
        if end == -1:
            end = text.find(".", start)
        return text[start:end].strip(": ").strip()
    return None


if __name__ == '__main__':
    print("All imports successful!")
    print("Starting Flask server...")
    app.run(debug=True, port=5000)