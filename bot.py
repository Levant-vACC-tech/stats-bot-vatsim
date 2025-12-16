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
        self.last_report_date = None
        self.last_check_time = None  # hold last timestamp for duration calc

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
                print("🌍 Fetching VATSIM data...")
                r = requests.get(VATSIM_DATA_URL, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    now = datetime.now(timezone.utc)

                    # -----------------------------
                    # Flights tracking
                    # -----------------------------
                    for pilot in data.get("pilots", []):
                        callsign = pilot.get("callsign", "").strip()
                        if not callsign:
                            continue

                        fp = pilot.get("flight_plan", {}) or {}
                        dep = (fp.get("departure") or "").strip().upper()
                        arr = (fp.get("arrival") or "").strip().upper()

                        if not dep and not arr:
                            continue

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
                    # ATC tracking
                    # -----------------------------
                    active_cids = set()

                    for atc in data.get("controllers", []):
                        callsign = atc.get("callsign", "")
                        cid = atc.get("cid")
                        if not cid or not callsign:
                            continue

                        # detect both FIR and airport controllers
                        if any(fir in callsign for fir in FIRS) or any(
                            icao in callsign for icao in AIRPORTS
                        ):
                            active_cids.add(cid)

                            if cid not in self.atc_sessions:
                                self.atc_sessions[cid] = {
                                    "callsign": callsign,
                                    "start": now,
                                    "duration": timedelta(),
                                }
                                print(f"🧑✈️ Started ATC session: {callsign}")

                    # update duration
                    if self.last_check_time is not None:
                        elapsed = now - self.last_check_time
                        for cid in active_cids:
                            if cid in self.atc_sessions:
                                self.atc_sessions[cid]["duration"] += elapsed

                    # remove inactive controllers (ended sessions)
                    ended_cids = [
                        cid for cid in self.atc_sessions if cid not in active_cids
                    ]
                    for cid in ended_cids:
                        print(
                            f"🛑 ATC session ended: {self.atc_sessions[cid]['callsign']}"
                        )

                    self.last_check_time = now

                    # -----------------------------
                    # Daily report
                    # -----------------------------
                    utc_now = datetime.utcnow()
                    if utc_now.hour == 1 and self.last_report_date != utc_now.date():
                        print("📊 Sending daily report...")
                        embed = self.generate_report()
                        await channel.send(embed=embed)
                        self.last_report_date = utc_now.date()

                        # reset for next day
                        self.flights = []
                        self.atc_sessions = {}
                        self.last_check_time = None

                else:
                    print(f"⚠️ Failed to fetch data (HTTP {r.status_code})")

            except Exception as e:
                print(f"❌ Error fetching VATSIM data: {e}")

            await asyncio.sleep(60)

    # -----------------------------
    # Generate daily report
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
            atc_count = sum(1 for s in self.atc_sessions.values() if icao in s["callsign"])

            embed.add_field(
                name=f"{icao} – {name}",
                value=f"Departures: {departures}\nArrivals: {arrivals}\nATC Sessions: {atc_count}",
                inline=False,
            )

        # -----------------------------
        # Longest ATC session
        # -----------------------------
        if self.atc_sessions:
            longest = max(
                self.atc_sessions.items(), key=lambda x: x[1]["duration"]
            )
            cid, info = longest
            dur_h = info["duration"].seconds // 3600
            dur_m = (info["duration"].seconds % 3600) // 60
            embed.add_field(
                name="🏆 Longest ATC Session",
                value=f"{info['callsign']} — {dur_h}h {dur_m}m ({cid})",
                inline=False,
            )

            # Controller of the day (most time in total)
            controller_of_the_day = max(
                self.atc_sessions.items(), key=lambda x: x[1]["duration"]
            )
            _, info2 = controller_of_the_day
            embed.add_field(
                name="👨✈️ Controller of the Day",
                value=f"{info2['callsign']} — {int(info2['duration'].total_seconds() // 3600)}h {(info2['duration'].seconds % 3600)//60}m",
                inline=False,
            )
        else:
            embed.add_field(
                name="No ATC Activity",
                value="No controllers recorded today.",
                inline=False,
            )

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