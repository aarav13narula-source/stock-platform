"""Vercel serverless entry point."""
import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app import create_app

app = create_app()
handler = app
