<div align="center">
  <h1>💸 EarnView</h1>
  <p><b>Opportunity Detector & Sniper Bot for Crypto Lending Arbitrage</b></p>
  
  [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg)](https://fastapi.tiangolo.com/)
  [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
</div>

A fully automated, fee-aware cryptocurrency arbitrage and lending tool. It detects interest rate differentials between major exchanges (OKX, Binance) and Gate.io Simple Earn, then automates the borrowing process using APIs or Playwright-based browser automation (Sniper Bot).

## 📸 Web Dashboard Demo

EarnView comes with a sleek, real-time web interface to monitor live opportunities and control the Sniper Bot. 

<div align="center">
  <img src="https://via.placeholder.com/800x450.png?text=EarnView+Dashboard+Screenshot" alt="EarnView Dashboard Preview" width="800"/>
  <br/>
  <i>(Tip: Replace this placeholder with a screenshot of your dashboard at `http://localhost:8001`)</i>
</div>
## 🌟 Features
- **Smart Opportunity Detection**: Scans OKX and Binance for low borrowing rates and compares them against high-yield Gate.io Simple Earn rates.
- **Effective EV Calculation**: Calculates true profitability by automatically factoring in cross-exchange withdrawal and bridging fees.
- **Sniper Bot**: Automatically borrows assets when inventory appears. Includes a **Browser Automation Mode** (Playwright) to bypass API restrictions on flexible loans.
- **Real-Time Web Dashboard**: A fast, React/Vanilla SPA frontend powered by FastAPI and WebSockets for live monitoring.
- **Telegram Integration**: Get instant push notifications when high-EV opportunities arise or when the Sniper Bot successfully secures a loan.

## 🏗️ Architecture Stack
- **Backend API**: FastAPI, Uvicorn, WebSockets
- **Data Processing**: Pandas, SQLite (for historical tracking and trend prediction)
- **Browser Automation**: Playwright (Persistent Context, Stealth Modules)
- **Frontend**: HTML5, CSS3, Vanilla JS (Single Page Application)

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+
- Activated Virtual Environment
- API Keys for Gate.io, OKX, and/or Binance

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/yoghaf/opportunity-detector.git
git clone 
cd opportunity-detector
python -m venv venv

# Windows
source venv/Scripts/activate
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 3. Configuration
Copy the environment template and fill in your API keys:
```bash
cp .env.example .env
```
*(Note: Never commit your actual `.env` file!)*

### 4. Running the Dashboard (Recommended)
Start the FastAPI backend and serve the Web UI:
```bash
python dev.py
# Or use the shortcut script on Windows: run.bat
```
Navigate to `http://localhost:8001` in your browser.

### 5. Running the CLI Tool
If you prefer a terminal interface for quick scans or managing watchlists:
```bash
python src/main.py
```

## 🔫 Sniper Bot & Browser Automation
The Sniper Bot can borrow assets automatically. To use the Browser Automation mode (which is often required for OKX Flexible Loans):
1. Open the Web Dashboard (`http://localhost:8001`).
2. Go to the **🌐 OKX Browser** tab.
3. Click **📱 Launch QR Login**. A browser window will appear. Scan the QR code with your OKX mobile app.
4. Once the session is saved, you can go to the **🔫 Sniper Bot** tab and start sniping!

## ⚠️ Disclaimer
This tool executes real financial transactions. Use it at your own risk. Always test with small amounts first and ensure you understand the risks of margin borrowing and crypto lending.

## 📝 License
MIT License
