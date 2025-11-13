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
# ⚠️ CRITICAL CONFIGURATION BLOCK ⚠️
# You MUST update these settings before running the bot.
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
SRCDS_RCON_HOST = os.getenv('SRCDS_RCON_HOST', "127.0.0.1")
SRCDS_RCON_PORT = int(os.getenv('SRCDS_RCON_PORT', 27015))
SRCDS_RCON_PASSWORD = os.getenv('SRCDS_RCON_PASSWORD', "YOUR_SRCDS_RCON_PASSWORD_HERE")


# --- BOT CONSTANTS ---
PREFIX = "!server-"
RCON_CHECK_INTERVAL_SECONDS = 30
STATISTICS_FILE = "player_stats.json"
PALWORLD_BLACKLIST_FILE = "palworld_blacklist.txt"

# ==============================================================================
# GLOBAL STATE & PERSISTENCE
# ==============================================================================

intents = Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Global data structure for tracking player statistics (first join, playtime)
player_stats = {}
# Current players for live monitoring
current_mc_players = set()
current_pal_players = set()
current_asa_players = set()
current_srcds_players = set()
# Player join timestamps (for calculating session time)
mc_join_times = {}
pal_join_times = {}
asa_join_times = {}
srcds_join_times = {}

# Global set for blacklisted Palworld Steam IDs
palworld_blacklist = set()


def load_stats():
    """Loads player statistics from a JSON file."""
    global player_stats
    if os.path.exists(STATISTICS_FILE):
        with open(STATISTICS_FILE, 'r') as f:
            try:
                player_stats = json.load(f)
            except (json.JSONDecodeError, Exception):
                print("Warning: Failed to load/decode player_stats.json. Starting fresh.")
                player_stats = {}
    else:
        player_stats = {}

def save_stats():
    """Saves player statistics to a JSON file."""
    temp_file = STATISTICS_FILE + ".tmp"
    try:
        with open(temp_file, 'w') as f:
            json.dump(player_stats, f, indent=4)
        os.replace(temp_file, STATISTICS_FILE)
    except Exception as e:
        print(f"Error saving stats: {e}")

# NEW: Function to save the blacklist
def save_palworld_blacklist():
    """Saves the Palworld blacklist set to the text file."""
    temp_file = PALWORLD_BLACKLIST_FILE + ".tmp"
    try:
        with open(temp_file, 'w') as f:
            f.write("# Palworld Steam ID Blacklist (one ID per line)\n")
            for steam_id in sorted(palworld_blacklist):
                f.write(f"{steam_id}\n")
        os.replace(temp_file, PALWORLD_BLACKLIST_FILE)
        print(f"[INFO] Palworld blacklist saved with {len(palworld_blacklist)} IDs.")
    except Exception as e:
        print(f"[ERROR] Error saving Palworld blacklist: {e}")

# Corrected blacklist loading function (logs to console to avoid Discord spam)
def load_palworld_blacklist():
    """Loads Palworld Steam IDs from the blacklist file."""
    global palworld_blacklist
    if not os.path.exists(PALWORLD_BLACKLIST_FILE):
        palworld_blacklist = set()
        return
    try:
        with open(PALWORLD_BLACKLIST_FILE, 'r') as f:
            # Read lines, strip whitespace, filter out comments (#) and empty lines
            new_blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
            palworld_blacklist = new_blacklist
            print(f"[INFO] Palworld blacklist reloaded with {len(palworld_blacklist)} IDs.")
    except Exception as e:
        print(f"[ERROR] Error loading Palworld blacklist: {e}")
        palworld_blacklist = set()


def update_player_join(game: str, player: str):
    """Updates player stats upon joining."""
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
        # Ensure 'total_playtime_seconds' exists before adding
        if "total_playtime_seconds" not in player_stats[player_key]:
            player_stats[player_key]["total_playtime_seconds"] = 0
            
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
            self.client = RconAsync(self.host, self.port, self.password, timeout=5)
            await self.client.connect()
            self.connected = True
            self.last_error = None
            return True
        except (RCONException, asyncio.TimeoutError, ConnectionRefusedError, OSError, Exception) as e:
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
        """Sends the list command and returns player set (for monitoring) and raw response (for commands)."""
        response = await self.send_command(self.list_command)
        
        if response.startswith("ERROR:"):
            return set(), response
        
        return self.player_name_extractor(response), response

