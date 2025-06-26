import os
import requests

# Use consistent variable naming
NOTION_TOKEN = os.getenv("NOTION_TOKEN")  # Fetch the Notion token from .env
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")  # Fetch the database ID from .env

# Debugging: Print token and database ID to verify they are loaded correctly
print(f"Loaded Notion Token: {NOTION_TOKEN}")
print(f"Loaded Notion Database ID: {NOTION_DATABASE_ID}")

url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",  # Use the consistent variable name
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

response = requests.post(url, headers=headers)
if response.status_code == 200:
    print("Successfully retrieved data from Notion:")
    print(response.json())
else:
    print(f"Error: {response.status_code} - {response.text}")



