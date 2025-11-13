# -*- coding: utf-8 -*-
import os
import asyncio
import json
import re
from datetime import datetime
from discord.ext import commands, tasks
from discord import Intents, Status, Game, Embed, Colour
from rcon.asyncio import RconAsync, RCONException

# ==============================================================================
# ⚠️ CONFIGURATION BLOCK ⚠️
# Update these settings before running the bot.
# ==============================================================================

# --- DISCORD CONFIGURATION ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', "YOUR_DISCORD_BOT_TOKEN_HERE")
TARGET_CHANNEL_ID = int(os.getenv('TARGET_CHANNEL_ID', 0)) # Channel for joins/leaves/auto-saves
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', TARGET_CHANNEL_ID)) # Channel for admin/error logs

# --- MINECRAFT RCON CONFIGURATION ---
MC_RCON_HOST = os.getenv('MC_RCON_HOST', "127.0.0.1")
MC_RCON_PORT = int(os.getenv('MC_RCON_PORT', 25575))
MC_RCON_PASSWORD = os.getenv('MC_RCON_PASSWORD', "YOUR_MC_RCON_PASSWORD_HERE")

# --- PALWORLD RCON CONFIGURATION ---
PAL_RCON_HOST = os.getenv('PAL_RCON_HOST', "127.0.0.1")
PAL_RCON_PORT = int(os.getenv('PAL_RCON_PORT', 25576))
PAL_RCON_PASSWORD = os.getenv('PAL_RCON_PASSWORD', "YOUR_PAL_RCON_PASSWORD_HERE")

# --- ARK: SURVIVAL ASCENDED RCON CONFIGURATION ---
ASA_RCON_HOST = os.getenv('ASA_RCON_HOST', "127.0.0.1")
ASA_RCON_PORT = int(os.getenv('ASA_RCON_PORT', 27020))
ASA_RCON_PASSWORD = os.getenv('ASA_RCON_PASSWORD', "YOUR_ASA_RCON_PASSWORD_HERE")

# --- GENERIC SRCDS (Source Engine, e.g., CS:GO, TF2, GMod) RCON CONFIGURATION ---
# Use this for any Steam game that uses the standard Source RCON protocol.
SRCDS_RCON_HOST = os.getenv('SRCDS_RCON_HOST', "127.0.0.1")
SRCDS_RCON_PORT = int(os.getenv('SRCDS_RCON_PORT', 27015))
SRCDS_RCON_PASSWORD = os.getenv('SRCDS_RCON_PASSWORD', "YOUR_SRCDS_RCON_PASSWORD_HERE")


# --- BOT CONSTANTS ---
PREFIX = "!server-"
RCON_CHECK_INTERVAL_SECONDS = 30
STATISTICS_FILE = "player_stats.json"

# ==============================================================================
# GLOBAL STATE & PERSISTENCE
# ==============================================================================

# Global bot instance
intents = Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Global data structure for tracking player statistics (first join, playtime)
player_stats = {}
# Dictionary to hold active RCON connections
rcon_clients = {}
# Current players for live monitoring
current_mc_players = set()
current_pal_players = set()
current_asa_players = set()
current_srcds_players = set() # New server state
# Player join timestamps (for calculating session time)
mc_join_times = {}
pal_join_times = {}
asa_join_times = {}
srcds_join_times = {} # New server state


def load_stats():
    """Loads player statistics from a JSON file."""
    global player_stats
    if os.path.exists(STATISTICS_FILE):
        with open(STATISTICS_FILE, 'r') as f:
            try:
                player_stats = json.load(f)
            except json.JSONDecodeError:
                print("Warning: Failed to decode player_stats.json. Starting fresh.")
                player_stats = {}
    else:
        player_stats = {}

def save_stats():
    """Saves player statistics to a JSON file."""
    with open(STATISTICS_FILE, 'w') as f:
        json.dump(player_stats, f, indent=4)