# --- Palworld specific logic (for monitoring join/leave only) ---
def pal_player_extractor(response: str) -> set:
    """Parses Palworld's ShowPlayers RCON output (Name,UID,SteamID) to get only names."""
    players = set()
    lines = response.split('\n')[1:] # Skip header
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 1:
            name = parts[0].strip()
            if name and name != "Name": # Ensure we skip the header if it reappears
                players.add(name)
    return players

# --- Palworld specific logic (for command details) ---
def pal_player_details_extractor(response: str) -> list:
    """Parses Palworld's ShowPlayers RCON output into a list of dictionaries."""
    details = []
    lines = response.split('\n')[1:] # Skip header
    for line in lines:
        parts = [p.strip() for p in line.split(',', 2)] # Name,UID,SteamID
        if len(parts) == 3 and parts[0] != "Name":
            name, uid, steam_id = parts
            details.append({"name": name, "uid": uid, "steam_id": steam_id})
    return details


# --- Minecraft specific logic ---
def mc_player_extractor(response: str) -> set:
    """Parses Minecraft's list RCON output."""
    players = set()
    # Example: "There are 1 of a max of 20 players online: PlayerName"
    if ':' in response:
        player_list_str = response.split(':', 1)[1].strip()
        player_names = [name.strip() for name in player_list_str.split(',') if name.strip()]
        players.update(player_names)
    return players

# --- ASA specific logic (for monitoring join/leave only) ---
def asa_player_extractor(response: str) -> set:
    """Parses ARK: Survival Ascended's ListPlayers RCON output (Name: PlayerName\nID: 123...\n) to get only names."""
    players = set()
    # Matches the Name: ... followed by a newline or end of string
    matches = re.findall(r'Name: (.+?)(?:\r?\n|$)', response, re.DOTALL)
    for match in matches:
        name = match.strip()
        # ARK list players sometimes includes 'ID: 123...' lines, ensure we only capture names
        if name and not name.startswith("ID:"):
            players.add(name)
    return players

# --- ASA specific logic (for command details) ---
def asa_player_details_extractor(response: str) -> list:
    """Parses ARK: Survival Ascended's ListPlayers RCON output into a list of dictionaries."""
    details = []
    current_player = {}
    
    for line in response.split('\n'):
        line = line.strip()
        if line.startswith("Name:"):
            # Start of a new player entry
            if current_player and current_player.get("name"):
                details.append(current_player)
            current_player = {"name": line.split(':', 1)[1].strip()}
        elif line.startswith("SteamID:") and current_player.get("name"):
            current_player["steam_id"] = line.split(':', 1)[1].strip()
        elif line.startswith("PlayerID:") and current_player.get("name"):
            current_player["player_id"] = line.split(':', 1)[1].strip()
            
    # Append the last player found
    if current_player and current_player.get("name"):
        details.append(current_player)

    return details
    
