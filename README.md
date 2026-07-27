# GitRAG: A Multi-User Repository Chatbot

GitRAG is a lightweight chatbot application designed to help developers query and discuss their GitHub repositories. By combining database indexing, keyword searches, and conversational memory, it allows users to log in, register their repositories, and ask questions about their code in a private and organized workspace.

---

## 📁 Folder Structure

Below is the directory layout of the GitRAG codebase:

```text
gitRAG/
├── app/
│   ├── api/
│   │   ├── auth.py          # Authentication middleware and session token tracking
│   │   ├── routes_ingest.py # Endpoints for repo ingestion and indexing status
│   │   └── routes_query.py  # Endpoints for hybrid query processing and history retrieval
│   ├── cache/
│   │   └── redis_client.py  # Upstash Redis cache and progress tracking client
│   ├── generation/
│   │   └── groq_client.py   # LLM generation via Groq API (llama-3.3-70b-versatile)
│   ├── ingestion/
│   │   ├── chunker.py       # Syntax-aware code chunker using Tree-Sitter
│   │   ├── diff_sync.py     # Hash-based incremental sync and diff checker
│   │   └── repo_loader.py   # Git cloning and repository file filters
│   ├── reranking/
│   │   └── reranker.py      # Cross-Encoder candidate reranker (BAAI/bge-reranker-base)
│   ├── retrieval/
│   │   ├── dense_search.py  # Qdrant client, collection init, and semantic vector search
│   │   ├── embeddings.py    # SentenceTransformers document/query embedding generator
│   │   └── sparse_search.py # TF-IDF vectorizer fitting and keyword search
│   ├── config.py            # Global Pydantic settings loading env values
│   ├── database.py          # SQLite connection manager and database schemas
│   └── main.py              # FastAPI application initialization and login routes
├── static/
│   ├── index.html           # Dark-mode dashboard frontend structure and login UI
│   ├── script.js            # User authentication, repository lists, and session chat scripts
│   └── style.css            # Glassmorphism dark-themed style configurations
├── temp/                    # Directory for temporary Git checkouts, SQLite, and chat histories
├── .env.example             # Template file documenting environment variables
├── requirements.txt         # Project python dependencies file
└── README.md                # System documentation
```

---

## 🛠️ Tech Stack

This project is built using a simple, modern stack:
*   **Web Framework**: FastAPI (Python 3.11+)
*   **User & Repository Database**: SQLite (`sqlite3`) to save user account credentials and manage repository lists.
*   **Vector Database**: Qdrant Cloud for storing code chunks and their semantic vectors.
*   **Embeddings**: HuggingFace SentenceTransformers (`BAAI/bge-base-en-v1.5`)
*   **Keyword Vectorizer**: Local Scikit-Learn `TfidfVectorizer` (trained dynamically per repository to catch exact terms).
*   **Reranking Model**: Cross-Encoder (`BAAI/bge-reranker-base`)
*   **Large Language Model**: Groq API (`llama-3.3-70b-versatile`)
*   **Code Parser**: Tree-Sitter (`tree-sitter-python`, `tree-sitter-javascript`)
*   **Frontend**: Plain HTML5, CSS3, and JavaScript (with a simple, dark glassmorphism design).
*   **Job Queue**: Redis & RQ (automatically falls back to FastAPI's built-in `BackgroundTasks` for local runs - in progression).

---

## 🚀 Features

*   **Hybrid Search**: Merges semantic meaning (dense vectors) with exact code keywords (sparse vectors) to find relevant code snippets.
*   **Reciprocal Rank Fusion (RRF)**: Combines keyword search rankings and vector search rankings into a single list.
*   **Cross-Encoder Reranking**: Refines the list of retrieved code snippets to ensure only the most relevant context is selected.
*   **Sigmoid Score Filtering**: Normalizes relevance scores to a clean `[0.0, 1.0]` percentage and filters out snippets below `0.35` (35%) similarity to keep results relevant and clean.
*   **Multi-User Dashboards**: Allows users to register accounts, log in, and view only their own indexed repositories.
*   **Session Auto-Logout**: Keeps session tokens in browser `sessionStorage` so users are automatically logged out when they close the browser tab or window.
*   **Conversational Memory**: Injects the last three turns of the chat history so you can ask follow-up questions naturally (e.g., using words like "it" or "this function").

---

## 🔄 How the System Works

### 1. Ingestion Pipeline
When you index a repository:
1. The server clones the repository locally (depth=1).
2. Tree-Sitter parses the files to find natural function and class boundaries, breaking the code into clean chunks.
3. HuggingFace BGE computes dense semantic vectors, and a local TF-IDF model compiles sparse keyword vectors.
4. The chunks and vectors are uploaded together to Qdrant Cloud.

### 2. Query & Retrieval Flow
When you ask a question:
1. The server checks the SQLite database to confirm you have indexed the repository on your account.
2. The server queries Qdrant using both dense and sparse searches.
3. RRF fuses the results, and the Cross-Encoder model reranks them.
4. Scores are mapped to a `[0.0, 1.0]` range using a sigmoid function. Any reference below `0.35` similarity is filtered out (with a fallback that always keeps the single best matching snippet).
5. The remaining high-relevance code snippets are sent to Groq alongside your question to generate the final response.

---

## 💻 Running the Server Locally

### 1. Configure Environment
Create a `.env` file in your project root directory:
```ini
ENV=development
TEMP_DIR=./temp
GROQ_API_KEY=your_groq_api_key
QDRANT_URL=https://your-qdrant-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your_qdrant_api_key_here
```

### 2. Install Dependencies
```cmd
pip install -r requirements.txt
```

### 3. Run the Server
```cmd
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser and navigate to **[http://127.0.0.1:8000/static/index.html](http://127.0.0.1:8000/static/index.html)** to create an account and start querying repositories!