def update_player_join(game: str, player: str):
    """Updates player stats upon joining."""
    # Use format: game:player_name for the key
    player_key = f"{game}:{player}"
    now = datetime.now()
    
    # 1. Update Persistent Stats (First Join)
    if player_key not in player_stats:
        player_stats[player_key] = {
            "first_join": now.strftime("%Y-%m-%d %H:%M:%S"),
            "total_playtime_seconds": 0
        }
        save_stats()
        
    # 2. Update Live Join Times (for session tracking)
    if game == 'mc':
        mc_join_times[player] = now
    elif game == 'pal':
        pal_join_times[player] = now
    elif game == 'asa':
        asa_join_times[player] = now
    elif game == 'srcds':
        srcds_join_times[player] = now


def update_player_leave(game: str, player: str):
    """Updates player stats upon leaving and calculates playtime."""
    player_key = f"{game}:{player}"
    
    join_time = None
    if game == 'mc' and player in mc_join_times:
        join_time = mc_join_times.pop(player)
    elif game == 'pal' and player in pal_join_times:
        join_time = pal_join_times.pop(player)
    elif game == 'asa' and player in asa_join_times:
        join_time = asa_join_times.pop(player)
    elif game == 'srcds' and player in srcds_join_times:
        join_time = srcds_join_times.pop(player)
    
    if join_time is None:
        # Player wasn't tracked (e.g., bot restarted while they were online)
        return

    session_duration = (datetime.now() - join_time).total_seconds()
    
    if player_key in player_stats:
        player_stats[player_key]["total_playtime_seconds"] += session_duration
        save_stats()

def format_duration(seconds: float) -> str:
    """Formats seconds into Hh Mmin Ssec string."""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}min")
    parts.append(f"{seconds}sec")
    
    return " ".join(parts) or "0sec"


# ==============================================================================
# RCON CONNECTION MANAGER AND EXTRACTORS
# ==============================================================================

class RconManager:
    """Manages the RCON connection and state for a single game."""
    def __init__(self, host, port, password, game_name, list_command, player_name_extractor):
        self.game_name = game_name
        self.host = host
        self.port = port
        self.password = password
        self.list_command = list_command
        self.player_name_extractor = player_name_extractor
        self.client = None
        self.connected = False
        self.last_error = None
        self.channel = None

    async def connect(self):
        """Attempts to establish RCON connection."""
        if self.connected and self.client:
            return True

        try:
            self.client = RconAsync(self.host, self.port, self.password)
            await self.client.connect()
            self.connected = True
            self.last_error = None
            return True
        except (RCONException, asyncio.TimeoutError, ConnectionRefusedError, Exception) as e:
            self.connected = False
            self.client = None
            self.last_error = str(e)
            return False

    async def send_command(self, command: str) -> str:
        """Sends a command, reconnecting if necessary."""
        if not await self.connect():
            return f"ERROR: Not connected. Last RCON failure: {self.last_error}"

        try:
            response = await self.client.send(command)
            return response.strip()
        except RCONException as e:
            self.connected = False
            self.last_error = str(e)
            return f"ERROR: Command failed and connection dropped ({e})."
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            return f"ERROR: An unexpected RCON error occurred: {e}"

    async def get_players(self) -> tuple[set, str]:
        """Sends the list command and returns player set and raw response."""
        response = await self.send_command(self.list_command)
        
        if response.startswith("ERROR:"):
            return set(), response
        
        return self.player_name_extractor(response), response

# --- Palworld specific logic ---
def pal_player_extractor(response: str) -> set:
    """Parses Palworld's ShowPlayers RCON output."""
    players = set()
    lines = response.split('\n')[1:] # Skip header
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 1:
            name = parts[0].strip()
            if name:
                players.add(name)
    return players

# --- Minecraft specific logic ---
def mc_player_extractor(response: str) -> set:
    """Parses Minecraft's list RCON output."""
    players = set()
    if ':' in response:
        player_list_str = response.split(':', 1)[1].strip()
        player_names = [name.strip() for name in player_list_str.split(',') if name.strip()]
        players.update(player_names)
    return players

# --- ASA specific logic ---
def asa_player_extractor(response: str) -> set:
    """Parses ARK: Survival Ascended's ListPlayers RCON output."""
    players = set()
    matches = re.findall(r'Name: (.+?)\n', response, re.DOTALL)
    for match in matches:
        name = match.strip()
        if name and not name.startswith("ID:"):
             players.add(name)
    return players
    