# --- Generic SRCDS (Source Engine) logic ---
def srcds_player_extractor(response: str) -> set:
    """Parses Source Engine's 'status' RCON output (CS:GO, TF2, GMod)."""
    players = set()
    # SRCDS 'status' lines look like: # 1    "PlayerName" STEAM_X:X:XXXXX 00:00 0    400    0
    for line in response.split('\n'):
        # Match player name enclosed in quotes after the index
        match = re.search(r'^\s*#\s*\d+\s+"(.+?)"', line)
        if match:
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
srcds_monitor = RconManager(
    host=SRCDS_RCON_HOST, 
    port=SRCDS_RCON_PORT, 
    password=SRCDS_RCON_PASSWORD, 
    game_name="SRCDS", 
    list_command="status",
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
    load_palworld_blacklist()
    
    # Set channels for RCON managers
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    mc_monitor.channel = channel
    pal_monitor.channel = channel
    asa_monitor.channel = channel
    srcds_monitor.channel = channel

    if not channel and TARGET_CHANNEL_ID != 0:
        print(f"ERROR: Target Channel ID {TARGET_CHANNEL_ID} not found. Monitoring tasks will not start.")
        return

    # Start background tasks
    if not player_monitor_task.running:
        player_monitor_task.start()
        print("Player monitoring task started.")
    if not scheduled_actions_task.running:
        scheduled_actions_task.start()
        print("Scheduled actions task started.")
    if not palworld_blacklist_reloader.running:
        palworld_blacklist_reloader.start()
        print("Palworld blacklist reloader started.")


@tasks.loop(minutes=5)
async def palworld_blacklist_reloader():
    """Reloads the Palworld blacklist periodically. Logs only to console during loop."""
    load_palworld_blacklist()


@tasks.loop(seconds=RCON_CHECK_INTERVAL_SECONDS)
async def player_monitor_task():
    """Background task to continuously check players and report joins/leaves for all servers."""
    global current_mc_players, current_pal_players, current_asa_players, current_srcds_players

    async def check_server(monitor: RconManager, game_code: str, current_set: set) -> set:
        """Helper function to perform checks for one server."""
        if not monitor.channel:
            return current_set

        try:
            new_players, raw_response = await monitor.get_players()
        except Exception as e:
            if current_set:
                await monitor.channel.send(f"⚠️ **{monitor.game_name} Alert:** Lost RCON connectivity ({e}). Status monitoring paused.")
            return set()

        if raw_response.startswith("ERROR:"):
            if current_set:
                 await monitor.channel.send(f"⚠️ **{monitor.game_name} Alert:** Lost RCON connectivity or command failed. Status monitoring paused.")
            
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"⚠️ **{monitor.game_name} RCON Error:** {raw_response}")
            return set()

        # --- PALWORLD BLACKLIST CHECK (Auto-kick logic) ---
        if game_code == 'pal' and palworld_blacklist:
            # Palworld RCON response format: Name,UID,SteamID (lines 2+)
            lines = raw_response.split('\n')[1:]
            
            for line in lines:
                parts = [p.strip() for p in line.split(',', 2)] # Name,UID,SteamID
                if len(parts) == 3 and parts[0] != "Name":
                    name, _, steam_id = parts
                    
                    if steam_id in palworld_blacklist:
                        # Player is blacklisted, auto-kick them
                        log_channel = bot.get_channel(LOG_CHANNEL_ID)
                        kick_response = await monitor.send_command(f"KickPlayer {steam_id}")
                        
                        if log_channel:
                            await log_channel.send(f"🚨 **Blacklist Auto-Kick (Palworld):** Player **{name}** (`{steam_id}`) was kicked. Response: `{kick_response[:50]}...`")
                        
                        # Remove kicked player from the 'new_players' set so they don't trigger join/leave notifications
                        new_players.discard(name)

        # Check for Joins
        joined_players = new_players - current_set
        for player in joined_players:
            update_player_join(game_code, player)
            embed = Embed(
                title=f"🟢 Player Joined ({monitor.game_name})",
                description=f"**{player}** has joined the server. Current Players: **{len(new_players)}**",
                color=Colour.green()
            )
            await monitor.channel.send(embed=embed)

        # Check for Leaves
        left_players = current_set - new_players
        for player in left_players:
            update_player_leave(game_code, player)
            embed = Embed(
                title=f"🔴 Player Left ({monitor.game_name})",
                description=f"**{player}** has left the server. Session duration logged. Current Players: **{len(new_players)}**",
                color=Colour.red()
            )
            await monitor.channel.send(embed=embed)

        return new_players

    # Check all servers concurrently
    mc_task = check_server(mc_monitor, 'mc', current_mc_players)
    pal_task = check_server(pal_monitor, 'pal', current_pal_players)
    asa_task = check_server(asa_monitor, 'asa', current_asa_players)
    srcds_task = check_server(srcds_monitor, 'srcds', current_srcds_players)
    
    results = await asyncio.gather(mc_task, pal_task, asa_task, srcds_task)
    
    current_mc_players, current_pal_players, current_asa_players, current_srcds_players = results


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
    srcds_response = await srcds_monitor.send_command("version") 
    if "ERROR:" not in srcds_response:
        await channel.send("☑️ **[SRCDS Check]** Server successfully checked version.")
    else:
        await channel.send(f"❌ **[SRCDS Maintenance Failed]** Could not run command. {srcds_response}")


