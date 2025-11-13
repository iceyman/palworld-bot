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
ADMIN_CHANNEL_ID = int(os.getenv('ADMIN_CHANNEL_ID', 0)) # Channel where RCON commands are allowed
MC_CHANNEL_ID = int(os.getenv('MC_CHANNEL_ID', 0)) # Channel for Minecraft status
PAL_CHANNEL_ID = int(os.getenv('PAL_CHANNEL_ID', 0)) # Channel for Palworld status and auto-save logs
ASA_CHANNEL_ID = int(os.getenv('ASA_CHANNEL_ID', 0)) # Channel for ARK: ASA status and auto-save logs

# --- MINECRAFT RCON CONFIGURATION ---
MC_RCON_HOST = os.getenv('MC_RCON_HOST', "127.0.0.1")
MC_RCON_PORT = int(os.getenv('MC_RCON_PORT', 25575))
MC_RCON_PASSWORD = os.getenv('MC_RCON_PASSWORD', "YOUR_MC_RCON_PASSWORD_HERE")

# --- PALWORLD RCON CONFIGURATION ---
PAL_RCON_HOST = os.getenv('PAL_RCON_HOST', "127.0.0.1")
PAL_RCON_PORT = int(os.getenv('PAL_RCON_PORT', 25576))
PAL_RCON_PASSWORD = os.getenv('PAL_RCON_PASSWORD', "YOUR_PAL_RCON_PASSWORD_HERE")
PAL_SAVE_INTERVAL = int(os.getenv('PAL_SAVE_INTERVAL', 30)) # Auto-save interval in minutes

# --- ASA RCON CONFIGURATION ---
ASA_RCON_HOST = os.getenv('ASA_RCON_HOST', "127.0.0.1")
ASA_RCON_PORT = int(os.getenv('ASA_RCON_PORT', 27020))
ASA_RCON_PASSWORD = os.getenv('ASA_RCON_PASSWORD', "YOUR_ASA_RCON_PASSWORD_HERE")
ASA_SAVE_INTERVAL = int(os.getenv('ASA_SAVE_INTERVAL', 60)) # Auto-save interval in minutes

# --- PERSISTENT DATA ---
PAL_BAN_LIST_FILE = "palworld_ban_list.json"
ASA_PLAYER_LIST = {} # Caches ASA player list (ASA RCON doesn't provide IDs easily)

# ==============================================================================
# BOT INITIALIZATION
# ==============================================================================

# Use minimal intents for performance and required functionality
intents = Intents.default()
intents.message_content = True  # Required to read commands
bot = commands.Bot(command_prefix='!', intents=intents)

# ==============================================================================
# UTILITY FUNCTIONS (Server Status Check)
# ==============================================================================

async def get_server_status(host, port, password, game_name, status_command):
    """Checks server status and player count via RCON."""
    try:
        # Use a timeout to prevent the bot from locking up on unresponsive servers
        async with RconAsync(host, port, password, timeout=5) as rcon:
            response = await rcon.send(status_command)

            # Common processing logic for Minecraft, Palworld, ASA (ASA is tricky)
            player_count = 0
            max_players = '??'

            if game_name == "Minecraft":
                # Minecraft RCON 'list' command output is typically: "There are X of Y max players online: Player1, Player2"
                # This requires parsing or using a more robust query library (which we're avoiding for simplicity)
                # For basic RCON list, we count names
                if ':' in response:
                    player_names = response.split(':')[-1].strip()
                    if player_names:
                        player_count = len(player_names.split(', '))
                    
            elif game_name == "Palworld":
                # Palworld 'ShowPlayers' returns a list of Name, SteamID, PlayerUID
                lines = response.split('\n')[1:] # Skip header
                player_count = len([line for line in lines if line.strip()])
                max_players = '32' # Palworld standard max, usually

            elif game_name == "ASA":
                # ASA 'ListPlayers' is complex. It just lists names/IDs
                lines = response.split('\n')
                player_count = len([line for line in lines if line.strip() and re.match(r'^\d+\.', line.strip())])
                max_players = '70' # ASA standard max, usually

            status_embed = Embed(title=f"🟢 {game_name} Server Status", color=Colour.green())
            status_embed.add_field(name="Status", value="Online", inline=True)
            status_embed.add_field(name="Players", value=f"{player_count} / {max_players}", inline=True)
            status_embed.set_footer(text=f"Host: {host}:{port}")
            return status_embed

    except RCONException as e:
        status_embed = Embed(title=f"🔴 {game_name} Server Status", color=Colour.red())
        status_embed.add_field(name="Status", value=f"Offline or RCON Error ({e.__class__.__name__})", inline=False)
        status_embed.set_footer(text=f"Host: {host}:{port}")
        return status_embed
    except asyncio.TimeoutError:
        status_embed = Embed(title=f"🟡 {game_name} Server Status", color=Colour.gold())
        status_embed.add_field(name="Status", value="Timed Out (Check Port/Password)", inline=False)
        status_embed.set_footer(text=f"Host: {host}:{port}")
        return status_embed
    except Exception as e:
        print(f"[{game_name}] Unhandled RCON Error: {e}")
        status_embed = Embed(title=f"❓ {game_name} Server Status", color=Colour.light_grey())
        status_embed.add_field(name="Status", value=f"Unknown Error: {e.__class__.__name__}", inline=False)
        status_embed.set_footer(text=f"Host: {host}:{port}")
        return status_embed

