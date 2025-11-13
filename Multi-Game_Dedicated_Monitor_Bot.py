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
PALWORLD_BLACKLIST_FILE = "palworld_blacklist.txt" # NEW: Blacklist file name

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
# Dictionary to hold active RCON connections (currently not used, RconManager handles connections)
rcon_clients = {}
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

# NEW: Global set for blacklisted Palworld Steam IDs
palworld_blacklist = set() 


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
            except Exception as e:
                print(f"Error loading stats: {e}. Starting fresh.")
                player_stats = {}
    else:
        player_stats = {}

def save_stats():
    """Saves player statistics to a JSON file."""
    # Note: Use temporary file to ensure atomic write on save
    temp_file = STATISTICS_FILE + ".tmp"
    try:
        with open(temp_file, 'w') as f:
            json.dump(player_stats, f, indent=4)
        os.replace(temp_file, STATISTICS_FILE)
    except Exception as e:
        print(f"Error saving stats: {e}")

# NEW: Blacklist loading function
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
            print(f"Palworld blacklist reloaded with {len(palworld_blacklist)} IDs.")
    except Exception as e:
        print(f"Error loading Palworld blacklist: {e}")
        palworld_blacklist = set()


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
        # Check if client exists and is still connected (RconAsync doesn't have a reliable 'is_connected' state)
        # We rely on exceptions on command send, but try a new connection here if status is False.
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
            # Check connection health by sending a simple command first if possible, or just send the main command
            response = await self.client.send(command)
            return response.strip()
        except RCONException as e:
            # Connection dropped during command execution
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
    """Parses Palworld's ShowPlayers RCON output (Name,UID,SteamID)."""
    players = set()
    lines = response.split('\n')[1:] # Skip header
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 1:
            name = parts[0].strip()
            if name and name != "Name": # Ensure we skip the header if it reappears
                players.add(name)
    return players

# --- Minecraft specific logic ---
def mc_player_extractor(response: str) -> set:
    """Parses Minecraft's list RCON output."""
    players = set()
    # Example: "There are 1 of a max of 20 players online: PlayerName"
    if ':' in response:
        # Split on the first colon and then comma for names
        player_list_str = response.split(':', 1)[1].strip()
        player_names = [name.strip() for name in player_list_str.split(',') if name.strip()]
        players.update(player_names)
    return players

# --- ASA specific logic ---
def asa_player_extractor(response: str) -> set:
    """Parses ARK: Survival Ascended's ListPlayers RCON output (Name: PlayerName\nID: 123...\n)."""
    players = set()
    # Matches the Name: ... followed by a newline or end of string
    matches = re.findall(r'Name: (.+?)(?:\r?\n|$)', response, re.DOTALL)
    for match in matches:
        name = match.strip()
        # ARK list players sometimes includes 'ID: 123...' lines, ensure we only capture names
        if name and not name.startswith("ID:"):
            players.add(name)
    return players
    
# --- Generic SRCDS (Source Engine) logic ---
def srcds_player_extractor(response: str) -> set:
    """Parses Source Engine's 'status' RCON output (CS:GO, TF2, GMod)."""
    players = set()
    # SRCDS 'status' lines look like: # 1 	"PlayerName" STEAM_X:X:XXXXX 00:00 0 	400 	0
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
    load_palworld_blacklist() # NEW: Initial blacklist load
    
    # Set channels for RCON managers
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    mc_monitor.channel = channel
    pal_monitor.channel = channel
    asa_monitor.channel = channel
    srcds_monitor.channel = channel

    if not channel and TARGET_CHANNEL_ID != 0: # Only warn if ID is set but not found
        print(f"ERROR: Target Channel ID {TARGET_CHANNEL_ID} not found. Monitoring tasks will not start.")
        return

    # Start background tasks
    if not player_monitor_task.running:
        player_monitor_task.start()
        print("Player monitoring task started.")
    if not scheduled_actions_task.running:
        scheduled_actions_task.start()
        print("Scheduled actions task started.")
    if not palworld_blacklist_reloader.running: # NEW: Start blacklist reloader
        palworld_blacklist_reloader.start()
        print("Palworld blacklist reloader started.")


