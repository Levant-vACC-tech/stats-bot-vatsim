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
CHANNEL_ID = 1423190842641743912  # Replace with your Discord channel ID
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
                    # Post report daily at 01:00 UTC
                    # -----------------------------
                    utc_now = datetime.utcnow()
                    if utc_now.hour == 1 and self.last_report_date != utc_now.date():
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

        # Add large Discord-hosted banner image
        embed.set_image(url=BANNER_URL)
        embed.set_footer(text="Levant vACC Operations")
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