# --- Generic SRCDS (Source Engine) logic ---
def srcds_player_extractor(response: str) -> set:
    """Parses Source Engine's 'status' RCON output (CS:GO, TF2, GMod)."""
    players = set()
    # SRCDS 'status' lines look like: # 1   "PlayerName" STEAM_X:X:XXXXX 00:00 0   400   0
    for line in response.split('\n'):
        # Match player name enclosed in quotes after the index
        match = re.search(r'^\s*#\s*\d+\s+"(.+?)"', line)
        if match:
            # Skip BOTs or generic names if desired, but here we take everything matched
            name = match.group(1).strip()
            if name:
                players.add(name)
    return players


# Initialize RCON managers
mc_monitor = RconManager(
    host=MC_RCON_HOST, 
    port=MC_RCON_PORT, 
    password=MC_RCON_PASSWORD, 
    game_name="Minecraft", 
    list_command="list",
    player_name_extractor=mc_player_extractor
)
pal_monitor = RconManager(
    host=PAL_RCON_HOST, 
    port=PAL_RCON_PORT, 
    password=PAL_RCON_PASSWORD, 
    game_name="Palworld", 
    list_command="ShowPlayers", 
    player_name_extractor=pal_player_extractor
)
asa_monitor = RconManager(
    host=ASA_RCON_HOST, 
    port=ASA_RCON_PORT, 
    password=ASA_RCON_PASSWORD, 
    game_name="ASA", 
    list_command="ListPlayers",
    player_name_extractor=asa_player_extractor
)
srcds_monitor = RconManager( # New SRCDS monitor
    host=SRCDS_RCON_HOST, 
    port=SRCDS_RCON_PORT, 
    password=SRCDS_RCON_PASSWORD, 
    game_name="SRCDS", 
    list_command="status", # Source Engine list command is typically 'status'
    player_name_extractor=srcds_player_extractor
)


# ==============================================================================
# DISCORD EVENTS AND TASKS
# ==============================================================================

@bot.event
async def on_ready():
    """Executed when the bot is connected to Discord."""
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    await bot.change_presence(activity=Game(f"Monitoring 4 Servers | {PREFIX}help"))

    # Load persistent data
    load_stats()
    
    # Set channels for RCON managers
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    mc_monitor.channel = channel
    pal_monitor.channel = channel
    asa_monitor.channel = channel
    srcds_monitor.channel = channel # Set channel for new manager

    if not channel:
        print(f"ERROR: Channel ID {TARGET_CHANNEL_ID} not found. Monitoring tasks will not start.")
        return

    # Start background tasks
    if not player_monitor_task.running:
        player_monitor_task.start()
        print("Player monitoring task started.")
    if not scheduled_actions_task.running:
        scheduled_actions_task.start()
        print("Scheduled actions task started.")


@tasks.loop(seconds=RCON_CHECK_INTERVAL_SECONDS)
async def player_monitor_task():
    """Background task to continuously check players and report joins/leaves for all servers."""
    global current_mc_players, current_pal_players, current_asa_players, current_srcds_players

    async def check_server(monitor: RconManager, game_code: str, current_set: set) -> set:
        """Helper function to perform checks for one server."""
        try:
            new_players, raw_response = await monitor.get_players()
        except Exception as e:
            if current_set:
                 await monitor.channel.send(f"⚠️ **{monitor.game_name} Alert:** Lost RCON connectivity ({e}). Status monitoring paused.")
            return set()

        if "ERROR:" in raw_response:
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"⚠️ **{monitor.game_name} RCON Error:** {raw_response}")
            return current_set 

        # Check for Joins
        joined_players = new_players - current_set
        for player in joined_players:
            update_player_join(game_code, player)
            embed = Embed(
                title=f"🟢 Player Joined ({monitor.game_name})",
                description=f"**{player}** has joined the server.",
                color=Colour.green()
            )
            await monitor.channel.send(embed=embed)

        # Check for Leaves
        left_players = current_set - new_players
        for player in left_players:
            update_player_leave(game_code, player)
            embed = Embed(
                title=f"🔴 Player Left ({monitor.game_name})",
                description=f"**{player}** has left the server. Session duration logged.",
                color=Colour.red()
            )
            await monitor.channel.send(embed=embed)

        return new_players

    # Check Minecraft
    current_mc_players = await check_server(mc_monitor, 'mc', current_mc_players)
    
    # Check Palworld
    current_pal_players = await check_server(pal_monitor, 'pal', current_pal_players)
    
    # Check ASA
    current_asa_players = await check_server(asa_monitor, 'asa', current_asa_players)
    
    # Check SRCDS/Generic Steam Game
    current_srcds_players = await check_server(srcds_monitor, 'srcds', current_srcds_players)