@tasks.loop(minutes=5) # NEW: Task to reload the blacklist periodically
async def palworld_blacklist_reloader():
    """Reloads the Palworld blacklist periodically."""
    load_palworld_blacklist()
    if bot.is_ready():
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
             await log_channel.send(f"✅ **Palworld Blacklist:** Reloaded {len(palworld_blacklist)} IDs.")


@tasks.loop(seconds=RCON_CHECK_INTERVAL_SECONDS)
async def player_monitor_task():
    """Background task to continuously check players and report joins/leaves for all servers."""
    global current_mc_players, current_pal_players, current_asa_players, current_srcds_players

    async def check_server(monitor: RconManager, game_code: str, current_set: set) -> set:
        """Helper function to perform checks for one server."""
        # Ensure the channel is available before proceeding
        if not monitor.channel:
            return current_set

        try:
            new_players, raw_response = await monitor.get_players()
        except Exception as e:
            if current_set:
                # If we lose connection while players are online, notify once.
                await monitor.channel.send(f"⚠️ **{monitor.game_name} Alert:** Lost RCON connectivity ({e}). Status monitoring paused.")
            return set()

        if raw_response.startswith("ERROR:"):
            # Check for generic connection/auth errors
            if current_set:
                 # If we lose connection while players are online, notify once.
                await monitor.channel.send(f"⚠️ **{monitor.game_name} Alert:** Lost RCON connectivity or command failed. Status monitoring paused.")
            
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                # Send the specific RCON error to the log channel
                await log_channel.send(f"⚠️ **{monitor.game_name} RCON Error:** {raw_response}")
            return set() # Treat as no players or unknown state

        # --- NEW: PALWORLD BLACKLIST CHECK (Runs before join/leave logic) ---
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
                             # Send log message about the action
                             await log_channel.send(f"🚨 **Blacklist Auto-Kick (Palworld):** Player **{name}** (`{steam_id}`) was kicked. Response: `{kick_response[:50]}...`")
                        
                        # Remove kicked player from the 'new_players' set so they don't trigger join/leave notifications
                        new_players.discard(name)

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
        # Palworld Save command often returns "Save Successful" or similar, but checking for ERROR is enough.
        await channel.send("✅ **[Palworld Auto-Save]** World state successfully saved.")
    else:
        await channel.send(f"❌ **[Palworld Auto-Save Failed]** {pal_response}")
        
    # --- ASA Auto-Save ---
    asa_response = await asa_monitor.send_command("SaveWorld")
    if "ERROR:" not in asa_response:
        # ASA SaveWorld often returns an empty string, so checking for error is sufficient.
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
    # Handle the case where the list is too long for a single field
    if len("\n\n".join(player_details)) > 1024:
        # Truncate or use pagination if necessary, but for simplicity here, just the count.
        embed.add_field(name="Player Stats (Session/Total)", value=f"Too many players to list. {len(players)} online.", inline=False)
    else:
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
    if len("\n\n".join(player_details)) > 1024:
        embed.add_field(name="Player Stats (Session/Total)", value=f"Too many players to list. {len(players)} online.", inline=False)
    else:
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
    > Lists all currently logged-in players (names, playtime, stats).

    **!server-pal-broadcast <message>**
    > Sends a server-wide broadcast message to all players.

    **!server-pal-save**
    > Forces the world to save (`Save`).

    **!server-pal-kick <SteamID>**
    > Kicks a player using their Steam ID (required for Palworld).

    **!server-pal-shutdown <seconds> [message]**
    > Shuts down the server after a delay with an optional message.
    """
    embed = Embed(title="🐾 Palworld Admin Help", description=help_text, color=Colour.from_rgb(255, 165, 0))
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
    players, raw_response = await pal_monitor.get_players()
    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **Palworld RCON Error:** Could not retrieve player list. {raw_response}")
        return

    if not players:
        embed = Embed(title="🐾 Palworld Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_details = []
    # Note: Palworld list is Name, UID, SteamID
    lines = raw_response.split('\n')[1:]
    
    # Map SteamID to Name for easier lookup in the current session set
    player_map = {} 
    
    for line in lines:
        parts = [p.strip() for p in line.split(',', 2)]
        if len(parts) == 3 and parts[0] != "Name":
            name, _, steam_id = parts
            player_map[name] = steam_id

            stats_key = f"pal:{name}"
            stats = player_stats.get(stats_key, {})

            session_time_str = "N/A"
            if name in pal_join_times:
                session_seconds = (datetime.now() - pal_join_times[name]).total_seconds()
                session_time_str = format_duration(session_seconds)
                
            total_time_str = format_duration(stats.get("total_playtime_seconds", 0))
            first_join = stats.get("first_join", "Unknown")
            
            # Check if blacklisted
            blacklist_status = "⚠️ BLACKLISTED" if steam_id in palworld_blacklist else "✅ OK"
            
            player_details.append(
                f"**{name}** (`{steam_id}`)\n"
                f"• Session: {session_time_str}\n"
                f"• Total Time: {total_time_str}\n"
                f"• Status: {blacklist_status}\n"
                f"• First Join: {first_join}"
            )

    embed = Embed(
        title=f"🐾 Palworld Online Players ({len(players)})",
        description="List of currently logged-in players (IDs are needed for kicking):",
        color=Colour.blue()
    )
    if len("\n\n".join(player_details)) > 1024:
        embed.add_field(name="Player Stats (Session/Total)", value=f"Too many players to list. {len(players)} online.", inline=False)
    else:
        embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_details), inline=False)
    await ctx.send(embed=embed)

@pal.command(name="broadcast")
@commands.has_permissions(administrator=True)
async def pal_broadcast_command(ctx, *, message: str):
    """Sends a server-wide broadcast message in Palworld."""
    # Palworld RCON needs the message to be enclosed in quotes
    command = f"Broadcast [Discord Admin] {message}"
    response = await pal_monitor.send_command(command)
    
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Broadcast Failed!** {response}")
    else:
        embed = Embed(
            title="📣 Palworld Broadcast Sent",
            description=f"Message: *{message}*",
            color=Colour.gold()
        )
        await ctx.send(embed=embed)

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
async def pal_kick_command(ctx, *, steam_id: str):
    """Kicks a Palworld player using their Steam ID."""
    # Palworld kick command requires SteamID
    command = f"KickPlayer {steam_id}" 
    response = await pal_monitor.send_command(command)
    
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Kick Failed!** Ensure the ID (`{steam_id}`) is correct and the player is online. Response: {response}")
    else:
        embed = Embed(
            title="👟 Palworld Player Kicked",
            description=f"Steam ID **{steam_id}** has been kicked from the server.",
            color=Colour.orange()
        )
        await ctx.send(embed=embed)

@pal.command(name="shutdown")
@commands.has_permissions(administrator=True)
async def pal_shutdown_command(ctx, seconds: int, *, message: str = "Server is shutting down for maintenance. Please check Discord for updates."):
    """Shuts down the Palworld server after a delay."""
    # Palworld shutdown command format: Shutdown <seconds> <message>
    command = f"Shutdown {seconds} {message}"
    response = await pal_monitor.send_command(command)
    
    if "ERROR:" in response:
        await ctx.send(f"❌ **Palworld Shutdown Failed!** {response}")
    else:
        embed = Embed(
            title="🛑 Palworld Server Shutdown Initiated",
            description=f"Server will shut down in **{seconds} seconds**.\nBroadcast message: *{message}*",
            color=Colour.red()
        )
        await ctx.send(embed=embed)


# ==============================================================================
# DISCORD COMMANDS (ARK: SURVIVAL ASCENDED)
# ==============================================================================

@bot.group(name="asa", invoke_without_command=True)
async def asa(ctx):
    """ARK: Survival Ascended administration commands."""
    await ctx.send(f"Use `{PREFIX}asa-help` for ASA commands.")

@asa.command(name="help")
async def asa_help_command(ctx):
    help_text = f"""
    __**ARK: SA Admin Commands ({PREFIX}asa-)**__
    *All commands require **Administrator** permission in Discord.*

    **!server-asa-status**
    > Shows the current player count and RCON connection health.

    **!server-asa-players**
    > Lists all currently logged-in players (names, playtime, stats).

    **!server-asa-say <message>**
    > Sends a message to the in-game chat, prefixed by `[Discord Admin]`.

    **!server-asa-save**
    > Forces the world to save (`SaveWorld`).

    **!server-asa-kick <Name>**
    > Kicks a player using their exact in-game Name.

    **!server-asa-ban <Name>**
    > Bans a player using their exact in-game Name.
    """
    embed = Embed(title="🦕 ASA Admin Help", description=help_text, color=Colour.from_rgb(138, 43, 226))
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
    players, raw_response = await asa_monitor.get_players()
    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **ASA RCON Error:** Could not retrieve player list. {raw_response}")
        return

    if not players:
        embed = Embed(title="🦕 ASA Online Players (0)", description="The server is currently empty.", color=Colour.orange())
        await ctx.send(embed=embed)
        return

    player_details = []
    for name in sorted(players):
        stats_key = f"asa:{name}"
        stats = player_stats.get(stats_key, {})

        session_time_str = "N/A"
        if name in asa_join_times:
            session_seconds = (datetime.now() - asa_join_times[name]).total_seconds()
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
        title=f"🦕 ASA Online Players ({len(players)})",
        description="List of currently logged-in players:",
        color=Colour.blue()
    )
    if len("\n\n".join(player_details)) > 1024:
        embed.add_field(name="Player Stats (Session/Total)", value=f"Too many players to list. {len(players)} online.", inline=False)
    else:
        embed.add_field(name="Player Stats (Session/Total)", value="\n\n".join(player_details), inline=False)
    await ctx.send(embed=embed)

@asa.command(name="say")
@commands.has_permissions(administrator=True)
async def asa_say_command(ctx, *, message: str):
    """Sends a message to the in-game chat for ASA."""
    # ARK uses 'ServerChat <message>' for server broadcast
    command = f"ServerChat [Discord Admin] {message}"
    response = await asa_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Message Failed!** {response}")
    else:
        embed = Embed(
            title="💬 ASA Message Sent",
            description=f"Message: *{message}*",
            color=Colour.gold()
        )
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
async def asa_kick_command(ctx, *, name: str):
    """Kicks an ASA player using their name."""
    # ARK uses 'KickPlayer <name>'
    command = f"KickPlayer {name}"
    response = await asa_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Kick Failed!** {response}")
    else:
        await ctx.send(f"👟 Player **{name}** kicked from ASA.")

@asa.command(name="ban")
@commands.has_permissions(administrator=True)
async def asa_ban_command(ctx, *, name: str):
    """Bans an ASA player using their name."""
    # ARK uses 'BanPlayer <name>'
    command = f"BanPlayer {name}"
    response = await asa_monitor.send_command(command)
    if "ERROR:" in response:
        await ctx.send(f"❌ **ASA Ban Failed!** {response}")
    else:
        await ctx.send(f"🔨 Player **{name}** banned from ASA.")


# ==============================================================================
# DISCORD COMMANDS (GENERAL STATS)
# ==============================================================================

@bot.group(name="stats", invoke_without_command=True)
async def stats(ctx):
    """General player statistics commands across all servers."""
    await ctx.send(f"Use `{PREFIX}stats-help` for player statistics commands.")

@stats.command(name="help")
async def stats_help_command(ctx):
    help_text = f"""
    __**Player Stats Commands ({PREFIX}stats-)**__
    *These commands show global player data recorded by the bot.*

    **!server-stats-top**
    > Lists the top 10 players by recorded total playtime across all monitored servers.

    **!server-stats-info <game> <player_name>**
    > Displays detailed statistics for a specific player on a specific game.
    > Example: `!server-stats-info mc Steve`
    > *Supported games: `mc`, `pal`, `asa`, `srcds`*
    """
    embed = Embed(title="📊 Player Stats Help", description=help_text, color=Colour.from_rgb(255, 204, 0))
    await ctx.send(embed=embed)

@stats.command(name="top")
async def top_playtime_command(ctx):
    """Displays the top 10 players by total playtime."""
    
    # Process all stats to aggregate by player/game key
    sorted_stats = sorted(
        player_stats.items(), 
        key=lambda item: item[1].get("total_playtime_seconds", 0), 
        reverse=True
    )
    
    # Get top 10
    top_players = sorted_stats[:10]
    
    if not top_players:
        await ctx.send("No player statistics have been recorded yet.")
        return
        
    rankings = []
    for rank, (player_key, stats) in enumerate(top_players, 1):
        game_code, player_name = player_key.split(':', 1)
        total_time = format_duration(stats.get("total_playtime_seconds", 0))
        
        game_name_map = {'mc': 'Minecraft ⛏️', 'pal': 'Palworld 🐾', 'asa': 'ASA 🦕', 'srcds': 'SRCDS ⚙️'}
        game_display = game_name_map.get(game_code, game_code)
        
        rankings.append(f"**#{rank}** ({game_display}): **{player_name}** ({total_time})")

    embed = Embed(
        title="🏆 Top 10 Player Playtime (All Servers)",
        description="\n".join(rankings),
        color=Colour.gold()
    )
    await ctx.send(embed=embed)

@stats.command(name="info")
async def player_info_command(ctx, game_code: str, *, player_name: str):
    """Displays detailed stats for a specific player."""
    game_code = game_code.lower()
    player_key = f"{game_code}:{player_name}"
    
    game_name_map = {'mc': 'Minecraft', 'pal': 'Palworld', 'asa': 'ASA', 'srcds': 'SRCDS'}
    game_display = game_name_map.get(game_code, f"Unknown Game ({game_code})")
    
    if player_key not in player_stats:
        await ctx.send(f"❌ **Stats Not Found:** No recorded statistics for player **{player_name}** on **{game_display}**.")
        return

    stats = player_stats[player_key]
    
    total_time = format_duration(stats.get("total_playtime_seconds", 0))
    first_join = stats.get("first_join", "N/A")
    
    embed = Embed(
        title=f"Detailed Stats for {player_name}",
        description=f"**Game:** {game_display}",
        color=Colour.blue()
    )
    embed.add_field(name="Total Playtime", value=total_time, inline=False)
    embed.add_field(name="First Join Date", value=first_join, inline=False)
    
    await ctx.send(embed=embed)


# General error handler for the bot
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Ignore commands not starting with our prefix
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 **Permission Denied:** You need Administrator permissions to run this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ **Missing Argument:** Please provide all necessary arguments. Use `{PREFIX}help` or the game-specific help command for syntax.")
    elif isinstance(error, commands.BadArgument):
         await ctx.send(f"⚠️ **Bad Argument:** One or more arguments are the wrong type (e.g., expected a number, got text).")
    else:
        print(f"An unexpected error occurred: {error}")
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"💣 **Unhandled Bot Error in {ctx.command}:** ```{error}```")
        # await ctx.send(f"An unexpected error occurred. Check the log channel for details.")


def run_bot():
    """Starts the bot with the Discord token."""
    try:
        if DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE" or not DISCORD_TOKEN:
            print("ERROR: DISCORD_TOKEN is not set. Please update the configuration block or environment variable.")
            return
        if TARGET_CHANNEL_ID == 0:
            print("WARNING: TARGET_CHANNEL_ID is 0. Please update this to a valid channel ID for monitoring notifications.")
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Fatal error running the bot: {e}")

if __name__ == "__main__":
    run_bot()
