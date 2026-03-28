#!/usr/bin/env python3
"""Test HTTP request directly"""
import requests
import json

base_url = "http://localhost:5000"

payload = {
    "category": "decks",
    "shops": ["skatedeluxe"],
    "budget": 200
}

print(f"Sending request to {base_url}/api/scrape")
print(f"Payload: {json.dumps(payload)}\n")

try:
    response = requests.post(
        f"{base_url}/api/scrape",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
except Exception as e:
    print(f"Error: {e}")
