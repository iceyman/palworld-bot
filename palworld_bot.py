# -*- coding: utf-8 -*-
import os
import asyncio
import re
from discord.ext import commands
from discord import Intents, Status, Game, Embed, Colour
from rcon.asyncio import RconAsync, RCONException

# ==============================================================================
# ⚠️ CONFIGURATION BLOCK ⚠️
# Set your bot and RCON credentials here for easy setup.
# ==============================================================================

# --- DISCORD CONFIGURATION ---
# 1. Your Discord Bot Token (REQUIRED)
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
# 2. The Channel ID where the bot should post status updates (REQUIRED)
TARGET_CHANNEL_ID = 0  # Example: 123456789012345678

# --- RCON CONFIGURATION (MUST MATCH YOUR PALWORLD SERVER SETTINGS) ---
# 3. Server IP/Hostname (REQUIRED)
RCON_HOST = "127.0.0.1"
# 4. Server RCON Port (Default Palworld RCON port is 25575)
RCON_PORT = 25575
# 5. Server RCON Password (REQUIRED)
RCON_PASSWORD = "YOUR_RCON_PASSWORD_HERE"

# --- GAME CONSTANTS ---
GAME_NAME = "Palworld"
PREFIX = "!pal-"
RCON_CHECK_INTERVAL_SECONDS = 30

# Fallback to environment variables if placeholders are not updated
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', DISCORD_TOKEN)
TARGET_CHANNEL_ID = int(os.getenv('TARGET_CHANNEL_ID', TARGET_CHANNEL_ID))
RCON_HOST = os.getenv('RCON_HOST', RCON_HOST)
RCON_PORT = int(os.getenv('RCON_PORT', RCON_PORT))
RCON_PASSWORD = os.getenv('RCON_PASSWORD', RCON_PASSWORD)

# ==============================================================================
# BOT INITIALIZATION
# ==============================================================================
intents = Intents.default()
intents.message_content = True  # Required for command processing
intents.members = True # Required to check for Admin role/permissions

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Global state variables
current_players = set()
rcon_client = None

# ==============================================================================
# RCON HELPER FUNCTIONS
# ==============================================================================

