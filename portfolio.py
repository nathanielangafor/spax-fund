from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import requests
import cloudscraper
import time
import asyncio
import threading

# Global cache for portfolio data
portfolio_cache = None
cache_lock = threading.Lock()

async def update_portfolio_cache():
    """Update the portfolio cache by fetching fresh data."""
    global portfolio_cache
    try:
        new_data = get_portfolio_summary()
        with cache_lock:
            portfolio_cache = new_data
        print(f"Portfolio cache updated at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"Error updating portfolio cache: {e}")

async def background_price_updater():
    """Background task that updates prices every 15 minutes."""
    # Initial update on startup
    await update_portfolio_cache()
    
    # Then update every 15 minutes (900 seconds)
    while True:
        await asyncio.sleep(900)  # 15 minutes
        await update_portfolio_cache()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start background task
    task = asyncio.create_task(background_price_updater())
    yield
    # Shutdown: cancel background task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="SpaceX Portfolio Tracker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

token_info = {
    "raw_symbol": "SPACEX",
    "exchange_holdings": {
        "jarsy": {
            "symbol": "JSPAX",
            "cost_basis": 840,
            "quantity": 2.489
        },
        "jupiter": {
            "symbol": "PreANxuXjsy2pvisWWMNB6YaJNzr7681wJJr2rHsfTh",
            "cost_basis": 335.07,
            "quantity": 4.531
        }
    }
}

def get_jarsy_token_price(symbol: str) -> float | None:
    JARSY_TOKEN_LIST_URL = "https://api.jarsy.com/api/home/token_list"
    symbol = token_info["exchange_holdings"]["jarsy"]["symbol"]
    resp = requests.get(JARSY_TOKEN_LIST_URL, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 200:
        raise RuntimeError("Unexpected API response")
    for token in payload.get("data", []):
        if token.get("coin") == symbol:
            price = token.get("price")
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
    return None


def get_jupiter_token_price(input_mint: str):
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    input_mint = token_info["exchange_holdings"]["jupiter"]["symbol"]
    amount = 10**9  # probe with 1 token
    url = "https://ultra-api.jup.ag/order"
    params = {
        "inputMint": input_mint,
        "outputMint": USDC_MINT,
        "amount": amount,
        "swapMode": "ExactIn"
    }
    scraper = cloudscraper.create_scraper(
        browser={
            "browser": "chrome",
            "platform": "darwin",
            "desktop": True,
        }
    )
    resp = scraper.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("inUsdValue")


def calculate_p_l(exchange: str, current_price: float) -> dict | None:
    holdings = token_info["exchange_holdings"].get(exchange)
    purchase_price = holdings["cost_basis"]
    quantity = holdings["quantity"]
    pnl = (current_price - purchase_price) * quantity
    pnl_percent = ((current_price - purchase_price) / purchase_price) * 100
    return {"pnl": pnl, "pnl_percent": pnl_percent, "buy_price": purchase_price}

def get_portfolio_summary():
    jarsy_price = get_jarsy_token_price(None)
    jupiter_price = get_jupiter_token_price(None)

    jarsy_pnl = calculate_p_l("jarsy", jarsy_price)
    jupiter_pnl = calculate_p_l("jupiter", jupiter_price)

    # Calculate totals
    total_pnl = jarsy_pnl["pnl"] + jupiter_pnl["pnl"]
    
    # Total invested = sum of (buy_price * quantity) for each exchange
    holdings = token_info["exchange_holdings"]
    total_invested = sum(
        h["cost_basis"] * h["quantity"] for h in holdings.values()
    )
    total_pnl_percent = (total_pnl / total_invested) * 100 if total_invested else 0
    
    # Total portfolio value = sum of (current_price * quantity) for each exchange
    total_portfolio_value = 0
    if jarsy_price:
        total_portfolio_value += jarsy_price * holdings["jarsy"]["quantity"]
    if jupiter_price:
        total_portfolio_value += jupiter_price * holdings["jupiter"]["quantity"]

    return {
        "jarsy": {
            "pnl": jarsy_pnl["pnl"],
            "pnl_percent": jarsy_pnl["pnl_percent"],
            "buy_price": jarsy_pnl["buy_price"],
            "current_price": jarsy_price,
            "position_value": jarsy_price * holdings["jarsy"]["quantity"] if jarsy_price else None
        },
        "jupiter": {
            "pnl": jupiter_pnl["pnl"],
            "pnl_percent": jupiter_pnl["pnl_percent"],
            "buy_price": jupiter_pnl["buy_price"],
            "current_price": jupiter_price,
            "position_value": jupiter_price * holdings["jupiter"]["quantity"] if jupiter_price else None
        },
        "total": {
            "pnl": total_pnl,
            "pnl_percent": total_pnl_percent,
            "portfolio_value": total_portfolio_value,
            "invested": total_invested
        }
    }

@app.get("/api/portfolio")
def api_portfolio():
    """Get portfolio summary with P&L for all exchanges (cached, updates every 15 minutes)."""
    with cache_lock:
        if portfolio_cache is None:
            # If cache is empty (shouldn't happen after startup), return fresh data
            return get_portfolio_summary()
        return portfolio_cache


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the portfolio dashboard HTML."""
    with open("portfolio.html", "r") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
