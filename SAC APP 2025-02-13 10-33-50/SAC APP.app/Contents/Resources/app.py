import os
import requests
import PyPDF2  # PyPDF2 for PDF text extraction
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_session import Session
from urllib.parse import quote 
import openai
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if not load_dotenv(dotenv_path):
    raise FileNotFoundError(f"Could not find .env file at {dotenv_path}")

# Load API keys and database IDs
openai_api_key = os.getenv('OPENAI_API_KEY')
notion_token = os.getenv('NOTION_TOKEN')
notion_database_id = os.getenv('NOTION_DATABASE_ID')  # Acting tips database
notion_database_scene_id = os.getenv('NOTION_DATABASE_ID_SCENE')  # Scene analysis database
aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
s3_bucket_name = os.getenv('S3_BUCKET_NAME')
aws_default_region = os.getenv('AWS_DEFAULT_REGION')

# Debug print statements
print(f"AWS_ACCESS_KEY_ID: {aws_access_key}")
print(f"AWS_SECRET_ACCESS_KEY: {aws_secret_key}")
print(f"AWS_DEFAULT_REGION: {aws_default_region}")
print(f"S3_BUCKET_NAME: {s3_bucket_name}")

if not openai_api_key or not notion_token or not notion_database_id or not notion_database_scene_id or not aws_access_key or not aws_secret_key or not s3_bucket_name or not aws_default_region:
    raise ValueError("Missing required environment variables: check .env file")

# Set the OpenAI API key
openai.api_key = openai_api_key

# Initialize Boto3 S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key,
    region_name=aws_default_region
)

# Test the S3 client
try:
    response = s3_client.list_buckets()
    print("S3 Buckets:")
    for bucket in response['Buckets']:
        print(f"  {bucket['Name']}")
except Exception as e:
    print(f"Error listing S3 buckets: {e}")

# Flask app setup
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session/'
app.config['SESSION_PERMANENT'] = False
Session(app)
CORS(app)  # Enable CORS for all routes

def extract_text_from_pdf(file_url):
    """
    Extract text from a PDF file given its URL.
    """
    try:
        response = requests.get(file_url)
        response.raise_for_status()

        with open('/tmp/temp.pdf', 'wb') as f:
            f.write(response.content)

        # Extract text from the PDF using PyPDF2
        with open('/tmp/temp.pdf', 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                text += page.extract_text()

        return text
    except requests.exceptions.RequestException as e:
        print(f"Error downloading PDF file: {e}")
        return None

def upload_file_to_s3(file_name, file_content):
    """
    Uploads a file to AWS S3 and returns the public URL.
    """
    try:
        s3_client.put_object(Bucket=s3_bucket_name, Key=file_name, Body=file_content)
        return f"https://{s3_bucket_name}.s3.{aws_default_region}.amazonaws.com/{file_name}"
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f"Failed to upload file to S3: {e}")
        return None

@app.route('/', methods=['GET', 'POST'])
def home():
    answer = None
    error_message = None

    if request.method == 'POST':
        user_question = request.form.get('question')
        try:
            if not user_question:
                raise ValueError("No question provided")

            # Query Notion database for Acting Tips
            notion_response = requests.post(
                f"https://api.notion.com/v1/databases/{quote(notion_database_id)}/query",
                headers={
                    "Authorization": f"Bearer {notion_token}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                },
            )

            notion_data = notion_response.json()
            if notion_response.status_code != 200:
                raise ValueError(f"Notion API error: {notion_data}")

            # Extract relevant information
            relevant_info = []
            for page in notion_data.get('results', []):
                page_id = page.get('id')
                if page_id:
                    page_response = requests.get(
                        f"https://api.notion.com/v1/blocks/{quote(page_id)}/children",
                        headers={
                            "Authorization": f"Bearer {notion_token}",
                            "Notion-Version": "2022-06-28",
                        },
                    )
                    if page_response.status_code == 200:
                        page_content = page_response.json()
                        for block in page_content.get("results", []):
                            if block.get("type") == "paragraph":
                                text = block["paragraph"]["rich_text"]
                                if text:
                                    relevant_info.append("".join([t["text"]["content"] for t in text]))
                            elif block.get("type") == "file":
                                file_data = block["file"]
                                file_url = None
                                if file_data["type"] == "external":
                                    file_url = file_data["external"]["url"]
                                elif file_data["type"] == "file":
                                    file_url = file_data["file"]["url"]
                                if file_url:
                                    relevant_info.append(f"File URL: {file_url}")
                    else:
                        print(f"Error fetching page content: {page_response.status_code}, {page_response.json()}")

            if not relevant_info:
                answer = "I couldn't find any relevant information in the Acting Tips database."
                return render_template('index.html', answer=answer, error_message=error_message)

            notion_summary = " ".join(relevant_info)

            # Generate AI response using OpenAI
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": f"You are an acting mentor AI. Use the following information to help answer questions from the user: {notion_summary}"},
                    {"role": "user", "content": user_question}
                ],
                max_tokens=150
            )
            answer = response.choices[0].message['content'].strip()

        except requests.exceptions.RequestException as e:
            error_message = f"Error retrieving data from Notion: {e}"
        except ValueError as e:
            error_message = str(e)
        except Exception as e:
            error_message = f"An unexpected error occurred: {e}"

    return render_template('index.html', answer=answer, error_message=error_message)