# ==============================================================================
# DISCORD COMMANDS (GLOBAL)
# ==============================================================================

@bot.command(name="help")
async def general_help_command(ctx):
    """General help command listing all server categories."""
    help_text = f"""
    __**Multi-Game Monitor Commands**__
    Use `{PREFIX}<game>-help` (e.g., `!server-mine-help`) for specific commands.

    **Game Categories:**
    • **mine**: Minecraft Server Commands
    • **pal**: Palworld Server Commands
    • **asa**: ARK: Survival Ascended Server Commands
    • **srcds**: Generic Source Engine Commands (CS:GO, TF2, GMod, etc.)

    **Global Commands:**
    • **!server-status**: Shows quick status for all 4 servers.
    • **!server-stats-top <N>**: Shows the top N players by total playtime across all games.
    """
    embed = Embed(title="🎮 Multi-Game Monitor Bot Help", description=help_text, color=Colour.from_rgb(46, 204, 113))
    await ctx.send(embed=embed)

@bot.command(name="status")
@commands.has_permissions(administrator=True)
async def all_status_command(ctx):
    """Checks the status of all four monitored game servers."""
    
    async def get_single_status(monitor: RconManager):
        if await monitor.connect():
            players, _ = await monitor.get_players()
            return f"🟢 {monitor.game_name}: **{len(players)}** players online."
        else:
            return f"🔴 {monitor.game_name}: **Offline** (`{monitor.last_error}`)"

    statuses = await asyncio.gather(
        get_single_status(mc_monitor),
        get_single_status(pal_monitor),
        get_single_status(asa_monitor),
        get_single_status(srcds_monitor)
    )

    embed = Embed(
        title="🌐 All Server Status Check",
        description="\n".join(statuses),
        color=Colour.blue()
    )
    embed.set_footer(text=f"Check interval: {RCON_CHECK_INTERVAL_SECONDS}s")
    await ctx.send(embed=embed)


# ==============================================================================
# DISCORD COMMANDS (PLAYER STATISTICS)
# ==============================================================================

@bot.group(name="stats", invoke_without_command=True)
async def stats(ctx):
    """Player statistics commands."""
    await ctx.send(f"Use `{PREFIX}stats-top <N>` to see top players by playtime.")

@stats.command(name="top")
@commands.has_permissions(administrator=True)
async def stats_top_command(ctx, top_n: int = 10):
    """Shows the top N players by total playtime across all games."""
    if top_n <= 0 or top_n > 50:
        return await ctx.send("Please choose a number between 1 and 50.")

    # Convert player_stats dictionary into a sortable list of (player_key, total_playtime_seconds)
    top_players = []
    for player_key, data in player_stats.items():
        total_time = data.get("total_playtime_seconds", 0)
        game, name = player_key.split(':', 1)
        top_players.append({
            "name": name,
            "game": game.upper(),
            "time": total_time
        })

    # Sort by time, descending
    top_players.sort(key=lambda x: x['time'], reverse=True)

    # Format output
    top_players = top_players[:top_n]
    
    if not top_players:
        return await ctx.send("No player statistics recorded yet.")

    description = []
    for i, player in enumerate(top_players):
        time_str = format_duration(player['time'])
        description.append(f"**#{i+1}:** [{player['game']}] **{player['name']}** - {time_str}")

    embed = Embed(
        title=f"🏆 Top {len(top_players)} Players by Total Playtime",
        description="\n".join(description),
        color=Colour.from_rgb(255, 165, 0)
    )
    await ctx.send(embed=embed)


