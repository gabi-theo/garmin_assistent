# Architecture

## 1. Component overview

```mermaid
flowchart LR
    UI["React Frontend"]

    subgraph APP["FastAPI app<br/>(API + Kafka consumer + LangGraph agent)"]
        API["REST / SSE / WebSocket"]
    end

    subgraph CELERY["Celery"]
        BEAT["Beat scheduler"]
        WORKER["Worker"]
    end

    GARMIN[("Garmin Connect")]
    KAFKA[("Kafka")]
    REDIS[("Redis")]
    DB[("TimescaleDB")]
    OLLAMA[("Ollama LLM")]

    UI <--> API
    API <--> REDIS
    API <--> DB
    API <--> OLLAMA
    API -->|"trigger immediate poll"| WORKER

    BEAT --> WORKER
    WORKER --> GARMIN
    WORKER --> KAFKA
    WORKER --> REDIS

    KAFKA --> API
```

## 2. Background polling & ingestion pipeline

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Worker as Celery Worker
    participant Garmin as Garmin Connect API
    participant Kafka
    participant Consumer as Kafka Consumer
    participant Redis
    participant Agent as LangGraph Agent
    participant Ollama
    participant DB as TimescaleDB
    participant WS as WebSocket client

    Beat->>Worker: poll_user_task (every GARMIN_POLL_INTERVAL)
    Worker->>Garmin: fetch_all_metrics()
    Garmin-->>Worker: metrics
    Worker->>Kafka: publish_metric()
    Worker->>Redis: update poller_status

    Kafka->>Consumer: telemetry event
    Consumer->>Redis: acquire lock + cache_metric()
    Consumer->>Agent: invoke graph

    Agent->>Redis: detect_anomaly (rolling stats)
    alt anomaly detected
        Agent->>Redis: retrieve_history
        Agent->>Ollama: generate_insight
        Ollama-->>Agent: insight text
    end
    Agent->>DB: persist insight + profile snapshot
    Agent->>Redis: publish live event
    Redis-->>WS: push update

    Note over Redis,DB: Redis cache is also flushed to<br/>TimescaleDB every 60s by a background task
```

## 3. User-facing API

```mermaid
flowchart LR
    UI["Frontend"]

    UI -->|"REST"| AUTH["/auth"]
    UI -->|"REST"| METRICS["/metrics/{metric}"]
    UI -->|"REST"| INSIGHTS["/insights/latest"]
    UI -->|"SSE"| CHAT["/chat"]
    UI -->|"WebSocket"| WS["/ws/live"]
    UI -->|"REST"| HEALTH["/health"]

    AUTH --> DB[("TimescaleDB")]
    AUTH --> SESS[("Redis: sessions")]
    AUTH -.->|"save Garmin creds"| WORKER["Celery: poll_user_task"]

    METRICS -->|"<=24h"| CACHE[("Redis: metric cache")]
    METRICS -->|">24h"| DB

    INSIGHTS --> DB

    CHAT --> AGENT["LangGraph Agent"] --> OLLAMA[("Ollama")]

    WS --> PUBSUB[("Redis: pub/sub")]
    HEALTH --> WORKER
    HEALTH --> STATUS[("Redis: poller_status")]
```

## Two main flows

1. **Background ingestion** (diagram 2): Celery Beat ticks every `GARMIN_POLL_INTERVAL` and dispatches `poll_user_task` per user. Each task fetches data from Garmin, publishes it to Kafka, and the consumer caches it in Redis and runs the LangGraph agent (anomaly detection, optional Ollama insight, persistence to TimescaleDB, and a live event over Redis pub/sub to WebSocket clients).
2. **User-facing API** (diagram 3): the frontend hits `/auth`, `/metrics`, `/insights`, `/chat` (SSE, runs the same LangGraph agent in chat mode against Ollama), and `/ws/live` (subscribes to the per-user pub/sub channel for real-time updates).