# ==============================================================================
# PALWORLD BAN LIST MANAGEMENT
# ==============================================================================

def load_palworld_ban_list():
    """Loads the persistent Palworld ban list from a JSON file."""
    if os.path.exists(PAL_BAN_LIST_FILE):
        with open(PAL_BAN_LIST_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print("Warning: Palworld ban file is corrupt. Starting with an empty list.")
                return set()
    return set()

def save_palworld_ban_list(ban_set):
    """Saves the persistent Palworld ban list to a JSON file."""
    with open(PAL_BAN_LIST_FILE, 'w') as f:
        json.dump(list(ban_set), f, indent=4)

# ==============================================================================
# BOT EVENTS
# ==============================================================================

@bot.event
async def on_ready():
    """Confirms the bot is logged in and ready."""
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=Game(name="Monitoring Servers..."))

    # Start the automated tasks
    if ASA_SAVE_INTERVAL > 0:
        asa_auto_save.start()
    if PAL_SAVE_INTERVAL > 0:
        pal_auto_save.start()

# ==============================================================================
# GLOBAL PLAYER COMMANDS (Accessible by everyone)
# ==============================================================================

@bot.command(name='status')
async def check_all_status(ctx):
    """Displays the status (online/offline) and player count for all servers."""
    await ctx.defer() # Defer the response for long-running status checks
    
    # Check all servers concurrently
    mc_status_task = get_server_status(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, "Minecraft", "list")
    pal_status_task = get_server_status(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "Palworld", "ShowPlayers")
    asa_status_task = get_server_status(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, "ASA", "ListPlayers")

    results = await asyncio.gather(mc_status_task, pal_status_task, asa_status_task)
    
    # Send all results in a single message
    for embed in results:
        await ctx.send(embed=embed)


@bot.command(name='info')
async def bot_info(ctx):
    """Displays general information about the bot."""
    info_embed = Embed(
        title="Server Monitor Bot Info",
        description="I monitor the dedicated game servers and handle admin commands.",
        color=Colour.blue()
    )
    info_embed.add_field(name="Available Player Command", value="`!status` - Check server status and player count.", inline=False)
    info_embed.add_field(name="Admin Commands", value=f"Available in the designated admin channel (ID: `{ADMIN_CHANNEL_ID}`).", inline=False)
    info_embed.set_footer(text=f"Bot provided by {bot.user.name}")
    await ctx.send(embed=info_embed)


# ==============================================================================
# MINECRAFT RCON COMMANDS (Admin Channel Only)
# ==============================================================================

@bot.command(name='say_mc')
@commands.has_permissions(administrator=True)
async def say_mc(ctx, *, message):
    """Broadcasts a message to the Minecraft server."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")
        
    try:
        async with RconAsync(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD) as rcon:
            # Use 'say' command to broadcast message
            response = await rcon.send(f"say [Discord Admin] {message}")
            if "Unknown command" in response:
                await ctx.send(f"❌ RCON Error: Unknown Minecraft command or login failed.")
            else:
                await ctx.send(f"✅ Message sent to Minecraft server: **{message}**")
    except Exception as e:
        await ctx.send(f"❌ RCON connection failed for Minecraft: {e.__class__.__name__}")

@bot.command(name='ban_mc')
@commands.has_permissions(administrator=True)
async def ban_mc(ctx, player_name):
    """Bans a player by name on the Minecraft server."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    try:
        async with RconAsync(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD) as rcon:
            response = await rcon.send(f"ban {player_name}")
            if "Usage:" in response or "Unknown command" in response:
                 await ctx.send(f"❌ RCON Error: Unknown Minecraft command or login failed.")
            else:
                await ctx.send(f"🔨 Player **{player_name}** banned from Minecraft.")
    except Exception as e:
        await ctx.send(f"❌ RCON connection failed for Minecraft: {e.__class__.__name__}")

