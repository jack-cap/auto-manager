#!/usr/bin/env python3
"""Fetch and analyze Manager.io OpenAPI spec."""

import asyncio
import json
import os
import sys
sys.path.insert(0, '.')

from pathlib import Path
from dotenv import load_dotenv
import httpx

# Load test credentials
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env.test")

BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")
API_KEY = os.getenv("MANAGER_READ_API_KEY", "")


async def get_openapi():
    """Fetch OpenAPI spec."""
    
    async with httpx.AsyncClient(
        timeout=60.0,
        verify=False,
        headers={
            "X-API-KEY": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    ) as client:
        
        response = await client.get(BASE_URL)
        if response.is_success:
            spec = response.json()
            
            # Save full spec
            with open("backend/scripts/manager_openapi.json", "w") as f:
                json.dump(spec, f, indent=2)
            print("Saved full OpenAPI spec to manager_openapi.json")
            
            # List all paths
            paths = spec.get("paths", {})
            print(f"\n\nAvailable endpoints ({len(paths)}):")
            print("="*60)
            
            for path, methods in sorted(paths.items()):
                for method, details in methods.items():
                    summary = details.get("summary", "")
                    print(f"  {method.upper():6} {path:40} - {summary}")


if __name__ == "__main__":
    asyncio.run(get_openapi())
