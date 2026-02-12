"""Throwaway script to verify Serper.dev Google Jobs API response structure."""
import asyncio
import json
import os

import httpx


async def test_serper():
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        print("ERROR: Set SERPER_API_KEY env var first")
        return

    async with httpx.AsyncClient() as client:
        # Test Google search (organic results)
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": "Head of Growth B2C Bangalore",
                "gl": "in",
                "location": "Bangalore, Karnataka, India",
                "type": "search",
                "num": 5,
            },
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(json.dumps(data, indent=2))

        # Print the keys at each level so we know the exact structure
        print("\n--- TOP-LEVEL KEYS ---")
        print(list(data.keys()))

        if "organic" in data:
            print("\n--- FIRST ORGANIC RESULT KEYS ---")
            print(list(data["organic"][0].keys()))

        if "jobs" in data:
            print("\n--- FIRST JOB RESULT KEYS ---")
            print(list(data["jobs"][0].keys()))


asyncio.run(test_serper())
