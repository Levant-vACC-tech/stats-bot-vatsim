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
    "ORBI": "🇮🇶 Baghdad",
}

FIRS = ["OLBB", "OSTT", "ORBB"]

BANNER_URL = (
    "https://cdn.discordapp.com/attachments/1133008419142500434/"
    "1423108256594661457/BANNER.png"
)
intents = discord.Intents.default()

# -----------------------------
# Discord Bot
# -----------------------------
class MyClient(discord.Client):
    def __init__(self, *, intents):
        super().__init__(intents=intents)
        self.flights = []
        self.atc_sessions = {}
        self.last_report_date = None  # Prevent double posts

    async def setup_hook(self):
        # start background task
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
                print("🌍 Fetching VATSIM data...")
                r = requests.get(VATSIM_DATA_URL, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    now = datetime.now(timezone.utc)

                    # -----------------------------
                    # Track flights
                    # -----------------------------
                    for pilot in data.get("pilots", []):
                        callsign = pilot.get("callsign", "").strip()
                        if not callsign:
                            continue

                        fp = pilot.get("flight_plan", {}) or {}
                        dep = fp.get("departure")
                        arr = fp.get("arrival")

                        if not dep and not arr:
                            continue

                        dep = dep.strip().upper() if dep else None
                        arr = arr.strip().upper() if arr else None

                        # Only record flights linked to monitored airports
                        if (dep and dep in AIRPORTS) or (arr and arr in AIRPORTS):
                            exists = any(
                                f["callsign"] == callsign
                                and f["dep"] == dep
                                and f["arr"] == arr
                                for f in self.flights
                            )
                            if not exists:
                                self.flights.append(
                                    {"callsign": callsign, "dep": dep, "arr": arr, "time": now}
                                )
                                print(f"✈️ Logged {callsign}: {dep or 'UNK'} ➜ {arr or 'UNK'}")

                    # -----------------------------
                    # Track ATC sessions
                    # -----------------------------
                    for atc in data.get("controllers", []):
                        callsign = atc.get("callsign", "")
                        cid = atc.get("cid")
                        if not cid:
                            continue

                        if any(fir in callsign for fir in FIRS):
                            if cid not in self.atc_sessions:
                                self.atc_sessions[cid] = {
                                    "callsign": callsign,
                                    "start": now,
                                    "duration": timedelta(),
                                }
                                print(f"🧑✈️ Started ATC session: {callsign}")
                            else:
                                self.atc_sessions[cid]["duration"] += timedelta(minutes=1)

                    # -----------------------------
                    # Post report daily at 01:00 UTC
                    # -----------------------------
                    utc_now = datetime.utcnow()
                    if utc_now.hour == 1 and self.last_report_date != utc_now.date():
                        print("📊 Sending daily report...")
                        embed = self.generate_report()
                        await channel.send(embed=embed)
                        self.last_report_date = utc_now.date()

                        # Reset for next day
                        self.flights = []
                        self.atc_sessions = {}

                else:
                    print(f"⚠️ Failed to fetch data (HTTP {r.status_code})")

            except Exception as e:
                print(f"❌ Error fetching VATSIM data: {e}")

            await asyncio.sleep(60)

    # -----------------------------
    # Generate Daily Report
    # -----------------------------
    def generate_report(self):
        embed = discord.Embed(
            title=f"Daily VATSIM Report - {datetime.utcnow().strftime('%Y-%m-%d')}",
            description="Summary of Departures, Arrivals, and ATC Activity",
            color=0x1ABC9C,
        )

        for icao, name in AIRPORTS.items():
            arrivals = sum(1 for f in self.flights if f["arr"] == icao)
            departures = sum(1 for f in self.flights if f["dep"] == icao)
            sessions = sum(
                1 for cid, s in self.atc_sessions.items() if icao in s["callsign"]
            )

            embed.add_field(
                name=f"{icao} – {name}",
                value=f"Departures: {departures}\nArrivals: {arrivals}\nATC Sessions: {sessions}",
                inline=False,
            )

        # FIR summary
        fir_activity = [
            s["callsign"] for s in self.atc_sessions.values() if any(f in s["callsign"] for f in FIRS)
        ]
        if fir_activity:
            firs_list = "\n".join(sorted(set(fir_activity)))
            embed.add_field(name="FIR ATC Online", value=firs_list, inline=False)
        else:
            embed.add_field(name="FIR ATC Online", value="No FIR controllers found", inline=False)

        # Longest ATC session
        if self.atc_sessions:
            longest = max(self.atc_sessions.items(), key=lambda x: x[1]["duration"])
            cid, info = longest
            hours, remainder = divmod(info["duration"].seconds, 3600)
            minutes = remainder // 60
            embed.add_field(
                name="Longest ATC Session",
                value=f"{info['callsign']} – {hours}h {minutes}m ({cid})",
                inline=False,
            )
        else:
            embed.add_field(name="Longest ATC Session", value="No sessions", inline=False)

        embed.set_image(url=BANNER_URL)
        embed.set_footer(text="Levant vACC Operations")
        return embed


# -----------------------------
# Flask Web Server (keep alive)
# -----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Levant vACC Daily Stats Bot is running!"

def run_discord_bot():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN environment variable is missing!")
        return

    client = MyClient(intents=intents)
    client.run(token)


threading.Thread(target=run_discord_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)