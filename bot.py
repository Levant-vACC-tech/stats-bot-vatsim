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
CHANNEL_ID = 1420399607661465673  # Replace with your channel ID
AIRPORTS = {
    "OLBA": "🇱🇧 Beirut",
    "OSDI": "🇸🇾 Damascus",
    "ORBI": "🇮🇶 Baghdad"
}

intents = discord.Intents.default()

# -----------------------------
# Discord Bot
# -----------------------------
class MyClient(discord.Client):
    def __init__(self, *, intents):
        super().__init__(intents=intents)
        self.flights = []
        self.atc_sessions = {}

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
                    # Track flights
                    # -----------------------------
                    self.flights = [f for f in self.flights if f["time"] > now - timedelta(hours=24)]
                    for pilot in data.get("pilots", []):
                        dep = pilot.get("departure")
                        arr = pilot.get("arrival")
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
                    # Post report daily at 08:00 UTC
                    # -----------------------------
                    utc_now = datetime.utcnow()
                    if utc_now.hour == 8 and utc_now.minute < 2:
                        embed = self.generate_report()
                        await channel.send(embed=embed)

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
                name=f"{icao} – {name}",
                value=f"Departures: {departures}\nArrivals: {arrivals}\nATC Sessions: {sessions}",
                inline=False
            )

        # ATC longest session
        if self.atc_sessions:
            longest = max(self.atc_sessions.items(), key=lambda x: x[1]["duration"])
            cid, info = longest
            hours, remainder = divmod(longest[1]["duration"].seconds, 3600)
            minutes = remainder // 60
            embed.add_field(
                name="Longest ATC Session",
                value=f"{info['callsign']} – {hours}h {minutes}m ({cid})",
                inline=False
            )

            # Controller of the Day
            top = max(self.atc_sessions.items(), key=lambda x: x[1]["duration"])
            cid, info = top
            hours, remainder = divmod(info["duration"].seconds, 3600)
            minutes = remainder // 60
            embed.add_field(
                name="Controller of the Day",
                value=f"CID {cid}\nTotal: {hours}h {minutes}m",
                inline=False
            )
        else:
            embed.add_field(name="Longest ATC Session", value="No sessions", inline=False)
            embed.add_field(name="Controller of the Day", value="No controllers logged", inline=False)

        embed.set_footer(text="Levant vACC Operations")
        embed.set_image(url="https://your-custom-banner.png")  # optional
        return embed

# -----------------------------
# Flask Web Server (keeps Render alive)
# -----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Levant vACC Bot is running!"

def run_discord_bot():
    token = os.environ.get("DISCORD_TOKEN")
    client = MyClient(intents=intents)
    client.run(token)

# Run Discord bot in a background thread
threading.Thread(target=run_discord_bot, daemon=True).start()

# -----------------------------
# Start Flask (main Render process)
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
