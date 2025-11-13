import os
import asyncio
import json
import re
from datetime import datetime
from discord.ext import commands, tasks
from discord import Intents, Status, Game, Embed, Colour
from rcon.asyncio import RconAsync, RCONException
from dotenv import load_dotenv # New Import

# Load environment variables from .env file
load_dotenv()

# ==============================================================================
# ⚠️ CONFIGURATION BLOCK ⚠️
# All configurations are now loaded from the .env file.
# ==============================================================================

# --- DISCORD CONFIGURATION ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', "YOUR_DISCORD_BOT_TOKEN_HERE")

# Channel IDs for different log/status types
ADMIN_CHANNEL_ID = int(os.getenv('ADMIN_CHANNEL_ID', 0))
MC_CHANNEL_ID = int(os.getenv('MC_CHANNEL_ID', 0))
PAL_CHANNEL_ID = int(os.getenv('PAL_CHANNEL_ID', 0))
ASA_CHANNEL_ID = int(os.getenv('ASA_CHANNEL_ID', 0))

# --- MINECRAFT RCON CONFIGURATION ---
MC_RCON_HOST = os.getenv('MC_RCON_HOST', "127.0.0.1")
MC_RCON_PORT = int(os.getenv('MC_RCON_PORT', 25575))
MC_RCON_PASSWORD = os.getenv('MC_RCON_PASSWORD', "YOUR_MC_RCON_PASSWORD_HERE")

# --- PALWORLD RCON CONFIGURATION ---
PAL_RCON_HOST = os.getenv('PAL_RCON_HOST', "127.0.0.1")
PAL_RCON_PORT = int(os.getenv('PAL_RCON_PORT', 25576))
PAL_RCON_PASSWORD = os.getenv('PAL_RCON_PASSWORD', "YOUR_PAL_RCON_PASSWORD_HERE")
PAL_SAVE_INTERVAL = int(os.getenv('PAL_SAVE_INTERVAL', 30)) # Minutes
# The Palworld monitor task will run every 15 seconds to check online players against the blacklist
PAL_MONITOR_INTERVAL = 15 

# --- ARK: ASA RCON CONFIGURATION ---
ASA_RCON_HOST = os.getenv('ASA_RCON_HOST', "127.0.0.1")
ASA_RCON_PORT = int(os.getenv('ASA_RCON_PORT', 25577))
ASA_RCON_PASSWORD = os.getenv('ASA_RCON_PASSWORD', "YOUR_ASA_RCON_PASSWORD_HERE")
ASA_SAVE_INTERVAL = int(os.getenv('ASA_SAVE_INTERVAL', 60)) # Minutes


# ==============================================================================
# BOT INITIALIZATION
# ==============================================================================

# Setup Discord Intents
intents = Intents.default()
intents.message_content = True  # Required for command processing
intents.messages = True
intents.guilds = True

# Initialize Bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Global data store for Palworld's persistent ban list (Steam IDs)
PAL_BLACKLIST_FILE = 'palworld_blacklist.json'
pal_blacklist = set() 
# Global data store for online status
SERVER_STATUS = {
    'Minecraft': {'is_online': False, 'players': 0},
    'Palworld': {'is_online': False, 'players': 0},
    'ASA': {'is_online': False, 'players': 0},
}


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def load_blacklist():
    """Loads the Palworld blacklist from the JSON file."""
    global pal_blacklist
    if os.path.exists(PAL_BLACKLIST_FILE):
        try:
            with open(PAL_BLACKLIST_FILE, 'r') as f:
                data = json.load(f)
                pal_blacklist = set(data.get('banned_steam_ids', []))
                print(f"Loaded {len(pal_blacklist)} Palworld blacklisted IDs.")
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading Palworld blacklist: {e}")
            pal_blacklist = set()

def save_blacklist():
    """Saves the Palworld blacklist to the JSON file."""
    try:
        with open(PAL_BLACKLIST_FILE, 'w') as f:
            json.dump({'banned_steam_ids': list(pal_blacklist)}, f, indent=4)
        print("Palworld blacklist saved.")
    except IOError as e:
        print(f"Error saving Palworld blacklist: {e}")

