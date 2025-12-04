#!/usr/bin/env python3
"""Sync MongoDB data to Gorse - FIXED VERSION"""

from pymongo import MongoClient
import requests
from datetime import datetime
from bson import ObjectId
import time

# Config
GORSE_API = "http://localhost:8087/api"
MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "gorse_app"

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

def send_to_gorse(endpoint, data):
    try:
        url = f"{GORSE_API}/{endpoint}"
        response = requests.post(url, json=data, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

print("🚀 Starting sync...")

# Sync Users
print("\n📤 Syncing users...")
users = list(db.users.find())
user_data = []
for user in users:
    user_data.append({
        "UserId": str(user["_id"]),
        "Labels": ["user"]
    })
if user_data and send_to_gorse("users", user_data):
    print(f"✅ Synced {len(user_data)} users")

# Sync Posts (Feeds)
print("\n📤 Syncing posts...")
posts = list(db.feeds.find())
item_data = []
for post in posts:
    item_data.append({
        "ItemId": str(post["_id"]),
        "IsHidden": post.get("isDeleted", False),
        "Categories": ["post"],
        "Timestamp": post.get("createdAt", datetime.now()).isoformat()
    })
if item_data and send_to_gorse("items", item_data):
    print(f"✅ Synced {len(item_data)} posts")

# Sync Likes - FIXED to use userId field
print("\n📤 Syncing likes...")
likes = list(db.likes.find())
feedback_data = []
skipped = 0

for like in likes:
    try:
        # Try both userId and user fields
        user_id = like.get("userId") or like.get("user")
        target_id = like.get("targetId")
        
        # Skip if missing data
        if not user_id or not target_id:
            skipped += 1
            continue
        
        # Skip Refeed type (only want Feed/post type)
        if like.get("targetType") in ["Refeed", "refeed"]:
            continue
            
        feedback_data.append({
            "FeedbackType": "like",
            "UserId": str(user_id),
            "ItemId": str(target_id),
            "Timestamp": like.get("createdAt", datetime.now()).isoformat()
        })
    except Exception as e:
        skipped += 1
        continue

print(f"Found {len(feedback_data)} valid likes ({skipped} skipped)")

if feedback_data:
    batch_size = 100
    total_batches = (len(feedback_data) + batch_size - 1) // batch_size
    for i in range(0, len(feedback_data), batch_size):
        batch = feedback_data[i:i+batch_size]
        if send_to_gorse("feedback", batch):
            print(f"✅ Batch {i//batch_size + 1}/{total_batches}: {len(batch)} likes")
        time.sleep(0.5)

# Sync Comments
print("\n📤 Syncing comments...")
comments = list(db.comments.find())
feedback_data = []
skipped = 0

for comment in comments:
    try:
        user_id = comment.get("userId") or comment.get("user")
        target_id = comment.get("targetId") or comment.get("feedId") or comment.get("postId")
        
        if not user_id or not target_id:
            skipped += 1
            continue
        
        feedback_data.append({
            "FeedbackType": "comment",
            "UserId": str(user_id),
            "ItemId": str(target_id),
            "Timestamp": comment.get("createdAt", datetime.now()).isoformat()
        })
    except Exception as e:
        skipped += 1
        continue

print(f"Found {len(feedback_data)} valid comments ({skipped} skipped)")

if feedback_data:
    batch_size = 100
    total_batches = (len(feedback_data) + batch_size - 1) // batch_size
    for i in range(0, len(feedback_data), batch_size):
        batch = feedback_data[i:i+batch_size]
        if send_to_gorse("feedback", batch):
            print(f"✅ Batch {i//batch_size + 1}/{total_batches}: {len(batch)} comments")
        time.sleep(0.5)

print("\n✅ Sync complete!")
print("\n📊 Verify: curl http://localhost:8087/api/dashboard/stats")
print("🔄 Restart: docker restart gorse-master gorse-worker")
