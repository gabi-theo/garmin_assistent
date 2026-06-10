# Architecture

```mermaid
flowchart TB
    UI["React Frontend"]

    subgraph API["FastAPI (app/main.py)"]
        AUTH["/auth<br/>register, login, garmin creds, logout"]
        METRICSAPI["/metrics/{metric}"]
        INSIGHTSAPI["/insights/latest"]
        CHATAPI["/chat (SSE)"]
        WSAPI["/ws/live (WebSocket)"]
        HEALTHAPI["/health/status, /health/poll"]
    end

    subgraph CELERY["Celery"]
        BEAT["celery_beat<br/>poll_all_users_task<br/>every GARMIN_POLL_INTERVAL"]
        WORKER["celery_worker<br/>poll_user_task"]
    end

    RUNPOLL["run_poll_cycle()<br/>(app/garmin/poller.py)"]
    GARMIN["Garmin Connect API"]
    KAFKA["Kafka topic<br/>garmin.&lt;metric&gt;.&lt;user_id&gt;"]
    CONSUMER["Kafka consumer loop"]

    subgraph AGENT["LangGraph Agent"]
        direction TB
        N1["ingest_metrics"] --> N2["detect_anomaly"]
        N2 -->|"anomaly"| N3["retrieve_history"]
        N2 -->|"no anomaly"| N5["persist_results"]
        N3 --> N4["generate_insight (Ollama)"]
        N4 -->|"chat mode"| DONE(("END"))
        N4 -->|"ingest pipeline"| N5
    end

    OLLAMA["Ollama LLM"]

    subgraph REDIS["Redis"]
        SESS["sessions"]
        CACHE["metrics:* sorted sets + flush queue"]
        STATUS["poller_status:*"]
        LOCK["agent locks"]
        PUBSUB["live:* pub/sub"]
    end

    subgraph TSDB["TimescaleDB"]
        USERS["users"]
        METRICSTBL["metrics (hypertable)"]
        INSIGHTSTBL["insights"]
        SNAPSHOT["profile_snapshots"]
    end

    FLUSH["Cache flusher (60s)"]

    %% Frontend <-> API
    UI <--> AUTH
    UI <--> METRICSAPI
    UI <--> INSIGHTSAPI
    UI <--> CHATAPI
    UI <--> WSAPI
    UI <--> HEALTHAPI

    %% Auth
    AUTH --> USERS
    AUTH --> SESS
    AUTH -->|"save garmin creds<br/>poll_user_task.delay()"| WORKER

    %% Polling pipeline
    BEAT -->|"users with creds"| USERS
    BEAT --> WORKER
    WORKER --> RUNPOLL
    HEALTHAPI -->|"manual poll (in-process)"| RUNPOLL
    STATUS --> HEALTHAPI

    RUNPOLL -->|"fetch_all_metrics"| GARMIN
    RUNPOLL --> STATUS
    RUNPOLL -->|"publish_metric"| KAFKA

    %% Ingestion -> Agent
    KAFKA --> CONSUMER
    CONSUMER --> LOCK
    CONSUMER --> CACHE
    CONSUMER --> N1

    %% Chat path enters agent directly
    CHATAPI -->|"chat_mode=true"| N3

    %% Agent <-> Ollama
    N4 <--> OLLAMA

    %% Persist + live push
    N5 --> INSIGHTSTBL
    N5 --> SNAPSHOT
    N5 --> PUBSUB
    N5 --> LOCK
    PUBSUB --> WSAPI

    %% Reads
    METRICSAPI -->|"<=24h"| CACHE
    METRICSAPI -->|">24h"| METRICSTBL
    INSIGHTSAPI --> INSIGHTSTBL

    %% Background flush
    CACHE --> FLUSH --> METRICSTBL
```

## Two main flows

1. **Background ingestion**: Celery Beat ticks every `GARMIN_POLL_INTERVAL` and dispatches `poll_user_task` per user. Each task fetches data from Garmin, publishes it to Kafka, and the consumer caches it in Redis and runs the LangGraph agent (anomaly detection, optional Ollama insight, persistence to TimescaleDB, and a live event over Redis pub/sub to WebSocket clients).
2. **User-facing API**: the frontend hits `/auth`, `/metrics`, `/insights`, `/chat` (SSE, runs the same LangGraph agent in chat mode against Ollama), and `/ws/live` (subscribes to the per-user pub/sub channel for real-time updates).