# ==============================================================================
# DISCORD COMMANDS (GENERIC SRCDS / STEAM GAMES) - (Lines 600-850)
# (SRCDS/Mine/Pal commands from original file + missing ASA and Palworld completions)
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
    command = f"kick \"{name}\"" 
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
# DISCORD COMMANDS (MINECRAFT)
# ==============================================================================

@bot.group(name="mine", invoke_without_command=True)
async def mine(ctx):
    """Minecraft administration commands."""
    await ctx.send(f"Use `{PREFIX}mine-help` for Minecraft commands.")

@mine.command(name="help")
async def mc_help_command(ctx):
    help_text = f"""
    __**Minecraft Admin Commands ({PREFIX}mine-)**__
    *All commands require **Administrator** permission in Discord.*

    **!server-mine-status**
    > Shows the current player count and RCON connection health.

    **!server-mine-players**
    > Lists all currently logged-in players (names, playtime, stats).

    **!server-mine-say <message>**
    > Sends a message to the in-game chat, prefixed by `[Discord Admin]`.

    **!server-mine-save**
    > Forces the world to save (`save-all`).

    **!server-mine-kick <Name>**
    > Kicks a player using their exact in-game name.

    **!server-mine-ban <Name>**
    > Bans a player using their exact in-game name.
    """
    embed = Embed(title="⛏️ Minecraft Admin Help", description=help_text, color=Colour.from_rgb(98, 166, 75))
    await ctx.send(embed=embed)

@mine.command(name="status")
@commands.has_permissions(administrator=True)
async def mc_status_command(ctx):
    if not await mc_monitor.connect():
        embed = Embed(
            title="🔴 Minecraft Server Status",
            description=f"RCON Connection Failed.\nLast Error: `{mc_monitor.last_error}`",
            color=Colour.red()
        )
    else:
        players, _ = await mc_monitor.get_players()
        embed = Embed(
            title="🟢 Minecraft Server Status",
            description=f"**Online and Responsive**\n\nPlayers Online: **{len(players)}**",
            color=Colour.green()
        )
    await ctx.send(embed=embed)

@mine.command(name="players")
@commands.has_permissions(administrator=True)
async def mc_players_command(ctx):
    players, raw_response = await mc_monitor.get_players()
    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **Minecraft RCON Error:** Could not retrieve player list. {raw_response}")
        return

    if not players:
        embed = Embed(title="⛏️ Minecraft Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_details = []
    for name in sorted(players):
        stats_key = f"mc:{name}"
        stats = player_stats.get(stats_key, {})

        session_time_str = "N/A"
        if name in mc_join_times:
            session_seconds = (datetime.now() - mc_join_times[name]).total_seconds()
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
        title=f"⛏️ Minecraft Online Players ({len(players)})",
        description="List of currently logged-in players:",
        color=Colour.blue()
    )
    embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_details), inline=False)
    await ctx.send(embed=embed)

@mine.command(name="say")
@commands.has_permissions(administrator=True)
async def mc_say_command(ctx, *, message: str):
    command = f"say [Discord Admin] {message}"
    response = await mc_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **Minecraft Message Failed!** {response}")
    else:
        embed = Embed(
            title="💬 Minecraft Message Sent",
            description=f"Message: *{message}*",
            color=Colour.gold()
        )
        await ctx.send(embed=embed)

@mine.command(name="save")
@commands.has_permissions(administrator=True)
async def mc_save_command(ctx):
    response = await mc_monitor.send_command("save-all")
    if "ERROR:" in response:
        await ctx.send(f"❌ **Minecraft Save Failed!** {response}")
    else:
        await ctx.send("✅ **Minecraft Save Initiated.**")

@mine.command(name="kick")
@commands.has_permissions(administrator=True)
async def mc_kick_command(ctx, *, name: str):
    command = f"kick {name}"
    response = await mc_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **Minecraft Kick Failed!** {response}")
    else:
        await ctx.send(f"👟 Player **{name}** kicked from Minecraft.")

