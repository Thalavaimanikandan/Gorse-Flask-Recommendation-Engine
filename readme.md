# Gorse + Flask + MongoDB + Redis Production Setup

This repository contains a Gorse recommendation system using **Gorse**, **MongoDB**, **Redis**, and **Flask**.

---

## **1. Prerequisites**

- Docker & Docker Compose
- Python 3.10+
- pip

---

## **2. Docker Containers**

We will run the following services:

| Service     | Port     | Notes                           |
|------------|---------|--------------------------------|
| MySQL      | 3306    | For Gorse metadata             |
| Redis      | 6379    | Cache and trending items       |
| Gorse Master | 8086   | Gorse recommendation engine    |
| Gorse Server | 8087   | Gorse API server               |
| Gorse Dashboard | 8088| Gorse UI                       |
| MongoDB    | 27017   | User activity & items database |

---

## **3. Docker Compose Example**

```yaml
version: "3.8"

services:
  gorse-mysql:
    image: mysql:8
    container_name: gorse-mysql
    environment:
      MYSQL_ROOT_PASSWORD: gorse_pass
      MYSQL_DATABASE: gorse
      MYSQL_USER: gorse_user
      MYSQL_PASSWORD: gorse_pass
    ports:
      - "3306:3306"
    volumes:
      - gorse-mysql-data:/var/lib/mysql

  gorse-redis:
    image: redis:6
    container_name: gorse-redis
    ports:
      - "6379:6379"

  gorse-master:
    image: go-gorse/gorse:latest
    container_name: gorse-master
    depends_on:
      - gorse-mysql
      - gorse-redis
    ports:
      - "8086:8086"
      - "8088:8088"
    volumes:
      - ./config.toml:/etc/gorse/config.toml

  gorse-server:
    image: go-gorse/gorse:latest
    container_name: gorse-server
    depends_on:
      - gorse-master
    ports:
      - "8087:8087"

  mongo:
    image: mongo:latest
    container_name: gorse-mongo
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: Mani@2003

volumes:
  gorse-mysql-data:
````

---

## **4. Flask App Configuration**

* Install requirements:

```bash
pip install -r requirements.txt
```

* `.env` or `config.py` settings:

```python
# MySQL / Gorse
DB_USER = 'gorse_user'
DB_PASSWORD = 'gorse_pass'
DB_HOST = 'gorse-mysql'
DB_NAME = 'gorse'
SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

# MongoDB
MONGO_USER = 'root'
MONGO_PASS = 'Mani@2003'
MONGO_HOST = 'mongo'
MONGO_PORT = 27017
MONGO_DB = 'gorse_app'

# Redis
REDIS_HOST = 'gorse-redis'
REDIS_PORT = 6379
```

* Flask app run:

```bash
python app.py
```

* API Endpoints:

| Endpoint               | Method | Description          |
| ---------------------- | ------ | -------------------- |
| `/add_user`            | POST   | Add a user           |
| `/add_item`            | POST   | Add item/content     |
| `/feedback`            | POST   | Submit user feedback |
| `/activity`            | POST   | Log user activity    |
| `/recommend/<user_id>` | GET    | Get recommendations  |

---

## **5. Requirements (requirements.txt)**

```txt
Flask==2.3.4
Flask-SQLAlchemy==3.0.5
pymysql==1.1.1
pymongo==4.7.1
redis==5.3.7
requests==2.31.0
python-dotenv==1.0.1
```

---

## **6. Notes for Production**

1. **Docker Network**: Ensure all services are in same Docker network for hostname connectivity (`gorse-mysql`, `gorse-redis`, `mongo`, etc.)
2. **Separate DB per user (Optional)**: Use `get_user_db(user_id)` to maintain user-specific MongoDB databases.
3. **Gorse Configuration**: `config.toml` must match the Docker service hostnames.
4. **Security**: Replace default passwords, enable SSL for Redis/MySQL in production.
5. **Scaling**: Gorse workers and servers can be scaled for higher throughput.

```

---

✅ **Summary:**

- Ithu **full production setup** for **Gorse + Flask + MongoDB + Redis**.
- Requirements file ready (`requirements.txt`).
- All hostnames & ports match **Docker network**.  
- Flask app can log **per-user activity**, fetch recommendations from **Gorse**, and store content/user data in MongoDB.

---


