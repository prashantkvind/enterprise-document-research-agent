# Comprehensive Deployment & Testing Guide

This guide provides step-by-step instructions for setting up, running, testing, and deploying the **Enterprise Document Research Agent (ERA)** both **locally on a laptop** and on **Google Cloud Platform (GCP)**.

---

# Part 1: Local Setup, Execution & Testing (Laptop)

## Prerequisites
- **Python 3.10+**
- **Docker & Docker Compose** (optional, for containerized local execution)
- **PostgreSQL Database** (local instance or Docker container)
- **OpenAI API Key** (with access to GPT-4 Turbo & `text-embedding-ada-002`)
- **Pinecone API Key** & Index name
- **Google Drive API OAuth 2.0 Credentials** (`credentials.json` downloaded from Google Cloud Console)

---

## Step 1: Environment Configuration

1. Clone or extract the project repository into your local directory.
2. Copy `.env` and fill in your actual credentials:
   ```bash
   cp .env .env.local
   ```
3. Update `.env` with your keys:
   ```env
   OPENAI_API_KEY=sk-...
   PINECONE_API_KEY=pcsk_...
   PINECONE_INDEX_NAME=era-index

   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=era_db
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=your_password

   GDRIVE_FOLDER_ID=1A2b3C4d5E6f7G8h9I0j
   SIMILARITY_THRESHOLD=0.75
   PORT=8000
   ```

---

## Step 2: Set Up Local PostgreSQL Database

If using a local PostgreSQL container:
```bash
docker run --name era-postgres \
  -e POSTGRES_DB=era_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d postgres:15
```

Initialize the database schema:
```bash
psql -h localhost -U postgres -d era_db -f database_setup.sql
```

---

## Step 3: Install Python Dependencies

Create a virtual environment and install packages:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Step 4: Run Google Drive Document Ingestion

1. Place your Google Cloud OAuth client secret file named `credentials.json` in the root directory.
2. Run the ingestion pipeline:
   ```bash
   python ingestion_service.py
   ```
3. On the first run, a browser window will open requesting Google Drive read authorization. Complete the OAuth prompt.
4. A token file (`token.json`) will be generated automatically.
5. Ingestion will download documents, split text into 1000-character chunks, generate embeddings, upsert vectors to Pinecone, and store citation metadata in PostgreSQL.

---

## Step 5: Start the Agent Web Service

Run locally with Python:
```bash
python agent_service.py
```
Or with Uvicorn directly:
```bash
uvicorn agent_service:app --host 0.0.0.0 --port 8000 --reload
```

---

## Step 6: Test the Local API

### A. Health Check
```bash
curl http://localhost:8000/health
```

### B. Internal RAG Query (Document Search)
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the key objective mentioned in our strategic roadmap document?"}'
```

### C. Fallback Query (External Web Search)
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the current stock price of Apple today?"}'
```