# ==============================================================================
# PALWORLD RCON COMMANDS (Admin Channel Only)
# ==============================================================================

@bot.command(name='shutdown_pal')
@commands.has_permissions(administrator=True)
async def shutdown_pal(ctx, delay_seconds: int = 60, *, message: str = "Server is shutting down for maintenance!"):
    """Safely shuts down the Palworld server after a delay."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    try:
        async with RconAsync(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD) as rcon:
            # Palworld command is Shutdown {DelaySec} {Message}
            response = await rcon.send(f"Shutdown {delay_seconds} {message}")
            if response.strip() == "Server will shutdown after 60 seconds.": # Common error response on failure
                 await ctx.send(f"❌ RCON Error: Unknown Palworld command or login failed.")
            else:
                await ctx.send(f"⚠️ Palworld shutdown initiated! Message: **{message}** | Delay: **{delay_seconds}s**")
                # Also send to the Palworld channel for visibility
                pal_channel = bot.get_channel(PAL_CHANNEL_ID)
                if pal_channel:
                    await pal_channel.send(f"**🚨 SERVER ALERT 🚨**\nPalworld is shutting down in **{delay_seconds} seconds**!\nReason: *{message}*")
    except Exception as e:
        await ctx.send(f"❌ RCON connection failed for Palworld: {e.__class__.__name__}")


@bot.command(name='save_pal')
@commands.has_permissions(administrator=True)
async def save_pal(ctx):
    """Manually triggers an immediate world save for Palworld."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    try:
        async with RconAsync(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD) as rcon:
            response = await rcon.send("Save")
            if "Save" in response:
                await ctx.send("💾 Palworld world save command sent.")
                pal_channel = bot.get_channel(PAL_CHANNEL_ID)
                if pal_channel:
                    await pal_channel.send("💾 **Palworld Save Complete!** (Manual Trigger)")
            else:
                await ctx.send("❌ Palworld Save command failed. Check RCON status.")
    except Exception as e:
        await ctx.send(f"❌ RCON connection failed for Palworld: {e.__class__.__name__}")


@bot.command(name='ban_pal')
@commands.has_permissions(administrator=True)
async def ban_pal(ctx, steam_id: str):
    """Bans a player by Steam ID and saves the ID to a persistent list."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    steam_id = steam_id.strip()
    if not re.match(r'^\d{17}$', steam_id):
        return await ctx.send("❌ Invalid Steam ID format. Must be a 17-digit number.")
        
    ban_list = load_palworld_ban_list()
    ban_list.add(steam_id)
    save_palworld_ban_list(ban_list)
    
    # Try to kick the player immediately
    try:
        async with RconAsync(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD) as rcon:
            # Palworld RCON KickPlayer is by SteamID
            await rcon.send(f"KickPlayer {steam_id}")
            await ctx.send(f"🔨 Player with Steam ID **{steam_id}** added to persistent ban list and immediately kicked.")
    except Exception as e:
        await ctx.send(f"⚠️ Player added to persistent ban list. RCON Kick failed: {e.__class__.__name__} (They will be kicked on next check).")


@bot.command(name='unban_pal')
@commands.has_permissions(administrator=True)
async def unban_pal(ctx, steam_id: str):
    """Removes a Steam ID from the persistent Palworld ban list."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    steam_id = steam_id.strip()
    ban_list = load_palworld_ban_list()
    
    if steam_id in ban_list:
        ban_list.remove(steam_id)
        save_palworld_ban_list(ban_list)
        await ctx.send(f"✅ Steam ID **{steam_id}** removed from the persistent ban list.")
    else:
        await ctx.send(f"❌ Steam ID **{steam_id}** was not found in the persistent ban list.")


