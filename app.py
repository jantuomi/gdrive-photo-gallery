import os
import threading
import time
from flask.helpers import url_for
import requests
import re
import sqlite3

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, make_response, send_file
from flask_compress import Compress
from collections import defaultdict
from PIL import Image
from io import BytesIO

# Environment config
GDRIVE_FOLDER = os.environ["GDRIVE_FOLDER"]
GAPI_KEY = os.environ["GAPI_KEY"]
PORT = int(os.environ.get("PORT", 5000))
THUMBNAIL_DIR = "thumbnails"
DB_FILE = "data/sqlite.db"
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}")
AUTHOR = os.environ["AUTHOR"]
IG_LINK = os.environ.get("IG_LINK", None)
BASE_URL = os.environ["BASE_URL"]

# Setup
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
app = Flask(__name__)
Compress(app)

# Initialize DB
def init_db():
    # Create dir if not exists
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

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

    # Convert to RGB if image has alpha channel (RGBA or P)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.thumbnail((400, 400))
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

                    cur.execute("SELECT description FROM files WHERE id = ?", (f["id"],))
                    row = cur.fetchone()

                    if row is None:
                        # File not in DB — insert new with thumbnail
                        thumb_path = download_and_create_thumbnail(f["id"])
                        cur.execute("""
                            INSERT INTO files (id, name, description, date, thumbnail)
                            VALUES (?, ?, ?, ?, ?)
                        """, (f["id"], f["name"], f.get("description", ""), date, thumb_path))
                    else:
                        # File exists — update description if changed
                        existing_description = row[0] or ""
                        new_description = f.get("description", "")
                        if existing_description != new_description:
                            cur.execute("""
                                UPDATE files
                                SET name = ?, description = ?, date = ?
                                WHERE id = ?
                            """, (f["name"], new_description, date, f["id"]))

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

    if len(files) > 0:
        cover_img_path = url_for("serve_thumbnail", filename=files[0][4].split('/')[-1])
        cover_img_url = BASE_URL + cover_img_path
    else:
        cover_img_url = None

    return render_template("gallery.html",
        grouped=grouped,
        dates=sorted_dates,
        author=AUTHOR,
        ig_link=IG_LINK,
        cover_img_url=cover_img_url,
        base_url=BASE_URL,
    )

@app.route("/thumbnails/<filename>")
def serve_thumbnail(filename):
    path = os.path.join(THUMBNAIL_DIR, filename)
    if not os.path.exists(path):
        return "Not Found", 404

    response = make_response(send_file(path))
    response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
    return response

init_db()

thread = threading.Thread(target=save_files_periodically, daemon=True)
thread.start()