@tasks.loop(hours=1) # Run every hour for auto-save
async def scheduled_actions_task():
    """Performs scheduled maintenance tasks like auto-save."""
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        return

    # --- Minecraft Auto-Save ---
    mc_response = await mc_monitor.send_command("save-all")
    if "ERROR:" not in mc_response:
        await channel.send("✅ **[Minecraft Auto-Save]** World state successfully saved.")
    else:
        await channel.send(f"❌ **[Minecraft Auto-Save Failed]** {mc_response}")
        
    # --- Palworld Auto-Save ---
    pal_response = await pal_monitor.send_command("Save") 
    if "ERROR:" not in pal_response:
        await channel.send("✅ **[Palworld Auto-Save]** World state successfully saved.")
    else:
        await channel.send(f"❌ **[Palworld Auto-Save Failed]** {pal_response}")
        
    # --- ASA Auto-Save ---
    asa_response = await asa_monitor.send_command("SaveWorld")
    if "ERROR:" not in asa_response:
        await channel.send("✅ **[ASA Auto-Save]** World state successfully saved.")
    else:
        await channel.send(f"❌ **[ASA Auto-Save Failed]** {asa_response}")
        
    # --- SRCDS Maintenance (e.g., version check) ---
    # SRCDS games typically don't need 'save-all', so we run a benign command like 'version'
    srcds_response = await srcds_monitor.send_command("version") 
    if "ERROR:" not in srcds_response:
        await channel.send("☑️ **[SRCDS Check]** Server successfully checked version.")
    else:
        await channel.send(f"❌ **[SRCDS Maintenance Failed]** Could not run command. {srcds_response}")


# ==============================================================================
# DISCORD COMMANDS (GENERIC SRCDS / STEAM GAMES)
# ==============================================================================

@bot.group(name="srcds", invoke_without_command=True)
async def srcds(ctx):
    """Generic SRCDS (Source/Steam Game) administration commands."""
    await ctx.send(f"Use `{PREFIX}srcds-help` for SRCDS commands.")

@srcds.command(name="help")
async def srcds_help_command(ctx):
    """Displays a list of generic SRCDS administrative commands."""
    help_text = f"""
    __**SRCDS Admin Commands ({PREFIX}srcds-)**__
    *Generic commands for Source Engine-based games (e.g., CS:GO, TF2, GMod).*
    *All commands require **Administrator** permission in Discord.*

    **!server-srcds-status**
    > Shows the current player count and RCON connection health.

    **!server-srcds-players**
    > Lists all currently logged-in players (names, playtime, stats).

    **!server-srcds-say <message>**
    > Sends a message to the in-game chat, prefixed by `[Discord Admin]`.

    **!server-srcds-kick <Name>**
    > Kicks a player using their exact in-game Name.
    """
    embed = Embed(title="⚙️ SRCDS Admin Help (Generic Steam)", description=help_text, color=Colour.from_rgb(100, 149, 237))
    await ctx.send(embed=embed)

