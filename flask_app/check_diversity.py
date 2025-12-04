# check_diversity.py - Fixed version
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['gorse_app']

print("📊 User Interaction Analysis\n")

# Total stats
total_users = db.users.count_documents({})
total_likes = db.likes.count_documents({})
total_posts = db.feeds.count_documents({})

print(f"Users: {total_users}")
print(f"Posts: {total_posts}")
print(f"Likes: {total_likes}")
print(f"Avg likes per user: {total_likes/total_users:.1f}\n")

# User distribution
pipeline = [
    {"$group": {"_id": "$user", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}  # Limit inside pipeline
]

print("Top 10 Most Active Users:")
for i, user in enumerate(db.likes.aggregate(pipeline), 1):
    print(f"{i}. User {str(user['_id'])[:8]}...: {user['count']} likes")

# Post distribution
pipeline = [
    {"$group": {"_id": "$targetId", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]

print("\nTop 10 Most Liked Posts:")
for i, post in enumerate(db.likes.aggregate(pipeline), 1):
    print(f"{i}. Post {str(post['_id'])[:8]}...: {post['count']} likes")

# Unique posts per user
pipeline = [
    {"$group": {"_id": "$user", "unique_posts": {"$addToSet": "$targetId"}}},
    {"$project": {"_id": 1, "count": {"$size": "$unique_posts"}}}
]

print("\nUnique Posts Liked Per User:")
results = list(db.likes.aggregate(pipeline))
if results:
    counts = [r['count'] for r in results]
    avg_unique = sum(counts) / len(counts)
    max_unique = max(counts)
    min_unique = min(counts)
    
    print(f"Average: {avg_unique:.1f} unique posts")
    print(f"Max: {max_unique} posts")
    print(f"Min: {min_unique} posts")

# Check concentration
unique_posts_liked = len(db.likes.distinct("targetId"))
print(f"\n📈 Coverage Analysis:")
print(f"Total posts with likes: {unique_posts_liked}/{total_posts}")
print(f"Coverage: {unique_posts_liked/total_posts*100:.1f}%")

# Users with zero likes
users_with_likes = len(db.likes.distinct("user"))
users_without_likes = total_users - users_with_likes
print(f"\n👥 User Engagement:")
print(f"Users with likes: {users_with_likes}")
print(f"Users without likes: {users_without_likes}")

# Check if recommendations are diverse
print("\n🎯 Recommendation Diversity Check:")
if unique_posts_liked < 100:
    print("⚠️ WARNING: Very few posts liked - low diversity!")
elif unique_posts_liked < 500:
    print("⚠️ WARNING: Limited post diversity")
else:
    print("✅ Good post diversity")

if avg_unique < 10:
    print("⚠️ WARNING: Users like very few unique posts")
elif avg_unique < 50:
    print("⚠️ Moderate user diversity")
else:
    print("✅ Good user diversity")