@bot.command(name='list_bans_pal')
@commands.has_permissions(administrator=True)
async def list_bans_pal(ctx):
    """Lists all Steam IDs currently on the persistent Palworld ban list."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    ban_list = load_palworld_ban_list()
    if ban_list:
        bans = "\n".join(ban_list)
        await ctx.send(f"📜 **Palworld Persistent Bans**:\n```\n{bans}\n```")
    else:
        await ctx.send("✅ The persistent Palworld ban list is currently empty.")


@tasks.loop(minutes=PAL_SAVE_INTERVAL)
async def pal_auto_save():
    """Automated Palworld world saving loop."""
    # Only run the save command, don't send a message here, only on successful completion
    try:
        async with RconAsync(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD) as rcon:
            await rcon.send("Save")
            pal_channel = bot.get_channel(PAL_CHANNEL_ID)
            if pal_channel:
                 # Send a brief update to the Palworld channel
                await pal_channel.send(f"💾 **Auto-Save Complete!** Next save in {PAL_SAVE_INTERVAL} minutes.")
    except Exception as e:
        print(f"[Palworld Auto-Save] Failed to connect or send command: {e}")
        # Optionally send an error to the PAL_CHANNEL_ID or ADMIN_CHANNEL_ID


# ==============================================================================
# ARK: ASA RCON COMMANDS (Admin Channel Only)
# ==============================================================================

@bot.command(name='ban_asa')
@commands.has_permissions(administrator=True)
async def ban_asa(ctx, identifier):
    """Bans a player by name or ID on the ASA server."""
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send(f"❌ This command can only be used in the admin channel (ID: `{ADMIN_CHANNEL_ID}`).")

    try:
        async with RconAsync(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD) as rcon:
            # ARK command is BanPlayer <SteamID or CharacterName>
            rcon_command = f"BanPlayer {identifier}"
            response = await rcon.send(rcon_command)
            
            # ASA RCON responses can be vague or complex.
            if "Unknown command" in response:
                await ctx.send(f"❌ RCON Error: Unknown ASA command or login failed.")
            elif "not found" in response.lower():
                 await ctx.send(f"⚠️ Player **{identifier}** not found on server or RCON response was vague: `{response}`")
            else:
                await ctx.send(f"🔨 Player **{identifier}** banned from ASA.")
    except Exception as e:
        await ctx.send(f"❌ RCON connection failed for ASA: {e.__class__.__name__}")


@tasks.loop(minutes=ASA_SAVE_INTERVAL)
async def asa_auto_save():
    """Automated ARK: ASA world saving loop."""
    try:
        async with RconAsync(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD) as rcon:
            await rcon.send("SaveWorld")
            asa_channel = bot.get_channel(ASA_CHANNEL_ID)
            if asa_channel:
                await asa_channel.send(f"💾 **Auto-Save Complete!** Next save in {ASA_SAVE_INTERVAL} minutes.")
    except Exception as e:
        print(f"[ASA Auto-Save] Failed to connect or send command: {e}")
        # Optionally send an error to the ASA_CHANNEL_ID or ADMIN_CHANNEL_ID


# ==============================================================================
# ERROR HANDLING
# ==============================================================================

@bot.event
async def on_command_error(ctx, error):
    """Global command error handler."""
    if isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors to avoid spamming the channel
        return
    
    # Check for permission error, specifically for RCON commands
    if isinstance(error, commands.MissingPermissions):
        # Check if the command should only be run in the admin channel
        if ctx.command.name in ['say_mc', 'ban_mc', 'shutdown_pal', 'save_pal', 'ban_pal', 'unban_pal', 'list_bans_pal', 'ban_asa']:
            # This check is redundant because the command body already checks the channel ID, 
            # but this handles cases where the user is an admin but uses it outside the dedicated channel
             if ctx.channel.id != ADMIN_CHANNEL_ID:
                 await ctx.send(f"❌ **Admin Channel Required!** Please use admin commands in the designated admin channel (ID: `{ADMIN_CHANNEL_ID}`).")
                 return
        
        # If it's a true missing administrator permission issue
        await ctx.send(f"❌ **Permission Denied!** You need **Administrator** permissions to use the `!{ctx.command.name}` command.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ **Missing Argument!** You need to provide the required arguments. Usage: `!{ctx.command.name} {ctx.command.signature}`")
        return

    # Handle generic/unhandled errors
    print(f"Unhandled command error in {ctx.command}: {error}")
    await ctx.send(f"❌ An internal error occurred while running the command: `{error}`")
    
# ==============================================================================
# BOT RUN
# ==============================================================================

# Ensure the token is set before running
if DISCORD_TOKEN != "YOUR_DISCORD_BOT_TOKEN_HERE" and DISCORD_TOKEN:
    # Run the bot
    try:
        # Run the bot with the specified token
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Failed to run the bot. Check your DISCORD_TOKEN and permissions. Error: {e}")
else:
    print("FATAL: DISCORD_TOKEN is missing or set to the default placeholder. Please configure it.")
