import os
import logging
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS 
from pymongo import MongoClient
from bson import ObjectId
import redis
import hashlib
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("recommender")

MONGO_USER = quote_plus(os.getenv("MONGO_USER", "root"))
MONGO_PASS = quote_plus(os.getenv("MONGO_PASSWORD", "Mani@2003"))
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DBNAME = os.getenv("MONGO_DB", "gorse_app")
MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DBNAME}"

GORSE_URL = os.getenv("GORSE_URL", "http://localhost:8087/api")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

PORT = int(os.getenv("PORT", 5000))

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 20
MIN_PAGE_SIZE = 5
CACHE_TTL = 600  # 10 minutes
PRELOAD_BUFFER = 100

log.info("=" * 60)
log.info("🚀 GORSE-RECOMMENDATION ENGINE")
log.info("=" * 60)

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()  # Test connection
    db = mongo_client[MONGO_DBNAME]
    log.info("✓ MongoDB connected: %s", MONGO_HOST)
except Exception as e:
    log.error("✗ MongoDB connection failed: %s", e)
    raise

# MongoDB Collections - Your actual tables
users_col = db["users"]
feeds_col = db["feeds"]
likes_col = db["likes"]
comments_col = db["comments"]
refeeds_col = db["refeeds"]
reposts_col = db["reposts"]
follows_col = db["follows"]
saved_feeds_col = db["saved_feeds"]
watch_col = db["users_daily_activity"]
interests_col = db["userinterests"]
interactions_col = db["feedback"]
notifications_col = db["notifications"]
explore_feeds_col = db["explore_feeds"]
items_col = db["items"]
related_items_col = db["related_items"]

# Redis Connection with retry
REDIS_AVAILABLE = False
redis_client = None

def connect_redis(max_retries=3):
    global redis_client, REDIS_AVAILABLE
    for attempt in range(max_retries):
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30
            )
            redis_client.ping()
            REDIS_AVAILABLE = True
            log.info("✓ Redis connected: %s:%s (attempt %d)", REDIS_HOST, REDIS_PORT, attempt + 1)
            return True
        except redis.ConnectionError as e:
            log.warning("✗ Redis connection attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
    
    REDIS_AVAILABLE = False
    redis_client = None
    log.error("✗ Redis unavailable after %d attempts. Running WITHOUT cache.", max_retries)
    return False

connect_redis()

# Flask App
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ============= UTILITY FUNCTIONS =============
def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def get_cache_key(user_id, session_id=None):
    """Generate cache key for user's recommendation session"""
    if session_id:
        return f"rec_session:{user_id}:{session_id}"
    return f"rec_latest:{user_id}"

def cache_recommendations(user_id, recommendations, session_id=None):
    """Cache recommendations in Redis"""
    if not REDIS_AVAILABLE or not redis_client:
        return session_id or hashlib.md5(f"{user_id}{datetime.utcnow()}".encode()).hexdigest()[:16]
    
    try:
        key = get_cache_key(user_id, session_id)
        redis_client.setex(key, CACHE_TTL, json.dumps(recommendations))
        new_session = session_id or hashlib.md5(f"{user_id}{datetime.utcnow()}".encode()).hexdigest()[:16]
        log.info("📦 Cached %d recommendations for user %s (session: %s)", 
                 len(recommendations), user_id[:8], new_session[:8])
        return new_session
    except Exception as e:
        log.exception("cache_recommendations error: %s", e)
        return None

def get_cached_recommendations(user_id, session_id):
    """Get cached recommendations"""
    if not REDIS_AVAILABLE or not redis_client:
        return None
    
    try:
        key = get_cache_key(user_id, session_id)
        cached = redis_client.get(key)
        if cached:
            log.info("🎯 Cache HIT for user %s (session: %s)", user_id[:8], session_id[:8])
            return json.loads(cached)
        log.info("❌ Cache MISS for user %s (session: %s)", user_id[:8], session_id[:8])
        return None
    except Exception as e:
        log.exception("get_cached_recommendations error: %s", e)
        return None

def invalidate_user_cache(user_id):
    """Invalidate all cache for a user"""
    if not REDIS_AVAILABLE or not redis_client:
        return
    
    try:
        pattern = f"rec_session:{user_id}:*"
        deleted = 0
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)
            deleted += 1
        redis_client.delete(f"rec_latest:{user_id}")
        deleted += 1
        log.info("🗑️  Invalidated %d cache entries for user %s", deleted, user_id[:8])
    except Exception as e:
        log.warning("Failed to invalidate cache: %s", e)

