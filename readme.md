# Gorse + Flask + MongoDB + Redis Recommendation Engine 🚀

This repository contains a full setup of a recommendation engine using **Gorse** (the core recommender engine), along with a **Flask** application, **MongoDB** (for items/users storage), **MySQL**, and **Redis** — all configured via Docker Compose.  
It lets you add users/items, log feedback/activity, fetch personalized recommendations, and run a web-service around that.

---

## 📦 Features / What this repo provides

- Full production-ready stack with Docker Compose  
- RESTful endpoints to:  
  - Add users & items  
  - Submit feedback & user activity  
  - Return recommendations per user  
- Use of MongoDB for storing user/content data  
- MySQL (or other DB) + Gorse for metadata, recommendation training, and serving  
- Redis for caching / trending items / faster recommendation serving  
- Configurable via `config.toml`, Flask settings or environment variables  

---

## 🧰 Prerequisites

- Docker & Docker Compose installed  
- Python 3.10+  
- `pip` (for installing Flask-app dependencies)

---

## 🐳 Docker Compose Setup (Services & Ports)

The following services get created via `docker-compose.yml`:

| Service / Container | Port | Purpose / Notes |
|---------------------|------|------------------|
| `gorse-mysql`       | 3306 | Metadata DB for Gorse engine |
| `gorse-redis`       | 6379 | Cache + trending items & fast data access |
| `gorse-master`      | 8086 / 8088 | Gorse recommendation engine (master + dashboard) |
| `gorse-server`      | 8087 | Gorse REST API server |
| `mongo`             | 27017 | Storing user data, items/content for the Flask app |

Example `docker-compose.yml` is already provided in the repo.

---

## ⚙️ Flask App Configuration & Running

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
````

2. Configure environment variables or edit `config.py`:

   ```python
   # Example settings
   DB_USER = 'gorse_user'
   DB_PASSWORD = 'gorse_pass'
   DB_HOST = 'gorse-mysql'
   DB_NAME = 'gorse'
   SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

   MONGO_USER = 'root'
   MONGO_PASS = 'your_mongo_password'
   MONGO_HOST = 'mongo'
   MONGO_PORT = 27017
   MONGO_DB = 'gorse_app'

   REDIS_HOST = 'gorse-redis'
   REDIS_PORT = 6379
   ```
3. Start the Flask app:

   ```bash
   python app.py
   ```

### 📡 API Endpoints

| Endpoint               | Method | Description                                       |
| ---------------------- | ------ | ------------------------------------------------- |
| `/add_user`            | POST   | Add/register a new user                           |
| `/add_item`            | POST   | Add a new item/content                            |
| `/feedback`            | POST   | Submit user feedback (like / dislike / view etc.) |
| `/activity`            | POST   | Log user activity (optional)                      |
| `/recommend/<user_id>` | GET    | Get recommended items for the given user          |

---

## 📄 Sample `requirements.txt`

```text
Flask==2.3.4
Flask-SQLAlchemy==3.0.5
pymysql==1.1.1
pymongo==4.7.1
redis==5.3.7
requests==2.31.0
python-dotenv==1.0.1
```

---

## ✅ Production / Deployment Notes

* Ensure all services (MySQL, Redis, Mongo, Gorse) are on the same Docker network so hostnames resolve as configured
* Use strong credentials instead of defaults — especially for MySQL & Mongo
* Consider enabling SSL / TLS for external-facing services (DB, Redis)
* For scalability: scale Gorse worker/server containers depending on load
* Use separate databases per user or logical partitioning (optional) for multi-tenant / user-specific data

---

## 🔍 About

This project integrates the power of Gorse (a scalable open-source recommendation engine) with a Flask-based web interface + MongoDB data store, allowing easy customization, extension, and production deployments.

---

## 📝 License & Contributions

Feel free to use, modify, and contribute. Pull requests and issues are welcome.


