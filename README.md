# Website Qualitative Analysis Tool

A sophisticated qualitative analysis framework for conducting in-depth, systematic analysis of website content, structure, and user experience elements.

## Overview

Website-Q-A is a comprehensive qualitative analysis platform designed to extract, process, and analyze website characteristics across multiple dimensions. The system enables researchers, UX specialists, and analysts to perform detailed qualitative assessments of websites through both automated processing and agent-based analysis workflows.

## Features

- 🕷️ **BFS Crawler**: Traverses entire websites or specific paths with depth control.
- 📊 **Multi-Dimensional Analysis**: Evaluates HTTP status, redirects, performance, and layout integrity (Desktop & Mobile).
- 🤖 **AI-Powered QA**: Uses Gemini Pro to perform intelligent form testing, content verification, and root cause diagnosis.
- 🚀 **Production-Ready API**: Enqueue long-running QA tasks and fetch reports asynchronously.
- 💾 **Scalable Storage**: Job results are stored on disk to optimize memory usage.
- ⚙️ **Centralized Config**: Manage everything from `config.yaml` or Environment variables.

## Installation
## Clone the repository
```bash
git clone https://github.com/AliHaSSan-13/Website-Q-A.git
cd Website-Q-A 
```

### 1. Set Up Environment
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
```

### 2. Configure API Key(s)
Create a `.env` file in the root directory. **Gemini is used by default**; **OpenAI is used as fallback** if the Gemini key is missing or Gemini calls fail.

```env
GEMINI_API_KEY=your_gemini_api_key_here
# Optional fallback when Gemini is unavailable or fails:
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Further documentation
- **[TESTING_AND_DEPLOYMENT.md](TESTING_AND_DEPLOYMENT.md)** — How to run the system (CLI + API), run tests, and deploy (Railway, Docker, production).
- **[CODEBASE_EXPLANATION.md](CODEBASE_EXPLANATION.md)** — Full codebase reference and architecture.

---

## 🖥️ CLI Usage

Run a quick scan directly from your terminal:

```bash
python qa_tool.py --url https://example.com --max-pages 5 --max-depth 2 --headless
```

**Arguments:**
- `--url`: Starting URL (Required).
- `--max-pages`: Max internal pages to crawl (Default: Unlimited).
- `--max-depth`: Max crawl depth (Default: Unlimited).
- `--headless / --no-headless`: Run browser with or without UI.
- `--interactive`: Manually provide form inputs during the crawl.

---

## 🌐 API Usage (Production)

Start the API server:
```bash
python app.py
```
By default, the server runs on `http://localhost:8000`.

### 1. Start a QA Job
Submit a website for analysis. This is an asynchronous operation.

**Endpoint:** `POST /api/run-qa`

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/run-qa \
     -H "Content-Type: application/json" \
     -d '{
           "url": "https://practice.qabrains.com/registration",
           "max_pages": 1,
           "max_depth": 0,
           "run_ai": true,
           "timeout_seconds": 300
         }'
```

**Parameters:**
- `url` (string, required): Target URL.
- `max_pages` (int, optional): Limit internal pages.
- `max_depth` (int, optional): Limit crawl depth.
- `run_ai` (bool, optional): Enable AI analysis (Default: true).
- `timeout_seconds` (int, optional): Max time for the job (0 for no timeout).

**Response:**
Returns a `job_id` used to track progress.

### 2. Check Job Status & Results
Poll this endpoint to see if the job is finished.

**Endpoint:** `GET /api/status/<job_id>`

**Example Request:**
```bash
curl http://localhost:8000/api/status/YOUR_JOB_ID_HERE
```

**Response:**
- `status: "pending"`: In queue.
- `status: "running"`: Crawling and analyzing.
- `status: "success"`: Data is ready (includes `result` object).
- `status: "failed"`: Error details included in `error` field.

---

## ⚙️ Advanced Configuration

Most settings are managed in `config.yaml`.

```yaml
gemini:
  model: "gemini-2.5-flash"
  max_steps: 15

browser:
  headless: true
  nav_timeout_ms: 30000
  viewports:
    desktop: { width: 1920, height: 1080 }
    mobile: { width: 375, height: 812 }

api:
  port: 8000
  results_dir: "job_results"  # Folder where JSON reports are saved
```

---

## 🚂 Deployment to Railway

Railway is the recommended platform for this tool because it supports long-running background threads and persistent volumes.

### 1. Simple Deploy
1. Link your GitHub repository to [Railway.app](https://railway.app).
2. Railway will automatically detect the `Procfile` and `nixpacks.toml`.
3. Add your `GEMINI_API_KEY` to the **Variables** tab in Railway.

### 2. Enable Persistent Storage (CRITICAL)
By default, Railway's file system is temporary. To keep your results and job database after a restart:
1. Go to your Railway project.
2. Click **+ New** -> **Volume**.
3. Mount the volume to `/app/data`.
4. Update `config.yaml` or set environment variable `API__DB_PATH` to `/app/data/jobs.db`.
5. (Optional) Create another volume for `/app/crawl_results` if you use the CLI.

### 3. Build Configuration
The included `nixpacks.toml` ensures that Playwright and Chromium dependencies are correctly installed during the build process.

---

## 🛠️ Performance & Scalability

- **Database Persistence**: The API uses a SQLite database (`jobs.db`) to store job metadata and results, ensuring your data survives server restarts.
- **Memory Management**: Results are loaded from the database only when requested via the status API, keeping the server's idle memory usage low.
- **Async Execution**: Each QA job runs in a dedicated background thread to keep the API responsive.