async def run_rcon_command(host, port, password, command, game_name):
    """Generic function to run an RCON command and return the result."""
    try:
        async with RconAsync(host, port, passwd=password) as rcon:
            response = await rcon(command)
            return response
    except RCONException as e:
        print(f"RCON ERROR ({game_name}): {e}")
        return f"RCON_ERROR: {e}"
    except ConnectionRefusedError:
        return "CONNECTION_REFUSED"
    except asyncio.TimeoutError:
        return "TIMEOUT_ERROR"
    except Exception as e:
        return f"UNHANDLED_ERROR: {e}"

def is_admin(ctx):
    """Check if the user has Administrator permissions."""
    return ctx.author.guild_permissions.administrator

def check_admin_channel(ctx):
    """Check if the command is run in the dedicated Admin Channel."""
    return ctx.channel.id == ADMIN_CHANNEL_ID

# ==============================================================================
# DISCORD EVENTS
# ==============================================================================

@bot.event
async def on_ready():
    """Event triggered when the bot is ready."""
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('Bot is ready and connected to Discord.')

    load_blacklist()

    # Start the background loops
    check_all_server_status.start()
    pal_auto_save.start()
    asa_auto_save.start()
    pal_blacklist_monitor.start()

    # Set initial bot status
    await bot.change_presence(status=Status.online, activity=Game(name="Monitoring Servers"))


# ==============================================================================
# BACKGROUND TASKS (LOOPS)
# ==============================================================================

@tasks.loop(minutes=5)
async def check_all_server_status():
    """Checks the online status and player count for all servers."""
    print("--- Running Server Status Check ---")
    
    # ---------------------------------
    # Minecraft Check
    # ---------------------------------
    mc_response = await run_rcon_command(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, "list", "Minecraft")
    
    mc_was_online = SERVER_STATUS['Minecraft']['is_online']
    
    if mc_response and not isinstance(mc_response, str) and "players online" in mc_response:
        match = re.search(r"There are (\d+) of a max", mc_response)
        players = int(match.group(1)) if match else 0
        SERVER_STATUS['Minecraft'].update({'is_online': True, 'players': players})

        if not mc_was_online:
            channel = bot.get_channel(MC_CHANNEL_ID)
            if channel: await channel.send(f"✅ **Minecraft Server is back online!**")
    else:
        SERVER_STATUS['Minecraft'].update({'is_online': False, 'players': 0})
        if mc_was_online:
            channel = bot.get_channel(MC_CHANNEL_ID)
            if channel: await channel.send(f"❌ **Minecraft Server is offline!**")

    # ---------------------------------
    # Palworld Check
    # ---------------------------------
    pal_response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "ShowPlayers", "Palworld")
    
    pal_was_online = SERVER_STATUS['Palworld']['is_online']

    if pal_response and not isinstance(pal_response, str) and pal_response.startswith("name,playeruid,steamid"):
        # Palworld returns player list including header, count lines (header + 1 per player)
        players = len(pal_response.strip().split('\n')) - 1
        SERVER_STATUS['Palworld'].update({'is_online': True, 'players': players})

        if not pal_was_online:
            channel = bot.get_channel(PAL_CHANNEL_ID)
            if channel: await channel.send(f"✅ **Palworld Server is back online!**")
    else:
        SERVER_STATUS['Palworld'].update({'is_online': False, 'players': 0})
        if pal_was_online:
            channel = bot.get_channel(PAL_CHANNEL_ID)
            if channel: await channel.send(f"❌ **Palworld Server is offline!**")
    
    # ---------------------------------
    # ASA Check
    # ---------------------------------
    asa_response = await run_rcon_command(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, "GetPlayerList", "ASA")
    
    asa_was_online = SERVER_STATUS['ASA']['is_online']

    if asa_response and not isinstance(asa_response, str) and asa_response.startswith("Name,EOSID"):
        # ASA returns player list including header
        players = len(asa_response.strip().split('\n')) - 1
        SERVER_STATUS['ASA'].update({'is_online': True, 'players': players})

        if not asa_was_online:
            channel = bot.get_channel(ASA_CHANNEL_ID)
            if channel: await channel.send(f"✅ **ARK: ASA Server is back online!**")
    else:
        SERVER_STATUS['ASA'].update({'is_online': False, 'players': 0})
        if asa_was_online:
            channel = bot.get_channel(ASA_CHANNEL_ID)
            if channel: await channel.send(f"❌ **ARK: ASA Server is offline!**")


