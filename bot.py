import discord
import asyncio
import requests
import os
from datetime import datetime, timedelta, timezone
from flask import Flask
import threading

# -----------------------------
# Config
# -----------------------------
VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
CHANNEL_ID = 1420399607661465673  # Replace with your Discord channel ID
AIRPORTS = {
    "OLBA": "🇱🇧 Beirut",
    "OSDI": "🇸🇾 Damascus",
    "ORBI": "🇮🇶 Baghdad"
}

# Discord-hosted banner URL
BANNER_URL = "https://cdn.discordapp.com/attachments/1133008419142500434/1423108256594661457/BANNER.png"

intents = discord.Intents.default()

# -----------------------------
# Discord Bot
# -----------------------------
class MyClient(discord.Client):
    def __init__(self, *, intents):
        super().__init__(intents=intents)
        self.flights = []
        self.atc_sessions = {}
        self.last_report_date = None  # Prevent double-post

    async def setup_hook(self):
        self.bg_task = asyncio.create_task(self.check_vatsim())

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")

    async def check_vatsim(self):
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            print("❌ Could not find channel. Check CHANNEL_ID.")
            return

        while not self.is_closed():
            try:
                r = requests.get(VATSIM_DATA_URL)
                if r.status_code == 200:
                    data = r.json()
                    now = datetime.now(timezone.utc)

                    # -----------------------------
                    # Track flights for today only
                    # -----------------------------
                    for pilot in data.get("pilots", []):
                        dep = pilot.get("planned_departure_airport")
                        arr = pilot.get("planned_arrival_airport")
                        callsign = pilot.get("callsign")
                        if dep in AIRPORTS or arr in AIRPORTS:
                            self.flights.append({
                                "callsign": callsign,
                                "dep": dep,
                                "arr": arr,
                                "time": now
                            })

                    # -----------------------------
                    # Track ATC sessions
                    # -----------------------------
                    for atc in data.get("controllers", []):
                        callsign = atc.get("callsign", "")
                        cid = atc.get("cid")
                        for icao in AIRPORTS:
                            if icao in callsign:
                                if cid not in self.atc_sessions:
                                    self.atc_sessions[cid] = {
                                        "callsign": callsign,
                                        "start": now,
                                        "duration": timedelta()
                                    }
                                else:
                                    self.atc_sessions[cid]["duration"] += timedelta(minutes=1)

                    # -----------------------------
                    # Post report daily at 01:10 UTC
                    # -----------------------------
                    utc_now = datetime.utcnow()
                    if utc_now.hour == 1 and utc_now.minute == 10 and self.last_report_date != utc_now.date():
                        embed = self.generate_report()
                        await channel.send(embed=embed)
                        self.last_report_date = utc_now.date()

                        # Reset flights and ATC sessions for the next day
                        self.flights = []
                        self.atc_sessions = {}

            except Exception as e:
                print(f"Error: {e}")

            await asyncio.sleep(60)

    def generate_report(self):
        embed = discord.Embed(
            title=f"Daily VATSIM Report - {datetime.utcnow().strftime('%Y-%m-%d')}",
            description="Summary of Departures, Arrivals, and ATC Activity",
            color=0x1abc9c
        )

        # Flights stats
        for icao, name in AIRPORTS.items():
            arrivals = sum(1 for f in self.flights if f["arr"] == icao)
            departures = sum(1 for f in self.flights if f["dep"] == icao)
            sessions = sum(1 for cid, s in self.atc_sessions.items() if icao in s["callsign"])

            embed.add_field(
