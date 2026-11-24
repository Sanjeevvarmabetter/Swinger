# Production Deployment Guide — AI Trading OS

This guide explains how to deploy **Global Market Intelligence** to **Render** or **Railway** with persistent storage for the SQLite database (`trading.db`), caches and backups.

---

## Architecture Overview

- **Runtime:** Python 3.12 (via Docker)
- **Port:** Dynamically binds to `$PORT` (assigned by Render/Railway) or default `8501`.
- **Persistent Volume:** Mounted at `/app/data` to ensure stored news, archived briefings, chat history and settings survive restarts and re-deployments.
- **Healthcheck:** Evaluated at `/_stcore/health`.

---

## Option 1: Deploy on Render (Recommended)

### Method A: Deploy via Blueprint (Fastest)

1. Push your latest code to your GitHub repository:
   ```bash
   git add .
   git commit -m "feat: add production Docker and Render deployment manifests"
   git push origin main
   ```
2. Log in to [Render Dashboard](https://dashboard.render.com/).
3. Click **New +** → **Blueprint**.
4. Select your repository: `Sanjeevvarmabetter/Swinger`.
5. Render will automatically detect [`render.yaml`](file:///Users/sanjeevvarma/projects/Swinger/render.yaml) and configure:
   - Web Service (`ai-trading-os`)
   - Persistent Disk (`tradingos-data` mounted at `/app/data`)
   - Healthcheck path (`/_stcore/health`)
6. Enter your secret environment variables when prompted:
   - `GEMINI_API_KEY`: Your Google AI Studio API key
   - `FINNHUB_API_KEY`: Your Finnhub API key
   - `FMP_API_KEY`: Your Financial Modeling Prep key
   - `FRED_API_KEY`: Your St. Louis Fed FRED key
7. Click **Apply**. Render will build the Docker container and deploy your terminal.

---

### Method B: Manual Web Service Setup on Render

1. Click **New +** → **Web Service**.
2. Select your repository (`Sanjeevvarmabetter/Swinger`).
3. Choose **Docker** as the runtime.
4. Add a **Persistent Disk**:
   - Go to the **Disks** section.
   - Name: `tradingos-data`
   - Mount Path: `/app/data`
   - Size: `1 GB` (or larger)
5. Under **Environment Variables**, add:
   - `GEMINI_API_KEY` = `<your-gemini-key>`
   - `GEMINI_MODEL` = `gemini-3.8-flash`
   - `FINNHUB_API_KEY` = `<your-finnhub-key>`
   - `FMP_API_KEY` = `<your-fmp-key>`
   - `FRED_API_KEY` = `<your-fred-key>`
   - `SEC_USER_AGENT` = `AI-Trading-OS personal research trader@example.com`
   - `TRADINGOS_DATA_DIR` = `/app/data`
6. Click **Create Web Service**.

---

## Option 2: Deploy on Railway

1. Log in to [Railway](https://railway.app/).
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select `Sanjeevvarmabetter/Swinger`. Railway will automatically detect the [`Dockerfile`](file:///Users/sanjeevvarma/projects/Swinger/Dockerfile) and [`railway.json`](file:///Users/sanjeevvarma/projects/Swinger/railway.json).
4. **Attach a Persistent Volume:**
   - In your Railway project canvas, right-click or click **+ Add Volume**.
   - Attach it to your service.
   - Set the mount path to: `/app/data`.
5. **Configure Environment Variables:**
   - Go to your service's **Variables** tab.
   - Add:
     - `GEMINI_API_KEY`
     - `GEMINI_MODEL`: `gemini-3.8-flash`
     - `FINNHUB_API_KEY`
     - `FMP_API_KEY`
     - `FRED_API_KEY`
     - `SEC_USER_AGENT`: `AI-Trading-OS personal research trader@example.com`
     - `TRADINGOS_DATA_DIR`: `/app/data`
6. **Generate Domain:**
   - Under the **Settings** tab → **Networking** → Click **Generate Domain** (e.g. `swinger.up.railway.app`).

---

## Verification & Health Check

Once your service finishes building and transitions to **Live**:

1. Open your assigned URL (e.g., `https://ai-trading-os.onrender.com` or `https://swinger.up.railway.app`).
2. Verify the Top Bar:
   - Live US Market Session clock and status pill should display with active New York time.
3. Verify Integrations:
   - Navigate to **Settings** (`/settings_page`).
   - Click **Test Gemini**, **Test Finnhub**, **Test FMP**, and **Test FRED**.
   - All connection test pills should return green success status.