@tasks.loop(minutes=PAL_SAVE_INTERVAL)
async def pal_auto_save():
    """Automatically saves the Palworld world."""
    await bot.wait_until_ready()
    if SERVER_STATUS['Palworld']['is_online']:
        print("--- Running Palworld Auto-Save ---")
        response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "Save", "Palworld")
        channel = bot.get_channel(PAL_CHANNEL_ID)
        
        if channel:
            if "RCON_ERROR" in response or "TIMEOUT_ERROR" in response or "CONNECTION_REFUSED" in response:
                await channel.send(f"⚠️ **Palworld Auto-Save Failed!** Server responded with an error.")
            else:
                await channel.send("💾 **Palworld Auto-Save:** World data saved successfully.")


@tasks.loop(minutes=ASA_SAVE_INTERVAL)
async def asa_auto_save():
    """Automatically saves the ARK: ASA world."""
    await bot.wait_until_ready()
    if SERVER_STATUS['ASA']['is_online']:
        print("--- Running ASA Auto-Save ---")
        response = await run_rcon_command(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, "SaveWorld", "ASA")
        channel = bot.get_channel(ASA_CHANNEL_ID)

        if channel:
            if "RCON_ERROR" in response or "TIMEOUT_ERROR" in response or "CONNECTION_REFUSED" in response:
                await channel.send(f"⚠️ **ASA Auto-Save Failed!** Server responded with an error.")
            else:
                await channel.send("💾 **ARK: ASA Auto-Save:** World data saved successfully.")


@tasks.loop(seconds=PAL_MONITOR_INTERVAL)
async def pal_blacklist_monitor():
    """Periodically checks online players against the persistent blacklist and kicks them."""
    await bot.wait_until_ready()
    if not SERVER_STATUS['Palworld']['is_online'] or not pal_blacklist:
        return
    
    print(f"--- Running Palworld Blacklist Monitor. Blacklisted: {len(pal_blacklist)} ---")

    player_list_response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "ShowPlayers", "Palworld")
    
    if not player_list_response or "RCON_ERROR" in player_list_response or "TIMEOUT_ERROR" in player_list_response:
        return

    # Skip header line
    player_lines = player_list_response.strip().split('\n')[1:]
    channel = bot.get_channel(PAL_CHANNEL_ID)

    for line in player_lines:
        parts = line.split(',')
        if len(parts) >= 3:
            # Palworld RCON returns: name,playeruid,steamid
            steam_id = parts[2].strip()
            player_name = parts[0].strip()

            if steam_id in pal_blacklist:
                print(f"Banned player detected: {player_name} ({steam_id}). Kicking...")
                
                # Use the KickPlayer command with Steam ID
                kick_response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, f"KickPlayer {steam_id}", "Palworld")
                
                if channel:
                    if "RCON_ERROR" in kick_response:
                        await channel.send(f"⚠️ **Blacklist Kick Failed:** Could not kick player `{player_name}` ({steam_id}). RCON Error.")
                    else:
                        await channel.send(f"🚨 **Blacklisted Player Kicked:** Player **{player_name}** (`{steam_id}`) was detected and automatically kicked.")
                
                # Optimization: Since the player is kicked, no need to process other players in this loop iteration.
                # continue (but safe to let loop finish too)


# ==============================================================================
# DISCORD COMMANDS - GENERAL STATUS
# ==============================================================================

