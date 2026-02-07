import os
import time
import requests
import cloudscraper
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# --- YouTube imports ---
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build

# ──────────────────────────────────────────────
#  Configuration (env vars set via Vercel dashboard)
# ──────────────────────────────────────────────
YOUTUBE_VIDEO_ID = os.environ.get("YOUTUBE_VIDEO_ID", "6xF32qbLI84")

# ──────────────────────────────────────────────
#  Token / holdings info
# ──────────────────────────────────────────────
token_info = {
    "raw_symbol": "SPACEX",
    "exchange_holdings": {
        "jarsy": {
            "symbol": "JSPAX",
            "cost_basis": 840,
            "quantity": 2.489,
        },
        "jupiter": {
            "symbol": "PreANxuXjsy2pvisWWMNB6YaJNzr7681wJJr2rHsfTh",
            "cost_basis": 335.07,
            "quantity": 4.531,
        },
    },
}

# ──────────────────────────────────────────────
#  FastAPI app
# ──────────────────────────────────────────────
app = FastAPI(title="SpaceX Portfolio Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
#  Price helpers
# ──────────────────────────────────────────────
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


def get_jupiter_token_price(input_mint: str) -> float | None:
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    input_mint = token_info["exchange_holdings"]["jupiter"]["symbol"]
    amount = 10**9
    url = "https://ultra-api.jup.ag/order"
    params = {
        "inputMint": input_mint,
        "outputMint": USDC_MINT,
        "amount": amount,
        "swapMode": "ExactIn",
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


# ──────────────────────────────────────────────
#  Portfolio helpers
# ──────────────────────────────────────────────
def calculate_p_l(exchange: str, current_price: float) -> dict:
    holdings = token_info["exchange_holdings"][exchange]
    purchase_price = holdings["cost_basis"]
    quantity = holdings["quantity"]
    pnl = (current_price - purchase_price) * quantity
    pnl_percent = ((current_price - purchase_price) / purchase_price) * 100
    return {"pnl": pnl, "pnl_percent": pnl_percent, "buy_price": purchase_price}


def get_portfolio_summary() -> dict:
    jarsy_price = get_jarsy_token_price(None)
    jupiter_price = get_jupiter_token_price(None)

    jarsy_pnl = calculate_p_l("jarsy", jarsy_price)
    jupiter_pnl = calculate_p_l("jupiter", jupiter_price)

    total_pnl = jarsy_pnl["pnl"] + jupiter_pnl["pnl"]

    holdings = token_info["exchange_holdings"]
    total_invested = sum(h["cost_basis"] * h["quantity"] for h in holdings.values())
    total_pnl_percent = (total_pnl / total_invested) * 100 if total_invested else 0

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
            "position_value": jarsy_price * holdings["jarsy"]["quantity"] if jarsy_price else None,
        },
        "jupiter": {
            "pnl": jupiter_pnl["pnl"],
            "pnl_percent": jupiter_pnl["pnl_percent"],
            "buy_price": jupiter_pnl["buy_price"],
            "current_price": jupiter_price,
            "position_value": jupiter_price * holdings["jupiter"]["quantity"] if jupiter_price else None,
        },
        "total": {
            "pnl": total_pnl,
            "pnl_percent": total_pnl_percent,
            "portfolio_value": total_portfolio_value,
            "invested": total_invested,
        },
    }


# ──────────────────────────────────────────────
#  YouTube helpers
# ──────────────────────────────────────────────
def get_youtube_client():
    """Build an authenticated YouTube API client from env vars."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "Missing YouTube credentials. Set YOUTUBE_CLIENT_ID, "
            "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN env vars."
        )

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    credentials.refresh(GoogleAuthRequest())
    return build("youtube", "v3", credentials=credentials)


def update_video_title(new_title: str):
    """Update the YouTube video title."""
    youtube = get_youtube_client()

    resp = youtube.videos().list(part="snippet", id=YOUTUBE_VIDEO_ID).execute()

    if not resp.get("items"):
        raise RuntimeError(f"Video {YOUTUBE_VIDEO_ID} not found")

    snippet = resp["items"][0]["snippet"]
    snippet["title"] = new_title

    youtube.videos().update(
        part="snippet",
        body={"id": YOUTUBE_VIDEO_ID, "snippet": snippet},
    ).execute()

    print(f"YouTube title updated to: {new_title}")


# ──────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────
@app.get("/api/portfolio")
def api_portfolio():
    """Get portfolio summary with P&L for all exchanges."""
    try:
        return get_portfolio_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/update-title")
def api_update_title(request: Request):
    """
    Fetch current portfolio P&L and update the YouTube video title.
    Called by Vercel Cron every 15 minutes.
    """
    cron_secret = os.environ.get("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("authorization", "")
        if auth_header != f"Bearer {cron_secret}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        summary = get_portfolio_summary()
        total_pnl = summary["total"]["pnl"]
        amount = f"{total_pnl:,.2f}"
        new_title = f"How I Made ${amount} with SpaceX Stock..."
        update_video_title(new_title)
        return {
            "status": "ok",
            "new_title": new_title,
            "portfolio": summary,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the portfolio dashboard HTML."""
    with open("portfolio.html", "r") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