### D. Interactive Swagger UI
Open your web browser and navigate to:
[http://localhost:8000/docs](http://localhost:8000/docs)

---

## Step 7: Run via Local Docker Container

Build the container image:
```bash
docker build -t era-agent:latest .
```

Run the container:
```bash
docker run -p 8000:8000 --env-file .env era-agent:latest
```

---

# Part 2: Production Deployment on Google Cloud Platform (GCP)

We deploy ERA using serverless cloud-native architecture on GCP:
- **Compute**: Cloud Run (Serverless container deployment for `agent_service`).
- **Database**: Cloud SQL for PostgreSQL.
- **Secrets Management**: Secret Manager.
- **Container Registry**: Artifact Registry.
- **Scheduled Ingestion**: Cloud Run Jobs + Cloud Scheduler.

```
                  +-----------------------------------+
                  |        GCP Cloud Scheduler        |
                  +-----------------+-----------------+
                                    | Triggers
                                    v
                  +-----------------+-----------------+
                  |         Cloud Run Job             |
                  |     (ingestion_service.py)        |
                  +-----------------+-----------------+
                                    |
                                    v
+--------------+  HTTPS   +---------+---------+  VPC    +-------------------+
|  API Client  +--------->|  GCP Cloud Run    +-------->|  GCP Cloud SQL    |
+--------------+          |  (agent_service)  | Direct  |   (PostgreSQL)    |
                          +--------+----------+ Egress  +-------------------+
                                   |
                                   +-------------------> External APIs
                                                         (Pinecone & OpenAI)
```

---

## Prerequisites for GCP
1. Google Cloud Project with billing enabled.
2. `gcloud` CLI installed and authenticated (`gcloud auth login`).
3. Set your project ID:
   ```bash
   export GCP_PROJECT_ID="your-gcp-project-id"
   export GCP_REGION="us-central1"
   gcloud config set project $GCP_PROJECT_ID
   ```

---

## Step 1: Enable Required GCP APIs
```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  vpcaccess.googleapis.com
```

---

## Step 2: Set Up Cloud SQL for PostgreSQL

1. Create a Cloud SQL instance:
   ```bash
   gcloud sql instances create era-postgres-db \
     --database-version=POSTGRES_15 \
     --cpu=1 \
     --memory=3840MiB \
     --region=$GCP_REGION \
     --root-password="YourSecureDbPassword123!"
   ```

2. Create the `era_db` database:
   ```bash
   gcloud sql databases create era_db --instance=era-postgres-db
   ```

3. Connect and apply `database_setup.sql`:
   ```bash
   gcloud sql connect era_db --user=postgres < database_setup.sql
   ```

---

## Step 3: Configure Secret Manager

Store sensitive environment keys in Secret Manager:
```bash
# OpenAI Key
echo -n "sk-..." | gcloud secrets create OPENAI_API_KEY --data-file=-

# Pinecone Key
echo -n "pcsk_..." | gcloud secrets create PINECONE_API_KEY --data-file=-

# Postgres Password
echo -n "YourSecureDbPassword123!" | gcloud secrets create POSTGRES_PASSWORD --data-file=-
```

---

## Step 4: Build and Push Docker Image to Artifact Registry

1. Create Artifact Registry repository:
   ```bash
   gcloud artifacts repositories create era-repo \
     --repository-format=docker \
     --location=$GCP_REGION \
     --description="Docker repository for Enterprise Document Research Agent"
   ```

2. Authenticate Docker with GCP:
   ```bash
   gcloud auth configure-docker $GCP_REGION-docker.pkg.dev
   ```

3. Build and push image:
   ```bash
   IMAGE_URI="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/era-repo/agent-service:latest"
   
   docker build -t $IMAGE_URI .
   docker push $IMAGE_URI
   ```

---

## Step 5: Deploy Agent Service to Cloud Run

Deploy the container with environment variables, Cloud SQL connection, and secret bindings:

```bash
gcloud run deploy era-agent-service \
  --image=$IMAGE_URI \
  --platform=managed \
  --region=$GCP_REGION \
  --allow-unauthenticated \
  --port=8000 \
  --set-env-vars="POSTGRES_HOST=/cloudsql/$GCP_PROJECT_ID:$GCP_REGION:era-postgres-db,POSTGRES_PORT=5432,POSTGRES_DB=era_db,POSTGRES_USER=postgres,PINECONE_INDEX_NAME=era-index,GDRIVE_FOLDER_ID=your_gdrive_folder_id,SIMILARITY_THRESHOLD=0.75" \
  --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest,POSTGRES_PASSWORD=POSTGRES_PASSWORD:latest" \
  --add-cloudsql-instances="$GCP_PROJECT_ID:$GCP_REGION:era-postgres-db"
```

Once deployment completes, `gcloud` will output your live HTTPS service URL:
`https://era-agent-service-xxxxxx-uc.a.run.app`

---

## Step 6: Test Cloud Run Deployment

Test the live Cloud Run URL:
```bash
export SERVICE_URL="https://era-agent-service-xxxxxx-uc.a.run.app"

# Health Check
curl $SERVICE_URL/health

# Post Query
curl -X POST $SERVICE_URL/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are our Q3 business goals?"}'
```

---

## Step 7: Deploy Automated Ingestion Job on GCP

To run document ingestion on GCP on a schedule:

1. Create a Cloud Run Job for `ingestion_service.py`:
   ```bash
   gcloud run jobs create era-ingestion-job \
     --image=$IMAGE_URI \
     --region=$GCP_REGION \
     --command="python" \
     --args="ingestion_service.py" \
     --set-env-vars="POSTGRES_HOST=/cloudsql/$GCP_PROJECT_ID:$GCP_REGION:era-postgres-db,POSTGRES_PORT=5432,POSTGRES_DB=era_db,POSTGRES_USER=postgres,PINECONE_INDEX_NAME=era-index,GDRIVE_FOLDER_ID=your_gdrive_folder_id" \
     --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest,POSTGRES_PASSWORD=POSTGRES_PASSWORD:latest" \
     --add-cloudsql-instances="$GCP_PROJECT_ID:$GCP_REGION:era-postgres-db"
   ```

2. Schedule the ingestion job to run daily using Cloud Scheduler:
   ```bash
   gcloud scheduler jobs create http era-daily-ingestion \
     --schedule="0 2 * * *" \
     --time-zone="America/New_York" \
     --uri="https://$GCP_REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/era-ingestion-job:run" \
     --http-method=POST \
     --oauth-service-account-email="$GCP_PROJECT_ID-compute@developer.gserviceaccount.com"
   ```