async def _connect_rcon():
    """Establishes an asynchronous RCON connection."""
    global rcon_client
    if rcon_client and rcon_client.is_connected:
        return True

    try:
        rcon_client = RconAsync(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        await rcon_client.connect()
        return True
    except (RCONException, asyncio.TimeoutError, ConnectionRefusedError) as e:
        print(f"RCON Connection Error: {e}")
        return False

async def _send_rcon_command(command: str) -> str:
    """Sends a command over RCON and returns the response string."""
    if not await _connect_rcon():
        return f"ERROR: Failed to connect to RCON at {RCON_HOST}:{RCON_PORT}."

    try:
        response = await rcon_client.send(command)
        # Palworld RCON often returns status information before the actual command result
        if response.strip().startswith("Current player"):
            return "\n".join(response.strip().split('\n')[1:])
        return response.strip()
    except RCONException as e:
        print(f"RCON Command Error for '{command}': {e}")
        return f"ERROR: RCON Command failed ({e})."
    except asyncio.TimeoutError:
        return "ERROR: RCON command timed out."
    except Exception as e:
        return f"ERROR: An unexpected error occurred during RCON communication: {e}"

async def _get_current_players() -> set:
    """Gets the list of currently logged-in players."""
    response = await _send_rcon_command("ShowPlayers")
    players = set()
    # Palworld response format for ShowPlayers is: "name,playeruid,steamid" per line
    # We use a non-greedy regex to capture the player name which can contain spaces/special characters
    # e.g., "Player Name,12345678,98765432101234567"
    for line in response.split('\n'):
        match = re.search(r"^([^,]+),", line)
        if match:
            player_name = match.group(1).strip()
            if player_name and player_name != "name": # Skip header line
                players.add(player_name)
    return players, response

# ==============================================================================
# CORE BOT LOOP (TASK)
# ==============================================================================

@bot.event
async def on_ready():
    """Executed when the bot is connected to Discord."""
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    await bot.change_presence(activity=Game(f"Monitoring {GAME_NAME} | {PREFIX}help"))

    # Ensure the target channel exists before starting the monitoring loop
    try:
        target_channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not target_channel:
            print(f"ERROR: Channel ID {TARGET_CHANNEL_ID} not found. Please check configuration.")
            return

        # Start the background monitoring task
        if not player_monitor_task.running:
            player_monitor_task.start()
            print("Player monitoring task started.")

    except Exception as e:
        print(f"Initialization failed: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for commands."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"❌ You need the **Administrator** permission to use the `{ctx.command.name}` command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: {error}. Usage: `{PREFIX}{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors to avoid spam
        return
    else:
        print(f"Unhandled command error in {ctx.command}: {error}")
        await ctx.send("❌ An unexpected error occurred while executing the command.")


@bot.loop(seconds=RCON_CHECK_INTERVAL_SECONDS)
async def player_monitor_task():
    """Background task to continuously check players and report joins/leaves."""
    global current_players
    target_channel = bot.get_channel(TARGET_CHANNEL_ID)

    if not target_channel:
        # If channel is still not found, stop the loop.
        print(f"Monitor loop paused: Target channel ID {TARGET_CHANNEL_ID} is invalid.")
        return

    try:
        new_players, _ = await _get_current_players()
    except Exception as e:
        # Send a single error message to Discord if RCON fails repeatedly
        if not current_players: # Only report connectivity loss if we had players before
             await target_channel.send(f"⚠️ **RCON/Connectivity Alert:** Could not reach the {GAME_NAME} server. Status monitoring paused.")
        current_players = set() # Reset state
        return

    # Check for Joins
    joined_players = new_players - current_players
    for player in joined_players:
        embed = Embed(
            title=f"🟢 Player Joined",
            description=f"**{player}** has joined the server.",
            color=Colour.green()
        )
        await target_channel.send(embed=embed)

    # Check for Leaves
    left_players = current_players - new_players
    for player in left_players:
        embed = Embed(
            title=f"🔴 Player Left",
            description=f"**{player}** has left the server.",
            color=Colour.red()
        )
        await target_channel.send(embed=embed)

    # Update state for the next check
    current_players = new_players

# ==============================================================================
# DISCORD COMMANDS
# ==============================================================================

@bot.command(name="help")
async def help_command(ctx):
    """Displays a list of all administrative commands."""
    help_text = f"""
    __**{GAME_NAME} Admin Commands ({PREFIX})**__
    *All commands require **Administrator** permission in Discord.*

    **!pal-status**
    > Shows the current player count and RCON connection health.

    **!pal-players**
    > Lists all currently logged-in players and their required **Steam ID**.
    > *Use the Steam ID for kick/ban commands.*

    **!pal-broadcast <message>**
    > Sends a global announcement to all players in-game.
    > Example: `!pal-broadcast Server restarting in 5 minutes!`

    **!pal-save**
    > Forces the server to immediately save the world state.

    **!pal-shutdown**
    > Forces the server to shut down (use before stopping the hosting machine).

    **!pal-kick <SteamID>**
    > Kicks a player using their Steam ID (obtained via `!pal-players`).

    **!pal-ban <SteamID>**
    > Bans a player using their Steam ID (obtained via `!pal-players`).
    """

    embed = Embed(
        title=f"{GAME_NAME} Admin Help",
        description=help_text,
        color=Colour.blue()
    )
    await ctx.send(embed=embed)


@bot.command(name="status")
@commands.has_permissions(administrator=True)
async def status_command(ctx):
    """Checks the current server status and player count."""
    if not await _connect_rcon():
        embed = Embed(
            title=f"🔴 {GAME_NAME} Server Status",
            description=f"RCON Connection Failed to {RCON_HOST}:{RCON_PORT}.",
            color=Colour.red()
        )
    else:
        # Get players to confirm status
        players, _ = await _get_current_players()
        status_msg = "Online and Responsive"
        status_color = Colour.green()

        embed = Embed(
            title=f"🟢 {GAME_NAME} Server Status",
            description=f"**{status_msg}**\n\nPlayers Online: **{len(players)}**",
            color=status_color
        )
        embed.add_field(name="RCON Endpoint", value=f"`{RCON_HOST}:{RCON_PORT}`", inline=False)

    await ctx.send(embed=embed)


@bot.command(name="players")
@commands.has_permissions(administrator=True)
async def players_command(ctx):
    """Lists all players and their SteamIDs."""
    players, raw_response = await _get_current_players()

    if "ERROR:" in raw_response:
        await ctx.send(f"❌ **RCON Error:** Could not retrieve player list. {raw_response}")
        return

    if not players:
        embed = Embed(
            title=f"🎮 Online Players ({len(players)})",
            description="The server is currently empty.",
            color=Colour.orange()
        )
        await ctx.send(embed=embed)
        return

    # Process raw response to display names and IDs
    player_list = []
    # Palworld response columns: Name, PlayerUID, SteamID
    for line in raw_response.split('\n'):
        parts = [p.strip() for p in line.split(',', 2)]
        if len(parts) == 3 and parts[0] != "name": # Skip header line
            name, _, steam_id = parts
            player_list.append(f"**{name}** (`{steam_id}`)")

    player_list_str = "\n".join(player_list)
    embed = Embed(
        title=f"🎮 Online Players ({len(players)})",
        description="List of currently logged-in players and their Steam IDs (for kick/ban):",
        color=Colour.blue()
    )
    embed.add_field(name="Name (Steam ID)", value=player_list_str, inline=False)
    await ctx.send(embed=embed)


@bot.command(name="broadcast")
@commands.has_permissions(administrator=True)
async def broadcast_command(ctx, *, message: str):
    """Sends a global message to all players in-game."""
    # Palworld RCON command for broadcasting is 'Broadcast'
    command = f"Broadcast {message}"
    response = await _send_rcon_command(command)

    if "ERROR:" in response:
        await ctx.send(f"❌ **Broadcast Failed!** {response}")
    else:
        embed = Embed(
            title="📣 Broadcast Sent",
            description=f"Message: *{message}*",
            color=Colour.gold()
        )
        await ctx.send(embed=embed)


@bot.command(name="save")
@commands.has_permissions(administrator=True)
async def save_command(ctx):
    """Forces the server to save the world state."""
    command = "Save"
    response = await _send_rcon_command(command)

    if "ERROR:" in response:
        await ctx.send(f"❌ **Save Failed!** {response}")
    else:
        embed = Embed(
            title="💾 World Saved",
            description="The server was commanded to save the world state.",
            color=Colour.green()
        )
        await ctx.send(embed=embed)


@bot.command(name="shutdown")
@commands.has_permissions(administrator=True)
async def shutdown_command(ctx, delay: int = 10, *, reason: str = "Administrator request"):
    """Shuts down the server after a delay with a given reason."""
    # The command accepts a delay (in seconds) and a message (the reason)
    command = f"Shutdown {delay} {reason}"
    response = await _send_rcon_command(command)

    if "ERROR:" in response:
        await ctx.send(f"❌ **Shutdown Failed!** {response}")
    else:
        embed = Embed(
            title="🛑 Server Shutdown Initiated",
            description=f"Server will shut down in **{delay} seconds**.\nReason: *{reason}*",
            color=Colour.red()
        )
        await ctx.send(embed=embed)


@bot.command(name="kick")
@commands.has_permissions(administrator=True)
async def kick_command(ctx, steam_id: str):
    """Kicks a player using their Steam ID."""
    command = f"KickPlayer {steam_id}"
    response = await _send_rcon_command(command)

    if "ERROR:" in response or "Failed" in response:
        await ctx.send(f"❌ **Kick Failed!** Make sure the Steam ID (`{steam_id}`) is correct and the player is online. Response: {response}")
    else:
        embed = Embed(
            title="👟 Player Kicked",
            description=f"Steam ID: `{steam_id}` has been kicked from the server.",
            color=Colour.orange()
        )
        await ctx.send(embed=embed)


@bot.command(name="ban")
@commands.has_permissions(administrator=True)
async def ban_command(ctx, steam_id: str):
    """Bans a player using their Steam ID."""
    command = f"BanPlayer {steam_id}"
    response = await _send_rcon_command(command)

    if "ERROR:" in response or "Failed" in response:
        await ctx.send(f"❌ **Ban Failed!** Make sure the Steam ID (`{steam_id}`) is correct and the player is online. Response: {response}")
    else:
        embed = Embed(
            title="🔨 Player Banned",
            description=f"Steam ID: `{steam_id}` has been **banned** from the server.",
            color=Colour.dark_red()
        )
        await ctx.send(embed=embed)

# ==============================================================================
# RUN BOT
# ==============================================================================

# Ensure all critical configuration is set before running
if not DISCORD_TOKEN or TARGET_CHANNEL_ID == 0 or not RCON_PASSWORD:
    print("\n\n--------------------------------------------------------------")
    print("FATAL ERROR: Please update the CONFIGURATION BLOCK in the script.")
    print("--------------------------------------------------------------\n")
else:
    try:
        # Run the bot with the specified token
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"\n\nFATAL RUNTIME ERROR: {e}")
        print("Check if your DISCORD_TOKEN is valid and that you have installed discord.py.")
