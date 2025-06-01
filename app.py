from dotenv import load_dotenv
import os

load_dotenv()

import threading
import time
from flask import Flask, render_template, send_from_directory
import requests
from datetime import datetime
from collections import defaultdict
import re
import sqlite3
from PIL import Image
from io import BytesIO

# Environment config
GDRIVE_FOLDER = os.environ["GDRIVE_FOLDER"]
GAPI_KEY = os.environ["GAPI_KEY"]
PORT = int(os.environ.get("PORT", 5000))
THUMBNAIL_DIR = "thumbnails"
DB_FILE = "files.db"
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Setup
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
app = Flask(__name__)

# Initialize DB
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                date TEXT,
                thumbnail TEXT
            )
        """)

# Get image files from the given Google Drive folder (non-recursive)
def list_drive_files(folder_id):
    url = "https://www.googleapis.com/drive/v3/files"
    image_mime_types = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "image/bmp", "image/tiff", "image/jpg"
    }
    params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "files(id, name, mimeType, createdTime, description)",
        "key": GAPI_KEY,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return [f for f in files if f.get("mimeType") in image_mime_types]

# Download image and generate thumbnail
def download_and_create_thumbnail(file_id):
    url = f"https://drive.google.com/uc?id={file_id}"
    response = requests.get(url)
    response.raise_for_status()
    img = Image.open(BytesIO(response.content))
    img.thumbnail((200, 200))
    path = os.path.join(THUMBNAIL_DIR, f"{file_id}.jpg")
    img.save(path, format="JPEG")
    return path

# Background thread to sync Drive files
def save_files_periodically():
    while True:
        try:
            drive_files = list_drive_files(GDRIVE_FOLDER)
            current_ids = set()

            with sqlite3.connect(DB_FILE) as conn:
                cur = conn.cursor()

                for f in drive_files:
                    current_ids.add(f["id"])
                    date_match = ISO_DATE_REGEX.match(f["name"])
                    date = date_match.group(0) if date_match else f["createdTime"][:10]

                    cur.execute("SELECT 1 FROM files WHERE id = ?", (f["id"],))
                    exists = cur.fetchone()

                    if not exists:
                        thumb_path = download_and_create_thumbnail(f["id"])
                        cur.execute("""
                            INSERT OR REPLACE INTO files (id, name, description, date, thumbnail)
                            VALUES (?, ?, ?, ?, ?)
                        """, (f["id"], f["name"], f.get("description", ""), date, thumb_path))
                        conn.commit()

                # Delete removed files
                cur.execute("SELECT id, thumbnail FROM files")
                all_local = cur.fetchall()
                for file_id, thumb_path in all_local:
                    if file_id not in current_ids:
                        cur.execute("DELETE FROM files WHERE id = ?", (file_id,))
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                conn.commit()

        except Exception as e:
            print("Error updating file list:", e)
        time.sleep(60)

# Route: Gallery
@app.route("/")
def gallery():
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, description, date, thumbnail FROM files ORDER BY date DESC")
        files = cur.fetchall()

    grouped = defaultdict(list)
    for file in files:
        grouped[file[3]].append({
            "id": file[0],
            "name": file[1],
            "description": file[2],
            "thumbnail": file[4],
        })

    sorted_dates = sorted(grouped.keys(), reverse=True)
    return render_template("gallery.html", grouped=grouped, dates=sorted_dates)

# Route: Serve thumbnail
@app.route("/thumbnails/<filename>")
def serve_thumbnail(filename):
    return send_from_directory(THUMBNAIL_DIR, filename)

# Startup
if __name__ == "__main__":
    init_db()
    thread = threading.Thread(target=save_files_periodically, daemon=True)
    thread.start()

    print(f"Starting server at http://localhost:{PORT}")
    app.run(debug=True, port=PORT)
