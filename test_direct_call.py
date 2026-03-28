#!/usr/bin/env python3
"""Direct Flask function call test"""
import sys
sys.path.insert(0, r'c:\Users\gusta\Documents\Pythons\Website')

from app import scrape, SHOP_CONFIGS, app
from flask import Request
from werkzeug.test import EnvironBuilder
import json

print(f"SHOP_CONFIGS: {list(SHOP_CONFIGS.keys())}\n")

# Create a test request context
payload = {
    "category": "decks",
    "shops": ["skatedeluxe"],
    "budget": 200
}

print(f"Test payload: {payload}\n")

builder = EnvironBuilder(method='POST', data=json.dumps(payload), content_type='application/json')
env = builder.get_environ()

with app.request_context(env):
    result = scrape()
    print(f"Result status: {result[1] if isinstance(result, tuple) else 'unknown'}")
    print(f"Result: {result[0] if isinstance(result, tuple) else result}")
