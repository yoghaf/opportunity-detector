# src/api/server.py
"""
FastAPI backend for Crypto Decision Dashboard.

Replaces Streamlit with:
    - REST endpoints for opportunities + collector stats
    - WebSocket for real-time push to frontend
    - Static file serving for the SPA frontend
    - Background task for periodic data refresh

Run:
    python -m src.api.server
    # or
    uvicorn src.api.server:app --reload --port 8001
"""

import asyncio
import json
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager
import pandas as pd
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import Config
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.strategies.opportunity_finder import OpportunityFinder
from src.prediction.db import init_db, get_db_stats, get_token_history, get_latest_features, get_last_known_opportunities
from src.strategies.prediction import calculate_ema, analyze_trend
from src.prediction.pipeline import PredictionPipeline

# ... (existing imports)

# Logging
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api")

# ============================================================
# Global state
# ============================================================
class AppState:
    """Shared state across the app."""
    def __init__(self):
        self.finder: Optional[OpportunityFinder] = None
        self.pipeline: Optional[PredictionPipeline] = None
        self.latest_data: list[dict] = []
        self.last_fetch_time: Optional[str] = None
        self.connected_clients: list[WebSocket] = []
        self.refresh_task: Optional[asyncio.Task] = None
        self.prediction_task: Optional[asyncio.Task] = None

state = AppState()

# ============================================================
# Lifespan (startup / shutdown)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize clients and start background refresh on startup."""
    logger.info("🚀 Starting Crypto Decision Dashboard API...")
    
    # Init DB
    init_db()
    
    # Init exchange clients
    try:
        gate = GateClient()
        okx = OKXClient()
        binance = BinanceClient()
        state.finder = OpportunityFinder(gate, okx, binance)
    except Exception as e:
        logger.error(f"❌ Failed to init clients: {e}")

    # Init Prediction Pipeline (Phase 2)
    try:
        state.pipeline = PredictionPipeline()
        # Optional: Run maintenance once on startup
        # state.pipeline.update_survival_curves()
        logger.info("🧠 Prediction Pipeline initialized.")
    except Exception as e:
        logger.error(f"❌ Failed to init prediction pipeline: {e}")
    
    # INSTANT STARTUP: Load latest snapshot from DB
    try:
        cached_data, cached_ts = get_last_known_opportunities()
        if cached_data:
            state.latest_data = clean_floats(cached_data)
            state.last_fetch_time = cached_ts
            logger.info(f"⚡ Instant Startup: Loaded {len(cached_data)} records from {cached_ts}")
    except Exception as e:
        logger.error(f"⚠️ Failed to load cached data: {e}")

    # Start background refresh loop (it will fetch data immediately)
    state.refresh_task = asyncio.create_task(background_refresh_loop())
    state.prediction_task = asyncio.create_task(background_prediction_loop())
    
    logger.info("✅ API ready. Serving on http://localhost:8001")
    yield
    
    # Shutdown
    if state.refresh_task:
        state.refresh_task.cancel()
    if state.prediction_task:
        state.prediction_task.cancel()
    logger.info("🛑 API shutdown complete.")

# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(
    title="Crypto Decision Dashboard API",
    version="2.0.0",
    lifespan=lifespan,
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend"
)

# ============================================================
# Background data refresh
# ============================================================
REFRESH_INTERVAL = 60  # seconds