@app.route('/scene_analysis', methods=['GET'])
def scene_analysis():
    try:
        # Query the Scene Analysis database to get the latest uploaded scene
        notion_response = requests.post(
            f"https://api.notion.com/v1/databases/{quote(notion_database_scene_id)}/query",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={
                "sorts": [{"property": "Created time", "direction": "descending"}],  # Sort by Created time
                "page_size": 1  # Get the latest entry
            }
        )

        notion_data = notion_response.json()
        print(f"Notion Response Data: {notion_data}")  # Print the entire response for debugging
        if notion_response.status_code != 200:
            raise ValueError(f"Scene Analysis API error: {notion_data}")

        # Extract the latest scene entry
        latest_scene = notion_data.get('results', [])[0]
        print(f"Latest Scene Data: {latest_scene}")  # Print the latest scene data for debugging
        title = latest_scene.get('properties', {}).get('Title', {}).get('title', [])
        upload_scene = latest_scene.get('properties', {}).get('Upload Scene', {})

        if not title or not upload_scene:
            return jsonify({'message': "No scenes found in the Scene Analysis database."})

        scene_content = f"Title: {title[0]['text']['content']}\n"
        print(f"Upload Scene Data: {upload_scene}")  # Print the upload scene data for debugging
        files = upload_scene.get('files', [])
        if not files:
            return jsonify({'error': "No files found in the Upload Scene property."}), 500

        for file in files:
            try:
                print(f"File Data: {file}")  # Print the file data for debugging
                # Ensure the file URL is correct and accessible
                file_url = None
                if file["type"] == "file" and "file" in file:
                    file_url = file["file"].get("url")
                elif file["type"] == "external" and "external" in file:
                    file_url = file["external"].get("url")
                if not file_url:
                    raise KeyError("File URL not found")
                
                scene_content += f"File: {file_url}\n"
                print(f"Extracting text from PDF: {file_url}")  # Log the file URL

                # Extract text from the PDF file
                extracted_text = extract_text_from_pdf(file_url)
                if extracted_text is None:
                    return jsonify({'error': f"Error extracting text from PDF: Unable to download the file from {file_url}."}), 500
                scene_content += f"Extracted Text: {extracted_text}\n"

            except KeyError as e:
                print(f"Error accessing file URL: {e}")
                return jsonify({'error': f"Error accessing file URL: {e}"}), 500
            except Exception as e:
                print(f"Error extracting text from PDF: {e}")
                return jsonify({'error': f"Error extracting text from PDF: {e}"}), 500

        # Generate leading questions using OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI that provides leading questions for actors based on scene content."},
                {"role": "user", "content": f"Here is a scene: {scene_content} Provide a series of leading questions for an actor to help them understand key moments, key events for the characters, relationships, status, and stakes in this scene."}
            ],
            max_tokens=200
        )
        questions = response.choices[0].message['content'].strip()

        return jsonify({'questions': questions})

    except Exception as e:
        print(f"Error accessing Scene Analysis database: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/questions', methods=['GET'])
def get_questions():
    try:
        # Query the Scene Analysis database for questions
        notion_response = requests.post(
            f"https://api.notion.com/v1/databases/{quote(notion_database_scene_id)}/query",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
        )

        notion_data = notion_response.json()
        if notion_response.status_code != 200:
            raise ValueError(f"Notion API error: {notion_data}")

        # Extract questions
        questions = []
        for page in notion_data.get('results', []):
            for key, value in page.get('properties', {}).items():
                if 'title' in value and value['title']:
                    questions.append(value['title'][0]['text']['content'])

        if not questions:
            return jsonify({'message': "No questions found in the Notion database ID scene table."})

        # Store questions in session
        session['questions'] = questions

        return jsonify({'questions': questions})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    answer = data.get('answer', '')
    if not answer:
        return jsonify({'error': 'Answer is required'}), 400

    try:
        if 'questions' not in session:
            raise ValueError("Questions are missing in session.")

        responses = session.get('responses', [])
        responses.append(answer)
        session['responses'] = responses

        questions = session['questions']

        if len(responses) < len(questions):
            next_question = questions[len(responses)]
            return jsonify({'next_question': next_question})
        else:
            final_feedback = generate_final_feedback(questions, responses)
            return jsonify({'final_feedback': final_feedback})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.get_json()
    question = data.get('question', '')
    if not question:
        return jsonify({'error': 'Question is required'}), 400

    try:
        notion_response = requests.post(
            f"https://api.notion.com/v1/databases/{quote(notion_database_id)}/query",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
        )

        notion_data = notion_response.json()
        if notion_response.status_code != 200:
            return jsonify({'error': f"Notion API error: {notion_data}"}), 500

        relevant_info = []
        for page in notion_data.get('results', []):
            page_id = page.get('id')
            if page_id:
                page_response = requests.get(
                    f"https://api.notion.com/v1/blocks/{quote(page_id)}/children",
                    headers={
                        "Authorization": f"Bearer {notion_token}",
                        "Notion-Version": "2022-06-28",
                    },
                )
                if page_response.status_code == 200:
                    page_content = page_response.json()
                    for block in page_content.get('results', []):
                        if block.get('type') == 'paragraph':
                            text = block['paragraph']['rich_text']
                            if text:
                                relevant_info.append(''.join([t['text']['content'] for t in text]))
                        elif block.get("type") == "file":
                            file_data = block["file"]
                            file_url = None
                            if file_data["type"] == "external":
                                file_url = file_data["external"]["url"]
                            elif file_data["type"] == "file":
                                file_url = file_data["file"]["url"]
                            if file_url:
                                relevant_info.append(f"File URL: {file_url}")
                else:
                    print(f"Error fetching page content: {page_response.status_code}, {page_response.json()}")

        if not relevant_info:
            return jsonify({'response': "I couldn't find any relevant information in the Acting Tips database."})

        notion_summary = ' '.join(relevant_info)

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": f"You are an acting mentor AI. Use the following information to help answer questions from the user: {notion_summary}"},
                {"role": "user", "content": question}
            ],
            max_tokens=150
        )
        answer = response.choices[0].message['content'].strip()
        return jsonify({'response': answer})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'message': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400

    try:
        file_path = os.path.join('/tmp', file.filename)
        file.save(file_path)

        with open(file_path, 'rb') as f:
            file_data = f.read()

        # Upload the file to AWS S3 and get the public URL
        file_url = upload_file_to_s3(file.filename, file_data)
        
        if not file_url:
            raise ValueError("Failed to upload file to S3")

        # Use Notion API to upload the file as an external file
        response = requests.post(
            f"https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={
                "parent": {"database_id": notion_database_scene_id},
                "properties": {
                    "Title": {"title": [{"text": {"content": file.filename}}]},
                    "Upload Scene": {
                        "files": [{
                            "name": file.filename,
                            "external": {"url": file_url}
                        }]
                    }
                }
            }
        )

        notion_data = response.json()
        if response.status_code != 200:
            raise ValueError(f"Notion API error: {notion_data}")

        return jsonify({'message': f'File {file.filename} uploaded successfully to Notion', 'notion_data': notion_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_final_feedback(questions, responses):
    try:
        questions_and_answers = ""
        for question, response in zip(questions, responses):
            questions_and_answers += f"Q: {question}\nA: {response}\n"

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI that provides scene analysis feedback based on client responses."},
                {"role": "user", "content": f"Here are the responses from the client: {questions_and_answers}\nProvide feedback based on these responses."}
            ],
            max_tokens=150
        )
        feedback = response.choices[0].message['content'].strip()
        return feedback
    except Exception as e:
        return f"An error occurred while generating feedback: {str(e)}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