@srcds.command(name="status")
@commands.has_permissions(administrator=True)
async def srcds_status_command(ctx):
    """Checks the current SRCDS server status and player count."""
    if not await srcds_monitor.connect():
        embed = Embed(
            title="🔴 SRCDS Server Status",
            description=f"RCON Connection Failed to **{srcds_monitor.host}:{srcds_monitor.port}**.\nLast Error: `{srcds_monitor.last_error}`",
            color=Colour.red()
        )
    else:
        players, _ = await srcds_monitor.get_players()
        embed = Embed(
            title="🟢 SRCDS Server Status",
            description=f"**Online and Responsive**\n\nPlayers Online: **{len(players)}**",
            color=Colour.green()
        )
        embed.add_field(name="RCON Endpoint", value=f"`{srcds_monitor.host}:{srcds_monitor.port}`", inline=False)

    await ctx.send(embed=embed)


@srcds.command(name="players")
@commands.has_permissions(administrator=True)
async def srcds_players_command(ctx):
    """Lists all SRCDS players currently online with stats."""
    players, raw_response = await srcds_monitor.get_players()

    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **SRCDS RCON Error:** Could not retrieve player list. {raw_response}")
        return

    if not players:
        embed = Embed(title="⚙️ SRCDS Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_details = []
    
    for name in sorted(players):
        stats_key = f"srcds:{name}"
        stats = player_stats.get(stats_key, {})

        # Calculate current session time
        session_time_str = "N/A"
        if name in srcds_join_times:
            session_seconds = (datetime.now() - srcds_join_times[name]).total_seconds()
            session_time_str = format_duration(session_seconds)
            
        total_time_str = format_duration(stats.get("total_playtime_seconds", 0))
        first_join = stats.get("first_join", "Unknown")
        
        player_details.append(
            f"**{name}**\n"
            f"• Session: {session_time_str}\n"
            f"• Total Time: {total_time_str}\n"
            f"• First Join: {first_join}"
        )

    embed = Embed(
        title=f"⚙️ SRCDS Online Players ({len(players)})",
        description="List of currently logged-in players:",
        color=Colour.blue()
    )
    embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_details), inline=False)
    await ctx.send(embed=embed)


@srcds.command(name="say")
@commands.has_permissions(administrator=True)
async def srcds_say_command(ctx, *, message: str):
    """Sends a message to the in-game chat for SRCDS games."""
    # Source Engine command for chat message: say <message>
    command = f"say [Discord Admin] {message}" 
    response = await srcds_monitor.send_command(command)

    if "ERROR:" in response:
        await ctx.send(f"❌ **SRCDS Message Failed!** {response}")
    else:
        embed = Embed(
            title="💬 SRCDS Message Sent",
            description=f"Message: *{message}*",
            color=Colour.gold()
        )
        await ctx.send(embed=embed)


@srcds.command(name="kick")
@commands.has_permissions(administrator=True)
async def srcds_kick_command(ctx, *, name: str):
    """Kicks a SRCDS player using their in-game name."""
    command = f"kick \"{name}\"" # SRCDS often requires quotes around names
    response = await srcds_monitor.send_command(command)

    if "ERROR:" in response:
        await ctx.send(f"❌ **SRCDS Kick Failed!** Make sure the player name (`{name}`) is exact and the player is online. Response: {response}")
    else:
        embed = Embed(
            title="👟 SRCDS Player Kicked",
            description=f"Player **{name}** has been kicked from the server.",
            color=Colour.orange()
        )
        await ctx.send(embed=embed)

# ==============================================================================
# DISCORD COMMANDS (PALWORLD, ASA, MINECRAFT - REMAINING COMMANDS OMITTED FOR BREVITY)
# ... (The existing ASA, Palworld, and Minecraft commands remain unchanged below this point)
# ==============================================================================
# RUN BOT
# ==============================================================================

if not DISCORD_TOKEN or TARGET_CHANNEL_ID == 0 or not MC_RCON_PASSWORD or not PAL_RCON_PASSWORD or not ASA_RCON_PASSWORD or not SRCDS_RCON_PASSWORD:
    print("\n\n--------------------------------------------------------------")
    print("FATAL ERROR: Please update the CONFIGURATION BLOCK in the script.")
    print("You must provide all RCON details, even if only one server is used.")
    print("--------------------------------------------------------------\n")
else:
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"\n\nFATAL RUNTIME ERROR: {e}")
        print("Check if your DISCORD_TOKEN is valid and that you have installed discord.py and python-rcon.")
