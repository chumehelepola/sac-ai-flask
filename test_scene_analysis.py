import os
import requests
from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if not load_dotenv(dotenv_path):
    raise FileNotFoundError(f"Could not find .env file at {dotenv_path}")

# Load Notion token and Scene Analysis database ID
notion_token = os.getenv('NOTION_TOKEN')
scene_database_id = os.getenv('NOTION_DATABASE_ID_SCENE')

if not notion_token or not scene_database_id:
    raise ValueError("Missing Notion credentials: check .env file")

# Set up Notion API headers
headers = {
    "Authorization": f"Bearer {notion_token}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Query the Scene Analysis database
def test_scene_analysis_database():
    url = f"https://api.notion.com/v1/databases/{scene_database_id}/query"
    try:
        print("Querying Scene Analysis database...")
        response = requests.post(url, headers=headers)

        if response.status_code == 200:
            print("✅ Successfully connected to Scene Analysis database!")
            notion_data = response.json()

            # Check if there are entries in the database
            scene_entries = []
            for page in notion_data.get('results', []):
                title = page.get('properties', {}).get('Title', {}).get('title', [])
                if title:
                    scene_entries.append(title[0]['text']['content'])

            if scene_entries:
                print("Scenes in the database:")
                for scene in scene_entries:
                    print(f"- {scene}")
            else:
                print("No scenes found in the database.")
        else:
            print(f"❌ Failed to query the database. Status code: {response.status_code}")
            print("Response:", response.json())

    except Exception as e:
        print(f"❌ An error occurred: {e}")

# Run the test
if __name__ == "__main__":
    test_scene_analysis_database()