@bot.command(name='status')
async def get_status(ctx):
    """Checks the status and player count for all configured servers."""
    
    embed = Embed(
        title="🌐 Multi-Server Status Report",
        description=f"Real-time status check as of {datetime.now().strftime('%H:%M:%S')}",
        colour=Colour.blue()
    )

    # Minecraft
    mc_status = SERVER_STATUS['Minecraft']
    mc_emoji = "🟢" if mc_status['is_online'] else "🔴"
    mc_text = f"{mc_emoji} **Minecraft:** {'Online' if mc_status['is_online'] else 'Offline'} ({mc_status['players']} players)"
    embed.add_field(name="Minecraft", value=mc_text, inline=False)
    
    # Palworld
    pal_status = SERVER_STATUS['Palworld']
    pal_emoji = "🟢" if pal_status['is_online'] else "🔴"
    pal_text = f"{pal_emoji} **Palworld:** {'Online' if pal_status['is_online'] else 'Offline'} ({pal_status['players']} players)"
    embed.add_field(name="Palworld", value=pal_text, inline=False)

    # ASA
    asa_status = SERVER_STATUS['ASA']
    asa_emoji = "🟢" if asa_status['is_online'] else "🔴"
    asa_text = f"{asa_emoji} **ARK: ASA:** {'Online' if asa_status['is_online'] else 'Offline'} ({asa_status['players']} players)"
    embed.add_field(name="ARK: ASA", value=asa_text, inline=False)

    await ctx.send(embed=embed)


# ==============================================================================
# DISCORD COMMANDS - PALWORLD (Blacklist-aware)
# ==============================================================================

@bot.command(name='ban_pal')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def ban_pal(ctx, steam_id: str):
    """Bans a player by Steam ID from Palworld (adds to persistent blacklist)."""
    
    # Clean and validate Steam ID format (simple check)
    if not re.match(r'^\d{17}$', steam_id):
        await ctx.send("❌ Error: Palworld bans require a valid **17-digit Steam ID**.")
        return

    if steam_id in pal_blacklist:
        await ctx.send(f"⚠️ Steam ID `{steam_id}` is already on the persistent blacklist.")
        return

    pal_blacklist.add(steam_id)
    save_blacklist()

    # Attempt to kick immediately if the server is online
    if SERVER_STATUS['Palworld']['is_online']:
        kick_response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, f"KickPlayer {steam_id}", "Palworld")
        
        if "RCON_ERROR" in kick_response:
             await ctx.send(f"🔨 Player **{steam_id}** added to persistent blacklist. Kick attempt failed (RCON Error). Monitor will kick them if they join.")
        else:
             await ctx.send(f"🔨 Player **{steam_id}** added to persistent blacklist and **kicked** from the server.")
    else:
        await ctx.send(f"🔨 Player **{steam_id}** added to persistent blacklist. Server is offline, so no immediate kick was attempted.")


@bot.command(name='unban_pal')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def unban_pal(ctx, steam_id: str):
    """Removes a Steam ID from the Palworld persistent blacklist."""
    
    if steam_id in pal_blacklist:
        pal_blacklist.remove(steam_id)
        save_blacklist()
        await ctx.send(f"✅ Steam ID `{steam_id}` has been removed from the persistent blacklist.")
    else:
        await ctx.send(f"⚠️ Steam ID `{steam_id}` was not found on the persistent blacklist.")


@bot.command(name='list_bans_pal')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def list_bans_pal(ctx):
    """Lists all Steam IDs currently on the Palworld persistent blacklist."""
    
    if not pal_blacklist:
        await ctx.send("✅ The Palworld persistent blacklist is currently empty.")
        return
    
    list_str = "\n".join(pal_blacklist)
    
    # Discord has a limit for message length, truncate if necessary
    if len(list_str) > 1800:
        list_str = list_str[:1800] + "\n... (list truncated)"

    await ctx.send(f"**Palworld Persistent Blacklist ({len(pal_blacklist)} IDs):**\n```\n{list_str}\n```")


# ==============================================================================
# DISCORD COMMANDS - GENERAL RCON
# (Minecraft, Palworld, ASA)
# ==============================================================================

