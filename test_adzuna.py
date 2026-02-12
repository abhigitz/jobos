"""Throwaway script to verify Adzuna API response structure."""
import asyncio
import json
import os

import httpx


async def test_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    api_key = os.environ.get("ADZUNA_API_KEY", "")
    if not app_id or not api_key:
        print("ERROR: Set ADZUNA_APP_ID and ADZUNA_API_KEY env vars first")
        return

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.adzuna.com/v1/api/jobs/in/search/1",
            params={
                "app_id": app_id,
                "app_key": api_key,
                "results_per_page": 5,
                "what": "Head of Growth",
                "where": "Bangalore",
                "content-type": "application/json",
            },
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(json.dumps(data, indent=2))

        print("\n--- TOP-LEVEL KEYS ---")
        print(list(data.keys()))

        if "results" in data and data["results"]:
            print("\n--- FIRST RESULT KEYS ---")
            print(list(data["results"][0].keys()))


asyncio.run(test_adzuna())
