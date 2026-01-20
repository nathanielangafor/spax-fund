# Vercel entry point for FastAPI
import sys
import os

# Add parent directory to path so we can import portfolio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio import app

# Export the app for Vercel
__all__ = ["app"]