@mine.command(name="ban")
@commands.has_permissions(administrator=True)
async def mc_ban_command(ctx, *, name: str):
    command = f"ban {name}"
    response = await mc_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **Minecraft Ban Failed!** {response}")
    else:
        await ctx.send(f"🔨 Player **{name}** banned from Minecraft.")

# ==============================================================================
# DISCORD COMMANDS (PALWORLD)
# ==============================================================================

@bot.group(name="pal", invoke_without_command=True)
async def pal(ctx):
    """Palworld administration commands."""
    await ctx.send(f"Use `{PREFIX}pal-help` for Palworld commands.")

@pal.command(name="help")
async def pal_help_command(ctx):
    help_text = f"""
    __**Palworld Admin Commands ({PREFIX}pal-)**__
    *All commands require **Administrator** permission in Discord.*

    **!server-pal-status**
    > Shows the current player count and RCON connection health.

    **!server-pal-players**
    > Lists all currently logged-in players (names, playtime, stats) and their **Steam IDs** (required for admin actions).

    **!server-pal-broadcast <message>**
    > Sends a server-wide broadcast message to all players.

    **!server-pal-save**
    > Forces the world to save (`Save`).

    **!server-pal-kick <SteamID> [blacklist: True/False]**
    > **Kicks** a player using their Steam ID.
    > **NEW:** If you set `blacklist` to **True**, the ID will be added to the bot's persistent blacklist, preventing future joins. Example: `!server-pal-kick 12345678901234567 True`
    """
    embed = Embed(title="🐾 Palworld Admin Help", description=help_text, color=Colour.from_rgb(175, 140, 240))
    await ctx.send(embed=embed)

@pal.command(name="status")
@commands.has_permissions(administrator=True)
async def pal_status_command(ctx):
    if not await pal_monitor.connect():
        embed = Embed(
            title="🔴 Palworld Server Status",
            description=f"RCON Connection Failed.\nLast Error: `{pal_monitor.last_error}`",
            color=Colour.red()
        )
    else:
        players, _ = await pal_monitor.get_players()
        embed = Embed(
            title="🟢 Palworld Server Status",
            description=f"**Online and Responsive**\n\nPlayers Online: **{len(players)}**",
            color=Colour.green()
        )
    await ctx.send(embed=embed)

@pal.command(name="players")
@commands.has_permissions(administrator=True)
async def pal_players_command(ctx):
    _, raw_response = await pal_monitor.get_players()
    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **Palworld RCON Error:** Could not retrieve player list. {raw_response}")
        return

    player_details_list = pal_player_details_extractor(raw_response)
    if not player_details_list:
        embed = Embed(title="🐾 Palworld Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_fields = []
    for player in sorted(player_details_list, key=lambda p: p['name']):
        name = player['name']
        steam_id = player.get('steam_id', 'N/A')
        is_blacklisted = " (BLOCKED)" if steam_id in palworld_blacklist else ""
        stats_key = f"pal:{name}"
        stats = player_stats.get(stats_key, {})

        session_time_str = "N/A"
        if name in pal_join_times:
            session_seconds = (datetime.now() - pal_join_times[name]).total_seconds()
            session_time_str = format_duration(session_seconds)
            
        total_time_str = format_duration(stats.get("total_playtime_seconds", 0))
        
        player_fields.append(
            f"**{name}{is_blacklisted}**\n"
            f"• **ID (for Kick/Ban):** `{steam_id}`\n"
            f"• Session: {session_time_str}\n"
            f"• Total Time: {total_time_str}"
        )

    embed = Embed(
        title=f"🐾 Palworld Online Players ({len(player_details_list)})",
        description="List of currently logged-in players. Use the Steam ID for kick/blacklist commands:",
        color=Colour.blue()
    )
    embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_fields), inline=False)
    await ctx.send(embed=embed)

