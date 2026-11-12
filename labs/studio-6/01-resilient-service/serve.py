"""Run the service locally (needs FastAPI, uvicorn, and an API key in labs/.env):

    uvicorn serve:app --reload        # from this folder

The app is built from YOUR starter.py, so finish the TODOs first.
"""
import pathlib

try:
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from starter import build_default_app

app = build_default_app()