def clean_floats(obj):
    """Recursively replace NaN/Infinity and handle non-serializable types."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj): return 0
        if math.isinf(obj): return 0
        return obj
    elif isinstance(obj, dict):
        return {k: clean_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_floats(v) for v in obj]
    elif pd.isna(obj): # Handles pd.NA, pd.NaT if passed directly
        return None
    return obj

async def refresh_data():
    """Fetch fresh data from all exchanges."""
    if not state.finder:
        logger.warning("⚠️ Finder not initialized yet")
        return

    try:
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, state.finder.find_opportunities)
        
        if df is not None and not df.empty:
            logger.info("DF received from finder. Converting to raw_data...")
            # Convert DataFrame to list of dicts for JSON
            # Do NOT use fillna(0) as it hides missing data (None/NaN)
            # We want frontend to see null for "Unknown"
            # FIX: Cast to object to prevent float columns from forcing None -> NaN -> 0
            raw_data = df.astype(object).where(pd.notnull(df), None).to_dict(orient='records')
            
            logger.info("Cleaning floats...")
            state.latest_data = clean_floats(raw_data)
            state.last_fetch_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.info(f"📊 Data refreshed: {len(state.latest_data)} opportunities")
            
            # QUANT: Record history for prediction
            try:
                # Add timestamp to records
                logger.info("Preparing DB records...")
                db_records = []
                for d in raw_data:
                    # Create a copy to avoid mutating raw_data
                    rec = d.copy() 
                    rec['timestamp'] = state.last_fetch_time
                    rec['data_type'] = 'opportunity' 
                    rec['apr'] = rec.get('net_apr')
                    # Fix: Store the full record as raw_payload so we can reconstruct it on startup
                    rec['raw_payload'] = d
                    db_records.append(rec)
                
                # Insert into DB (non-blocking ideally, but SQLite is fast enough here)
                from src.prediction.db import insert_apr_batch
                logger.info("Inserting into DB...")
                inserted = insert_apr_batch(db_records)
                logger.info(f"💾 History recorded: +{inserted} rows")
            except Exception as e:
                logger.error(f"❌ Failed to record history: {e}")
                import traceback
                logger.error(traceback.format_exc())

            # Push to all WebSocket clients
            logger.info("Broadcasting update...")
            await broadcast_update()
        else:
            logger.warning("⚠️ No data returned from exchanges")
    except Exception as e:
        logger.error(f"❌ Data refresh failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

async def background_refresh_loop():
    """Periodically refresh data."""
    # Initial fetch immediately
    await refresh_data()
    
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            await refresh_data()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Background refresh error: {e}")

async def background_prediction_loop():
    """Periodically run the Probabilistic Prediction Pipeline."""
    # Wait a bit for data to populate
    await asyncio.sleep(10) 
    
    while True:
        try:
            if state.pipeline:
                logger.info("🧠 Running Prediction Pipeline...")
                await asyncio.to_thread(state.pipeline.run_cycle)
                logger.info("🧠 Pipeline cycle complete.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Prediction pipeline error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
        # Run every 2 minutes
        await asyncio.sleep(120)

async def broadcast_update():
    """Push latest data to all connected WebSocket clients."""
    if not state.connected_clients:
        return
    
    try:
        message = json.dumps({
            "type": "data_update",
            "timestamp": state.last_fetch_time,
            "count": len(state.latest_data),
            "data": state.latest_data,
        })
    except Exception as e:
        logger.error(f"❌ JSON Serialization Failed: {e}")
        # Fallback: Try to find the bad record
        logger.error(f"Sample data: {state.latest_data[:1]}")
        return
    
    disconnected = []
    for ws in state.connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    
    for ws in disconnected:
        state.connected_clients.remove(ws)

# ============================================================
# REST API Routes
# ============================================================
@app.get("/api/opportunities")
async def get_opportunities(
    min_apr: float = 0,
    source: str = "all",
    limit: int = 200,
):
    """Get current opportunity data with optional filters."""
    data = state.latest_data
    
    # Filter by min APR
    if min_apr > 0:
        data = [d for d in data if d.get('net_apr', 0) >= min_apr]
    
    # Filter by source - STRICT (Financial Integrity)
    if source == "okx":
        data = [d for d in data if d.get('best_loan_source') == 'OKX']
    elif source == "binance":
        data = [d for d in data if d.get('best_loan_source') == 'Binance']
    
    # Limit
    # Sort descending by Net APR (handle None values safely) to ensure best opps are kept
    data.sort(key=lambda x: (x.get('net_apr') or -999.0), reverse=True)
    data = data[:limit]
    
    return {
        "timestamp": state.last_fetch_time,
        "count": len(data),
        "data": data,
    }

@app.get("/api/collector/stats")
async def get_collector_stats():
    """Get APR collector health statistics."""
    try:
        stats = get_db_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/history/{token}")
async def get_history(token: str, hours: int = 24):
    """
    Quant Research: Get historical opportunity data + Trend Analysis.
    """
    try:
        data = get_token_history(token, hours)
        
        # Analyze Trend
        analysis = analyze_trend(data)
        
        return {
            "token": token.upper(),
            "hours": hours,
            "count": len(data),
            "trend": analysis,
            "data": data
        }
    except Exception as e:
        logger.error(f"Failed to fetch history for {token}: {e}")
        return {"error": str(e)}


@app.get("/api/predictions")
async def get_predictions(limit: int = 20):
    """
    Get top probabilistic predictions (Phase 2).
    Returns list of tokens with Regime, Volatility, and Probabilities.
    """
    try:
        loop = asyncio.get_event_loop()
        # Fetch latest features from DB
        data = await loop.run_in_executor(None, get_latest_features, limit)
        
        # Enrich with badges/formatting
        formatted = []
        for d in data:
            regime_probs = d['regime_prob']
            
            # Determine dominant regime
            dominant_regime = max(regime_probs, key=regime_probs.get)
            confidence = regime_probs[dominant_regime]
            
            # Simple signal logic for FE
            signal = "NEUTRAL"
            if dominant_regime == "Rising" and confidence > 0.6:
                signal = "BUY"
            elif dominant_regime == "Decay" and confidence > 0.6:
                signal = "SELL"
                
            # QUANT FIX (2026-02-16): User Request - Show ONLY "Rising" predictions
            # "hanya nampilin yang bakalan diprediksi naik aja"
            if dominant_regime != "Rising":
                continue

            formatted.append({
                "token": d['token'],
                "current_apr": d['apr_clean'],
                "regime": dominant_regime,
                "confidence": round(confidence * 100, 1),
                "signal": signal,
                "volatility": round(d['volatility'], 2),
                "probs": regime_probs
            })
            
        return {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(formatted),
            "data": formatted,
            "engine": "v2_probabilistic"
        }
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return {"error": str(e)}

@app.get("/api/validation/status")
async def get_validation_status(days: int = 30):
    """
    Get Phase 3.5 Validation Metrics (Paper Trading).
    Used to gate the Sniper Bot (Phase 4).
    """
    try:
        from src.prediction.simulation import PerformanceMonitor
        stats = PerformanceMonitor.get_stats(days=days)
        return stats
    except Exception as e:
        logger.error(f"Validation stats error: {e}")
        return {"error": str(e)}

@app.post("/api/refresh")
async def force_refresh():
    """Force immediate data refresh."""
    await refresh_data()
    return {"status": "ok", "timestamp": state.last_fetch_time, "count": len(state.latest_data)}

# ============================================================
# Bot API endpoints
# ============================================================
import subprocess
import signal

bot_process: Optional[subprocess.Popen] = None
bot_config: dict = {}

LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "bot.log"
)

def read_log_tail(path: str, lines: int = 30) -> list[str]:
    """Read last N lines from a log file."""
    try:
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
            return [l.rstrip() for l in all_lines[-lines:]]
    except Exception:
        return []

@app.post("/api/bot/start")
async def bot_start(config: dict = {}):
    """Start the sniper bot as a subprocess."""
    global bot_process, bot_config
    
    if bot_process and bot_process.poll() is None:
        return {"status": "already_running", "message": "Bot is already running. Stop it first."}
    
    token = config.get("token", "ETH")
    amount = config.get("amount", 0)
    ltv = config.get("ltv", 70)
    use_browser = config.get("use_browser", True)
    sniper_mode = config.get("sniper_mode", False)
    
    bot_config = {
        "token": token,
        "amount": amount,
        "ltv": ltv,
        "use_browser": use_browser,
        "sniper_mode": sniper_mode,
    }
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Build command
    cmd = [
        sys.executable, "-m", "src.strategies.sniper",
        "--token", token,
        "--ltv", str(ltv),
    ]
    if amount > 0:
        cmd.extend(["--amount", str(amount)])
    if use_browser:
        cmd.append("--browser")
    if sniper_mode:
        cmd.append("--sniper")
    
    try:
        # Ensure logs dir exists
        log_dir = os.path.join(project_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        log_f = open(LOG_FILE, 'a', encoding='utf-8')
        bot_process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
        )
        logger.info(f"🔫 Bot started PID={bot_process.pid} token={token}")
        return {"status": "started", "pid": bot_process.pid, "config": bot_config}
    except Exception as e:
        logger.error(f"❌ Bot start failed: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/bot/stop")
async def bot_stop():
    """Stop the running bot."""
    global bot_process
    
    if not bot_process or bot_process.poll() is not None:
        bot_process = None
        return {"status": "not_running", "message": "Bot is not running."}
    
    try:
        if sys.platform == 'win32':
            bot_process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            bot_process.terminate()
        
        bot_process.wait(timeout=5)
        logger.info("⏹️ Bot stopped.")
    except subprocess.TimeoutExpired:
        bot_process.kill()
        logger.warning("⚠️ Bot force-killed after timeout.")
    except Exception as e:
        logger.error(f"❌ Bot stop error: {e}")
    
    bot_process = None
    return {"status": "stopped"}

@app.get("/api/bot/status")
async def bot_status():
    """Get bot running status and recent logs."""
    global bot_process
    
    running = bot_process is not None and bot_process.poll() is None
    logs = read_log_tail(LOG_FILE, 25)
    
    return {
        "running": running,
        "pid": bot_process.pid if running else None,
        "config": bot_config if running else {},
        "status_msg": f"Sniping {bot_config.get('token', '?')}" if running else "Idle",
        "logs": logs,
    }

# ============================================================
# Browser automation endpoints
# ============================================================
@app.post("/api/browser/login")
async def browser_login(config: dict = {}):
    """Launch OKX browser login (QR or Chrome)."""
    method = config.get("method", "qr")
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    if method == "chrome":
        cmd = [sys.executable, "-c", 
               "from src.exchanges.okx_browser import login_system_chrome; login_system_chrome()"]
    else:
        cmd = [sys.executable, "-c",
               "from src.exchanges.okx_browser import login_qr; login_qr()"]
    
    try:
        subprocess.Popen(cmd, cwd=project_root)
        logger.info(f"🌐 Browser login launched (method={method})")
        return {"status": "launched", "message": f"Browser login ({method}) launched! Check the browser window."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/browser/borrow")
async def browser_borrow(config: dict = {}):
    """Execute a manual borrow via browser automation."""
    token = config.get("token", "ETH")
    amount = config.get("amount", "0.001")
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    cmd = [sys.executable, "-c",
           f"from src.exchanges.okx_browser import borrow_mode; borrow_mode('{token}', '{amount}')"]
    
    try:
        subprocess.Popen(cmd, cwd=project_root)
        logger.info(f"💸 Browser borrow started: {amount} {token}")
        return {"status": "started", "message": f"Borrow {amount} {token} started. Check Telegram for result."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/browser/session")
async def browser_session_status():
    """Check OKX browser session status."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    session_file = os.path.join(project_root, "okx_session.json")
    profile_dir = os.path.join(project_root, "okx_profile")
    
    result = {
        "session_exists": False,
        "profile_exists": False,
        "last_login": None,
        "cookie_count": 0,
        "age_minutes": None,
    }
    
    # Check okx_session.json
    if os.path.exists(session_file):
        result["session_exists"] = True
        mod_time = os.path.getmtime(session_file)
        last_login_dt = datetime.fromtimestamp(mod_time)
        result["last_login"] = last_login_dt.strftime("%Y-%m-%d %H:%M")
        
        age_seconds = time.time() - mod_time
        result["age_minutes"] = round(age_seconds / 60)
        
        try:
            import json as json_mod
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json_mod.load(f)
                result["cookie_count"] = len(data.get("cookies", []))
        except Exception:
            pass
    
    # Check okx_profile directory
    if os.path.isdir(profile_dir):
        result["profile_exists"] = True
    
    return result

# ============================================================
# WebSocket
# ============================================================
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time data push via WebSocket."""
    await websocket.accept()
    state.connected_clients.append(websocket)
    logger.info(f"🔌 WebSocket connected. Total clients: {len(state.connected_clients)}")
    
    # Send current data immediately on connect
    try:
        await websocket.send_text(json.dumps({
            "type": "data_update",
            "timestamp": state.last_fetch_time,
            "count": len(state.latest_data),
            "data": state.latest_data,
        }))
    except Exception:
        pass
    
    try:
        while True:
            # Keep connection alive, handle client messages
            msg = await websocket.receive_text()
            
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg == "refresh":
                await refresh_data()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in state.connected_clients:
            state.connected_clients.remove(websocket)
        logger.info(f"🔌 WebSocket disconnected. Remaining: {len(state.connected_clients)}")

# ============================================================
# Frontend serving
# ============================================================
@app.get("/")
async def serve_index():
    """Serve the main dashboard page."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"error": "Frontend not found. Run from project root."}, status_code=404)

# Mount static assets (CSS, JS) — must be after specific routes
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# ============================================================
# CLI entry point
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