@pal.command(name="broadcast")
@commands.has_permissions(administrator=True)
async def pal_broadcast_command(ctx, *, message: str):
    # Palworld RCON broadcast command: Broadcast <Message>
    command = f"Broadcast {message}"
    response = await pal_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Broadcast Failed!** {response}")
    else:
        await ctx.send(f"📣 **Broadcast Sent:** *{message}*")

@pal.command(name="save")
@commands.has_permissions(administrator=True)
async def pal_save_command(ctx):
    response = await pal_monitor.send_command("Save")
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Save Failed!** {response}")
    else:
        await ctx.send("✅ **Palworld Save Initiated.**")

@pal.command(name="kick")
@commands.has_permissions(administrator=True)
async def pal_kick_command(ctx, steam_id: str, blacklist: bool = False):
    """Kicks a player using their Steam ID and optionally adds them to the persistent blacklist."""
    
    # 1. Handle Blacklist Logic
    if blacklist:
        if steam_id not in palworld_blacklist:
            palworld_blacklist.add(steam_id)
            save_palworld_blacklist()
            await ctx.send(f"🔨 Steam ID **{steam_id}** added to the persistent Palworld blacklist and saved.")
        else:
            await ctx.send(f"⚠️ Steam ID **{steam_id}** was already in the blacklist.")

    # 2. Perform Kick
    # Palworld RCON kick command: KickPlayer <SteamID>
    command = f"KickPlayer {steam_id}"
    response = await pal_monitor.send_command(command)
    
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Kick Failed!** Response: {response}")
    else:
        status_msg = "permanently blacklisted and " if blacklist else ""
        await ctx.send(f"👟 Player with Steam ID **{steam_id}** {status_msg}kicked from Palworld.")


@pal.command(name="unblacklist")
@commands.has_permissions(administrator=True)
async def pal_unblacklist_command(ctx, steam_id: str):
    """Removes a Steam ID from the bot's internal blacklist."""
    if steam_id in palworld_blacklist:
        palworld_blacklist.remove(steam_id)
        save_palworld_blacklist()
        await ctx.send(f"✅ Steam ID **{steam_id}** removed from the Palworld blacklist.")
    else:
        await ctx.send(f"⚠️ Steam ID **{steam_id}** was not found in the Palworld blacklist.")

# ==============================================================================
# DISCORD COMMANDS (ARK: SURVIVAL ASCENDED)
# ==============================================================================

@bot.group(name="asa", invoke_without_command=True)
async def asa(ctx):
    """ASA administration commands."""
    await ctx.send(f"Use `{PREFIX}asa-help` for ASA commands.")

@asa.command(name="help")
async def asa_help_command(ctx):
    help_text = f"""
    __**ASA Admin Commands ({PREFIX}asa-)**__
    *All commands require **Administrator** permission in Discord.*

    **!server-asa-status**
    > Shows the current player count and RCON connection health.

    **!server-asa-players**
    > Lists all currently logged-in players (names, playtime, stats) **and their Steam/Player IDs** (required for kick/ban).

    **!server-asa-save**
    > Forces the world to save (`SaveWorld`).

    **!server-asa-kick <ID>**
    > Kicks a player using their Player ID or Steam ID (found via `!server-asa-players`).

    **!server-asa-ban <ID>**
    > Bans a player using their Player ID or Steam ID.
    """
    embed = Embed(title="🦖 ARK: ASA Admin Help", description=help_text, color=Colour.from_rgb(100, 180, 200))
    await ctx.send(embed=embed)

@asa.command(name="status")
@commands.has_permissions(administrator=True)
async def asa_status_command(ctx):
    if not await asa_monitor.connect():
        embed = Embed(
            title="🔴 ASA Server Status",
            description=f"RCON Connection Failed.\nLast Error: `{asa_monitor.last_error}`",
            color=Colour.red()
        )
    else:
        players, _ = await asa_monitor.get_players()
        embed = Embed(
            title="🟢 ASA Server Status",
            description=f"**Online and Responsive**\n\nPlayers Online: **{len(players)}**",
            color=Colour.green()
        )
    await ctx.send(embed=embed)

