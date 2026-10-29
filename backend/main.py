"""ASGI entry point: uvicorn main:app"""
from app.web import app

__all__ = ["app"]
