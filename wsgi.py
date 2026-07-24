"""WSGI entry points for production: gunicorn -b 127.0.0.1:8888 wsgi:admin_app"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_dashboard import app as admin_app
from shop import app as shop_app