@asa.command(name="players")
@commands.has_permissions(administrator=True)
async def asa_players_command(ctx):
    _, raw_response = await asa_monitor.get_players()
    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **ASA RCON Error:** Could not retrieve player list. {raw_response}")
        return

    player_details_list = asa_player_details_extractor(raw_response)
    if not player_details_list:
        embed = Embed(title="🦖 ASA Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_fields = []
    for player in sorted(player_details_list, key=lambda p: p['name']):
        name = player['name']
        player_id = player.get('player_id', 'N/A')
        steam_id = player.get('steam_id', 'N/A')
        stats_key = f"asa:{name}"
        stats = player_stats.get(stats_key, {})

        session_time_str = "N/A"
        if name in asa_join_times:
            session_seconds = (datetime.now() - asa_join_times[name]).total_seconds()
            session_time_str = format_duration(session_seconds)
            
        total_time_str = format_duration(stats.get("total_playtime_seconds", 0))
        
        player_fields.append(
            f"**{name}**\n"
            f"• **ID (for Kick/Ban):** `{player_id}` (or Steam ID: `{steam_id}`)\n"
            f"• Session: {session_time_str}\n"
            f"• Total Time: {total_time_str}"
        )

    embed = Embed(
        title=f"🦖 ASA Online Players ({len(player_details_list)})",
        description="List of currently logged-in players. Use the Player ID (or Steam ID) for kick/ban commands:",
        color=Colour.blue()
    )
    embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_fields), inline=False)
    await ctx.send(embed=embed)


@asa.command(name="save")
@commands.has_permissions(administrator=True)
async def asa_save_command(ctx):
    response = await asa_monitor.send_command("SaveWorld")
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Save Failed!** {response}")
    else:
        await ctx.send("✅ **ASA Save Initiated.**")

@asa.command(name="kick")
@commands.has_permissions(administrator=True)
async def asa_kick_command(ctx, *, identifier: str):
    # ASA RCON kick command: KickPlayer <PlayerName/PlayerID/SteamID>
    command = f"KickPlayer {identifier}"
    response = await asa_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Kick Failed!** Response: {response}")
    else:
        await ctx.send(f"👟 Player **{identifier}** kicked from ASA.")

@asa.command(name="ban")
@commands.has_permissions(administrator=True)
async def asa_ban_command(ctx, *, identifier: str):
    # ASA RCON ban command: BanPlayer <PlayerName/PlayerID/SteamID>
    command = f"BanPlayer {identifier}"
    response = await asa_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Ban Failed!** Response: {response}")
    else:
        await ctx.send(f"🔨 Player **{identifier}** banned from ASA.")


# ==============================================================================
# ERROR HANDLING
# ==============================================================================

@bot.event
async def on_command_error(ctx, error):
    """Global command error handler."""
    if isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors to avoid spamming the channel
        return
    
    if isinstance(error, commands.MissingRequiredArgument) and ctx.command.name == 'kick' and ctx.command.parent.name == 'pal':
        # Specific handler for palworld kick command if argument is missing
        await ctx.send(f"❌ **Missing Argument!** Usage: `!server-pal-kick <SteamID> [blacklist: True/False]`. The SteamID is required.")
        return
    
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"❌ **Permission Denied!** You need **Administrator** permissions to use this command.")
        return

    # Handle generic/unhandled errors
    print(f"Unhandled command error in {ctx.command}: {error}")
    await ctx.send(f"❌ An internal error occurred while running the command: `{error}`")
    
# ==============================================================================
# BOT RUN
# ==============================================================================

if DISCORD_TOKEN != "YOUR_DISCORD_BOT_TOKEN_HERE" and DISCORD_TOKEN:
    # Run the bot
    try:
        # Run the bot with the specified token
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Failed to run the bot. Check your DISCORD_TOKEN and permissions. Error: {e}")
else:
    print("FATAL: DISCORD_TOKEN is missing or set to the default placeholder. Please configure it.")