@bot.command(name='say_mc')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def say_mc(ctx, *, message: str):
    """Sends a message to all players on the Minecraft server."""
    response = await run_rcon_command(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, f"say {message}", "Minecraft")
    if isinstance(response, str) and response.startswith(("RCON_ERROR", "CONNECTION_REFUSED", "TIMEOUT_ERROR")):
        await ctx.send(f"❌ Failed to send message to Minecraft: `{response}`")
    else:
        await ctx.send(f"✅ Message sent to Minecraft: `{message}`")

# NOTE: Palworld 'DoExit' is needed for safe shutdown, delay is handled by the bot sending warnings.
@bot.command(name='shutdown_pal')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def shutdown_pal(ctx, delay: int = 60, *, message: str = "Server is shutting down for maintenance!")
    """Shuts down the Palworld server with a countdown (default 60s)."""
    
    if delay > 0:
        # 1. Send immediate warning
        await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, f"Broadcast {message} - Shutting down in {delay} seconds!", "Palworld")

        # 2. Wait for countdown
        await ctx.send(f"⚠️ **Palworld Shutdown initiated:** Waiting {delay} seconds...")
        await asyncio.sleep(delay)
    
    # 3. Final command
    response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "DoExit", "Palworld")
    
    if isinstance(response, str) and response.startswith(("RCON_ERROR", "CONNECTION_REFUSED", "TIMEOUT_ERROR")):
        await ctx.send(f"❌ **Palworld Shutdown FAILED!** Server responded with an error: `{response}`")
    else:
        await ctx.send(f"🚨 **Palworld Shutdown Command Sent.** Server should be offline shortly.")


@bot.command(name='save_pal')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def save_pal(ctx):
    """Manually triggers a world save on the Palworld server."""
    response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "Save", "Palworld")
    if isinstance(response, str) and response.startswith(("RCON_ERROR", "CONNECTION_REFUSED", "TIMEOUT_ERROR")):
        await ctx.send(f"❌ **Palworld Save Failed:** Server responded with an error: `{response}`")
    else:
        await ctx.send("💾 **Palworld Save:** World data saved successfully.")


# Placeholder commands for other games (implementation details omitted for brevity, but pattern is the same)
@bot.command(name='ban_mc')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def ban_mc(ctx, player_name: str):
    """Bans a player by name from the Minecraft server."""
    response = await run_rcon_command(MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, f"ban {player_name}", "Minecraft")
    if isinstance(response, str) and response.startswith(("RCON_ERROR", "CONNECTION_REFUSED", "TIMEOUT_ERROR")):
        await ctx.send(f"❌ Failed to ban player from Minecraft: `{response}`")
    else:
        await ctx.send(f"🔨 Player **{player_name}** banned from Minecraft.")


@bot.command(name='ban_asa')
@commands.check(is_admin)
@commands.check(check_admin_channel)
async def ban_asa(ctx, identifier: str):
    """Bans a player by Steam ID or name from the ASA server."""
    # Note: ASA uses BanPlayer <ID> or BanPlayer <Name>
    response = await run_rcon_command(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, f"BanPlayer {identifier}", "ASA")
    if isinstance(response, str) and response.startswith(("RCON_ERROR", "CONNECTION_REFUSED", "TIMEOUT_ERROR")):
        await ctx.send(f"❌ Failed to ban player from ASA: `{response}`")
    elif "Command BanPlayer finished" not in response and "was not found" not in response:
        # ASA RCON is often quiet on success, check for known error messages
        await ctx.send(f"❌ ASA Ban command response was unexpected: `{response}`")
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
    
    if isinstance(error, commands.CheckFailure):
        # Handles both missing permissions and wrong channel
        if not is_admin(ctx):
            await ctx.send(f"❌ **Permission Denied!** You need **Administrator** permissions to use this command.")
        elif not check_admin_channel(ctx):
            await ctx.send(f"⚠️ **Wrong Channel!** All RCON administration commands must be run in the designated Admin Channel (ID: `{ADMIN_CHANNEL_ID}`).")
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
    print("FATAL: DISCORD_TOKEN is missing or set to the default placeholder. Please configure it in the **.env** file.")