def parse_gorse_items(resp):
    try:
        data = resp.json()
    except Exception:
        return []
    if isinstance(data, list):
        normalized = []
        for it in data:
            if isinstance(it, dict):
                iid = it.get("Id") or it.get("ItemId") or it.get("item_id") or it.get("id")
                score = it.get("Score") or it.get("score") or 0
                normalized.append({"item_id": iid, "cf_score": float(score)})
            else:
                normalized.append({"item_id": it, "cf_score": 0.0})
        return normalized
    return []

# ============= USER INTERACTION TRACKING =============
def get_user_seen_items(user_id):
    """Get items user has already interacted with"""
    seen = set()
    
    user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    if not user_oid:
        return seen
    
    # Items user liked
    for like in likes_col.find({"userId": user_oid}):
        feed_id = like.get("feedId")
        if feed_id:
            seen.add(str(feed_id))
    
    # Items user commented on
    for comment in comments_col.find({"userId": user_oid}):
        feed_id = comment.get("feedId")
        if feed_id:
            seen.add(str(feed_id))
    
    # Items user saved
    for saved in saved_feeds_col.find({"userId": user_oid}):
        feed_id = saved.get("feedId")
        if feed_id:
            seen.add(str(feed_id))
    
    # Items user reposted
    for repost in reposts_col.find({"userId": user_oid}):
        feed_id = repost.get("originalFeedId")
        if feed_id:
            seen.add(str(feed_id))
    
    # Watch history
    for activity in watch_col.find({"user_id": str(user_id)}):
        item_id = activity.get("item_id")
        if item_id:
            seen.add(item_id)
    
    log.info("👀 User %s: Excluding %d seen items", user_id[:8], len(seen))
    return seen

def get_user_created_items(user_id):
    """Get items created by the user"""
    created = set()
    
    user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    if not user_oid:
        return created
    
    for feed in feeds_col.find({"userId": user_oid}):
        created.add(str(feed["_id"]))
    
    log.info("✍️  User %s: Created %d posts", user_id[:8], len(created))
    return created

# ============= GORSE INTEGRATION =============
def send_feedback_to_gorse(user_id, item_id, feedback_type="like", timestamp=None):
    payload = [{
        "FeedbackType": feedback_type,
        "UserId": str(user_id),
        "ItemId": str(item_id),
        "Timestamp": timestamp or now_iso(),
    }]
    try:
        r = requests.post(f"{GORSE_URL}/feedback", json=payload, timeout=5)
        if r.status_code not in (200, 201):
            log.warning("Gorse feedback returned %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        log.exception("Gorse feedback failed: %s", e)

def get_gorse_recommendations(user_id, n=200):
    try:
        r = requests.get(f"{GORSE_URL}/recommend/{user_id}", params={"n": n}, timeout=6)
        if r.status_code == 200:
            items = parse_gorse_items(r)
            log.info("🤖 Gorse returned %d recommendations for user %s", len(items), user_id[:8])
            return items
        else:
            log.warning("Gorse recommend status %s: %s", r.status_code, r.text[:200])
            return []
    except Exception as e:
        log.exception("Gorse recommend error: %s", e)
        return []

def store_local_interaction(user_id, item_id, typ, extra=None):
    """Store in feedback table"""
    doc = {
        "user_id": str(user_id),
        "item_id": str(item_id),
        "type": typ,
        "extra": extra or {},
        "timestamp": datetime.utcnow()
    }
    try:
        interactions_col.insert_one(doc)
    except Exception as e:
        log.exception("store_local_interaction error: %s", e)

def update_popularity_from_redis(item_id):
    if not REDIS_AVAILABLE or not redis_client:
        return
    try:
        score = redis_client.zscore("trending_items", item_id) or 0
        items_col.update_one({"item_id": item_id}, {"$set": {"popularity_score": float(score)}}, upsert=True)
    except Exception as e:
        log.exception("update_popularity error: %s", e)

# ============= CANDIDATE GENERATION =============
def candidate_interest(user_id, limit=30):
    """Posts matching user's interests"""
    user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    if not user_oid:
        return []
    
    ui = interests_col.find_one({"userId": user_oid})
    if not ui:
        return []
    
    tags = ui.get("interests", []) or []
    if not tags:
        return []
    
    cursor = feeds_col.find({
        "hashtags": {"$in": tags},
        "status": "active"
    }).limit(limit)
    
    out = []
    for feed in cursor:
        out.append({
            "item_id": str(feed["_id"]),
            "content_score": 0.7,
            "category": "post",
            "popularity_score": feed.get("decayedPopularityScore", 0),
            "feed_data": feed
        })
    
    log.info("🎯 User %s: Found %d interest-based posts", user_id[:8], len(out))
    return out

def candidate_followed_users(user_id, limit=50):
    """Posts from followed users"""
    user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    if not user_oid:
        return []
    
    follows = follows_col.find({"followerId": user_oid, "status": "active"})
    followed = [f.get("followingId") for f in follows]
    
    if not followed:
        return []
    
    cursor = feeds_col.find({
        "userId": {"$in": followed},
        "status": "active"
    }).sort("createdAt", -1).limit(limit)
    
    out = []
    for feed in cursor:
        out.append({
            "item_id": str(feed["_id"]),
            "content_score": 0.9,
            "category": "post",
            "popularity_score": feed.get("decayedPopularityScore", 0),
            "feed_data": feed
        })
    
    log.info("👥 User %s: Found %d posts from followed users", user_id[:8], len(out))
    return out

def candidate_social_boost(user_id):
    """Posts liked by friends"""
    user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    if not user_oid:
        return []
    
    follows = follows_col.find({"followerId": user_oid, "status": "active"})
    friends = [f.get("followingId") for f in follows]
    
    if not friends:
        return []
    
    candidate_scores = {}
    
    for like in likes_col.find({"userId": {"$in": friends}}):
        feed_id = str(like.get("feedId"))
        candidate_scores[feed_id] = candidate_scores.get(feed_id, 0) + 0.5
    
    for comment in comments_col.find({"userId": {"$in": friends}}):
        feed_id = str(comment.get("feedId"))
        candidate_scores[feed_id] = candidate_scores.get(feed_id, 0) + 0.3
    
    log.info("💫 User %s: Found %d socially boosted posts", user_id[:8], len(candidate_scores))
    return [{"item_id": k, "social_score": v} for k, v in candidate_scores.items()]

def candidate_trending(limit=30):
    """Get trending posts"""
    cursor = explore_feeds_col.find({"status": "active"}).sort("popularityScore", -1).limit(limit)
    
    out = []
    for feed in cursor:
        feed_id = feed.get("feedId")
        if feed_id:
            out.append({
                "item_id": str(feed_id),
                "content_score": 0.5,
                "category": "post",
                "popularity_score": feed.get("popularityScore", 0)
            })
    
    log.info("🔥 Found %d trending posts", len(out))
    return out

# ============= SCORING FUNCTIONS =============
def compute_recency_score(item_doc):
    """Score based on post age"""
    ts = item_doc.get("createdAt")
    if not ts:
        return 0.2
    
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.utcnow()
    
    age_hours = (datetime.utcnow() - ts).total_seconds() / 3600.0
    
    if age_hours < 1:
        return 1.0
    elif age_hours < 24:
        return 0.8
    elif age_hours < 72:
        return 0.5
    else:
        return 0.2

def compute_hybrid(user_id, candidates):
    """Compute final hybrid score - Instagram algorithm"""
    social_map = {c["item_id"]: c.get("social_score", 0) for c in candidate_social_boost(user_id)}
    scored = []
    
    for c in candidates:
        iid = c["item_id"]
        
        if "feed_data" in c:
            item_doc = c["feed_data"]
            popularity = float(item_doc.get("decayedPopularityScore", 0) or 0)
        else:
            try:
                if ObjectId.is_valid(iid):
                    item_doc = feeds_col.find_one({"_id": ObjectId(iid)}) or {}
                    popularity = float(item_doc.get("decayedPopularityScore", 0) or 0)
                else:
                    item_doc = {}
                    popularity = 0.0
            except:
                item_doc = {}
                popularity = 0.0
        
        cf = float(c.get("cf_score", 0))
        content = float(c.get("content_score", 0))
        recency = compute_recency_score(item_doc)
        friend_boost = social_map.get(iid, 0)
        
        watch = watch_col.find_one({"user_id": str(user_id), "item_id": iid}) or {}
        watch_boost = 1.2 if watch.get("watch_time", 0) >= 5 else 1.0
        
        # Instagram-style scoring algorithm
        final = (
            0.35 * cf +              # ML collaborative filtering
            0.30 * content +          # Content similarity
            0.15 * recency +          # Post freshness
            0.10 * popularity +       # Global popularity
            0.10 * friend_boost       # Social signals
        )
        final = final * watch_boost
        
        scored.append({
            "item_id": iid,
            "score": round(float(final), 6),
            "category": c.get("category", "post"),
            "popularity": popularity,
            "feed_data": item_doc if item_doc else None
        })
    
    return sorted(scored, key=lambda x: x["score"], reverse=True)

def merge_candidates(candidate_lists):
    """Merge candidates from different sources"""
    merged = {}
    for list_ in candidate_lists:
        for c in list_:
            iid = c["item_id"]
            if iid not in merged:
                merged[iid] = c
            else:
                for key in ["cf_score", "content_score", "social_score"]:
                    if key in c:
                        merged[iid][key] = max(merged[iid].get(key, 0), c[key])
                if "feed_data" in c:
                    merged[iid]["feed_data"] = c["feed_data"]
    return list(merged.values())

def generate_recommendations_for_user(user_id, excluded_items):
    """Generate full personalized recommendation list"""
    log.info("🎬 Generating recommendations for user %s", user_id[:8])
    
    cands = []
    
    # Priority 1: Followed users
    cands += candidate_followed_users(user_id, limit=50)
    
    # Priority 2: User interests
    cands += candidate_interest(user_id, limit=30)
    
    # Priority 3: Gorse ML
    gorse_items = get_gorse_recommendations(user_id, n=PRELOAD_BUFFER)
    gorse_item_ids = [it["item_id"] for it in gorse_items]
    
    try:
        gorse_object_ids = [ObjectId(iid) for iid in gorse_item_ids if ObjectId.is_valid(iid)]
    except:
        gorse_object_ids = []
    
    excluded_oids = [ObjectId(x) for x in excluded_items if ObjectId.is_valid(x)]
    feeds_cursor = feeds_col.find({
        "_id": {"$in": gorse_object_ids, "$nin": excluded_oids},
        "status": "active"
    })
    feeds_map = {str(feed["_id"]): feed for feed in feeds_cursor}
    
    for it in gorse_items:
        iid = it["item_id"]
        if iid in excluded_items:
            continue
        
        feed = feeds_map.get(iid)
        if feed:
            popularity = feed.get("decayedPopularityScore", 0.0) or 0.0
            cands.append({
                "item_id": iid,
                "cf_score": float(it.get("cf_score", 0)),
                "category": "post",
                "popularity_score": float(popularity),
                "feed_data": feed
            })
    
    # Priority 4: Trending
    cands += candidate_trending(limit=20)
    
    # Priority 5: Related items
    for r in related_items_col.find({"user_id": str(user_id)}).sort("score", -1).limit(20):
        rel_item_id = r.get("related_item_id")
        if rel_item_id not in excluded_items:
            cands.append({
                "item_id": rel_item_id,
                "cf_score": float(r.get("score", 0))
            })
    
    # Priority 6: Social
    social = candidate_social_boost(user_id)
    for s in social:
        if s["item_id"] not in excluded_items:
            cands.append({"item_id": s["item_id"], "social_score": s["social_score"]})
    
    merged = merge_candidates([cands])
    recommendations = compute_hybrid(user_id, merged)
    
    log.info("✅ Generated %d recommendations for user %s", len(recommendations), user_id[:8])
    return recommendations, feeds_map

# ============= API ROUTES =============
@app.route("/")
def home():
    return jsonify({
        "service": "Gorse Recommendation Engine",
        "version": "2.0",
        "redis": "connected" if REDIS_AVAILABLE else "disconnected",
        "mongodb": "connected",
        "endpoints": {
            "recommend": "/recommend/<user_id>?page=1&limit=10",
            "feedback": "/feedback (POST)",
            "stats": "/debug/stats"
        }
    })
@app.route('/recommend')
def recommend_page():
    return render_template('recommend.html')

@app.route("/recommend/<user_id>", methods=["GET"])
def recommend(user_id):

    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", DEFAULT_PAGE_SIZE))
        session_id = request.args.get("session_id")
        refresh = request.args.get("refresh", "false").lower() == "true"
        
        # NEW: Personalization ratio (0.0 = all popular, 1.0 = all personalized)
        personalized_ratio = float(request.args.get("personalized_ratio", 0.7))
        personalized_ratio = max(0.0, min(1.0, personalized_ratio))  # Clamp 0-1
        
        if page < 1:
            page = 1
        if limit < MIN_PAGE_SIZE:
            limit = MIN_PAGE_SIZE
        if limit > MAX_PAGE_SIZE:
            limit = MAX_PAGE_SIZE
        
        start = (page - 1) * limit
        end = start + limit
        
        # Check cache
        if session_id and not refresh:
            cached = get_cached_recommendations(user_id, session_id)
            if cached:
                total_items = len(cached)
                paginated_items = cached[start:end]
                
                if end >= total_items and total_items < PRELOAD_BUFFER:
                    cached = None
                else:
                    return jsonify({
                        "user": user_id,
                        "page": page,
                        "limit": limit,
                        "session_id": session_id,
                        "total": total_items,
                        "has_more": end < total_items,
                        "results_count": len(paginated_items),
                        "recommendations": paginated_items,
                        "cache": "hit"
                    }), 200
        
        # Generate fresh
        seen_items = get_user_seen_items(user_id)
        created_items = get_user_created_items(user_id)
        excluded_items = seen_items | created_items
        
        # NEW: Get user's interaction history for better filtering
        user_liked_items = set()
        try:
            user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
            if user_oid:
                user_likes = likes_col.find({"userId": user_oid})
                user_liked_items = {str(like.get("targetId") or like.get("feedId")) 
                                   for like in user_likes if like.get("targetId") or like.get("feedId")}
        except Exception as e:
            log.warning(f"Could not fetch user likes: {e}")
        
        recommendations, feeds_map = generate_recommendations_for_user(user_id, excluded_items)
        
        # NEW: Categorize recommendations as popular vs personalized
        categorized_recs = []
        for rec in recommendations:
            # Check if this is likely a popular recommendation
            # (appears in top N for multiple users)
            is_popular = rec.get("popularity", 0) > 0.5  # Adjust threshold as needed
            rec["is_popular"] = is_popular
            categorized_recs.append(rec)
        
        # NEW: Apply personalization ratio
        popular_recs = [r for r in categorized_recs if r.get("is_popular")]
        personalized_recs = [r for r in categorized_recs if not r.get("is_popular")]
        
        # Calculate how many of each type to include
        total_needed = min(len(categorized_recs), PRELOAD_BUFFER)
        num_personalized = int(total_needed * personalized_ratio)
        num_popular = total_needed - num_personalized
        
        # Combine with desired ratio
        mixed_recommendations = (
            personalized_recs[:num_personalized] + 
            popular_recs[:num_popular]
        )
        
        # Shuffle to avoid all popular at top
        import random
        random.shuffle(mixed_recommendations)
        
        # If we don't have enough, fill with remainder
        if len(mixed_recommendations) < total_needed:
            remaining = [r for r in categorized_recs if r not in mixed_recommendations]
            mixed_recommendations.extend(remaining[:total_needed - len(mixed_recommendations)])
        
        # Get friend likes
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
        friend_map = {}
        
        if user_oid:
            follows = follows_col.find({"followerId": user_oid, "status": "active"})
            friends = [f.get("followingId") for f in follows]
            
            if friends:
                for like in likes_col.find({"userId": {"$in": friends}}):
                    feed_id = str(like.get("targetId") or like.get("feedId"))
                    user_who_liked = str(like.get("userId"))
                    friend_map.setdefault(feed_id, []).append(user_who_liked)
        
        # Build full list with enhanced metadata
        full_list = []
        for rec in mixed_recommendations:
            iid = rec["item_id"]
            feed = rec.get("feed_data") or feeds_map.get(iid)
            
            # NEW: Skip if user already liked this
            if iid in user_liked_items:
                continue
            
            recommendation = {
                "item_id": iid,
                "score": rec["score"],
                "category": rec.get("category", "post"),
                "friend_liked_by": friend_map.get(iid, []),
                "popularity": rec.get("popularity", 0),
                # NEW: Add recommendation reason
                "recommendation_type": "popular" if rec.get("is_popular") else "personalized"
            }
            
            if feed:
                recommendation["metadata"] = {
                    "text": (feed.get("text") or "")[:200],
                    "title": feed.get("title"),
                    "likes": feed.get("likeCount", 0),
                    "comments": feed.get("commentCount", 0),
                    "created_at": feed["createdAt"].isoformat() if feed.get("createdAt") else None
                }
            
            full_list.append(recommendation)
        
        new_session_id = cache_recommendations(user_id, full_list, session_id)
        
        total_items = len(full_list)
        paginated_items = full_list[start:end]
        
        # NEW: Add statistics
        stats = {
            "total_popular": sum(1 for r in full_list if r.get("recommendation_type") == "popular"),
            "total_personalized": sum(1 for r in full_list if r.get("recommendation_type") == "personalized"),
            "filtered_already_liked": len(user_liked_items & {r["item_id"] for r in recommendations}),
            "personalization_ratio": personalized_ratio
        }
        
        return jsonify({
            "user": user_id,
            "page": page,
            "limit": limit,
            "session_id": new_session_id,
            "total": total_items,
            "has_more": end < total_items,
            "results_count": len(paginated_items),
            "recommendations": paginated_items,
            "cache": "miss",
            "stats": stats  # NEW: Add recommendation statistics
        }), 200
        
    except Exception as e:
        log.exception("recommend error: %s", e)
        return jsonify({"error": str(e)}), 500


# NEW: Helper endpoint to adjust personalization on-the-fly
@app.route("/recommend/<user_id>/personalized", methods=["GET"])
def recommend_personalized(user_id):
    """Get highly personalized recommendations (80% personalized, 20% popular)"""
    request.args = request.args.copy()
    request.args["personalized_ratio"] = "0.8"
    return recommend(user_id)


@app.route("/recommend/<user_id>/popular", methods=["GET"])  
def recommend_popular(user_id):
    """Get mostly popular recommendations (20% personalized, 80% popular)"""
    request.args = request.args.copy()
    request.args["personalized_ratio"] = "0.2"
    return recommend(user_id)


@app.route("/recommend/<user_id>/balanced", methods=["GET"])
def recommend_balanced(user_id):
    """Get balanced recommendations (50% personalized, 50% popular)"""
    request.args = request.args.copy()
    request.args["personalized_ratio"] = "0.5"
    return recommend(user_id)

@app.route("/debug/stats", methods=["GET"])
def debug_stats():
    """Get system statistics"""
    try:
        stats = {
            "system": {
                "redis_available": REDIS_AVAILABLE,
                "mongodb_connected": True,
                "gorse_url": GORSE_URL
            },
            "collections": {
                "users": users_col.count_documents({}),
                "feeds": feeds_col.count_documents({}),
                "likes": likes_col.count_documents({}),
                "comments": comments_col.count_documents({}),
                "follows": follows_col.count_documents({}),
                "interactions": interactions_col.count_documents({})
            }
        }
        
        if REDIS_AVAILABLE and redis_client:
            stats["trending"] = redis_client.zrevrange("trending_items", 0, 9, withscores=True)
        
        return jsonify(stats), 200
    except Exception as e:
        log.exception("debug_stats error: %s", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    log.info("Starting Instagram-style Recommender on 0.0.0.0:%s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)