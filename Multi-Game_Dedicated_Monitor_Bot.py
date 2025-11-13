# -*- coding: utf-8 -*-
import os
import asyncio
import json
import re
from datetime import datetime
from discord.ext import commands, tasks
from discord import Intents, Status, Game, Embed, Colour
from rcon.asyncio import RconAsync, RCONException
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================================================================
# ⚠️ CONFIGURATION BLOCK ⚠️
# The bot reads settings from environment variables (e.g., in a .env file).
# ==============================================================================

# --- DISCORD CONFIGURATION ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', "YOUR_DISCORD_BOT_TOKEN_HERE")
ADMIN_CHANNEL_ID = int(os.getenv('ADMIN_CHANNEL_ID', 0)) # Channel where RCON commands are allowed
MC_CHANNEL_ID = int(os.getenv('MC_CHANNEL_ID', 0)) # Channel for Minecraft status/logs
PAL_CHANNEL_ID = int(os.getenv('PAL_CHANNEL_ID', 0)) # Channel for Palworld status/logs
ASA_CHANNEL_ID = int(os.getenv('ASA_CHANNEL_ID', 0)) # Channel for ARK: ASA status/logs

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

# --- BOT SETUP ---
intents = Intents.default()
intents.message_content = True # Required to read command messages
intents.members = True # Required for some discord.py features if needed later
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# RCON settings mapping for convenience
RCON_SETTINGS = {
    'mc': (MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD),
    'pal': (PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD),
    'asa': (ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD),
}

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

async def run_rcon_command(host, port, password, command):
    """Executes a single RCON command and returns the response string."""
    if not password or password == "YOUR_MC_RCON_PASSWORD_HERE":
        raise RCONException("RCON password is not configured.")
    
    try:
        async with RconAsync(host, port, password) as rcon:
            response = await rcon.send(command)
            return response
    except RCONException as e:
        print(f"RCON Error for command '{command}' on {host}:{port}: {e}")
        raise

async def run_rcon_command_with_feedback(ctx, host, port, password, command, success_message=None):
    """Executes RCON command, sends feedback to Discord, and returns the response."""
    try:
        response = await run_rcon_command(host, port, password, command)
        
        # Clean up common Palworld/ASA successful command responses
        if response.startswith("Command received") or response.strip() == "Server saved.":
            response = "Command executed successfully."

        if success_message:
            await ctx.send(f"✅ {success_message}\n```\n{response}\n```")
        else:
            await ctx.send(f"✅ Command executed:\n```\n{response}\n```")
        return response
    
    except RCONException as e:
        await ctx.send(f"❌ RCON Connection Error: Could not connect or authenticate to server. `{e}`")
        return None
    except Exception as e:
        await ctx.send(f"❌ An error occurred: `{e}`")
        return None


def is_admin_channel():
    """Check if the command is run in the designated admin channel."""
    async def predicate(ctx):
        if ctx.channel.id != ADMIN_CHANNEL_ID:
            await ctx.send(f"⚠️ This command can only be used in the designated administration channel (<#{ADMIN_CHANNEL_ID}>).")
            return False
        return True
    return commands.check(predicate)

# ==============================================================================
# RCON MONITORING TASKS
# ==============================================================================

# --- Palworld Auto-Save Task ---
@tasks.loop(minutes=PAL_SAVE_INTERVAL)
async def pal_auto_save():
    """Automatically saves the Palworld server every PAL_SAVE_INTERVAL minutes."""
    if not PAL_RCON_HOST or PAL_RCON_PASSWORD == "YOUR_PAL_RCON_PASSWORD_HERE":
        return # Skip if not configured

    channel = bot.get_channel(PAL_CHANNEL_ID)
    if not channel:
        return

    try:
        response = await run_rcon_command(PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, "Save")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        embed = Embed(
            title="💾 Palworld Server Auto-Save",
            description=f"Server save initiated successfully at {timestamp}.",
            colour=Colour.blue()
        )
        if response and response.strip() != "Server saved.":
             embed.add_field(name="RCON Response", value=f"```\n{response}\n```", inline=False)
        await channel.send(embed=embed)
        
    except Exception as e:
        print(f"Palworld Auto-Save Error: {e}")
        # Optionally notify admin channel if save fails repeatedly
        
# --- ASA Auto-Save Task ---
@tasks.loop(minutes=ASA_SAVE_INTERVAL)
async def asa_auto_save():
    """Automatically saves the ASA server every ASA_SAVE_INTERVAL minutes."""
    if not ASA_RCON_HOST or ASA_RCON_PASSWORD == "YOUR_ASA_RCON_PASSWORD_HERE":
        return # Skip if not configured

    channel = bot.get_channel(ASA_CHANNEL_ID)
    if not channel:
        return

    try:
        # ARK's command for save is usually 'SaveWorld' or 'DoExit' followed by 'SaveWorld' depending on version
        response = await run_rcon_command(ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, "SaveWorld")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        embed = Embed(
            title="💾 ARK: ASA Server Auto-Save",
            description=f"Server save initiated successfully at {timestamp}.",
            colour=Colour.purple()
        )
        if response:
             embed.add_field(name="RCON Response", value=f"```\n{response}\n```", inline=False)
        await channel.send(embed=embed)
        
    except Exception as e:
        print(f"ASA Auto-Save Error: {e}")


# ==============================================================================
# BOT EVENTS
# ==============================================================================

@bot.event
async def on_ready():
    """Fires when the bot successfully connects to Discord."""
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    await bot.change_presence(activity=Game(name="Monitoring Dedicated Servers..."))
    
    # Start looping tasks only if RCON configuration is valid
    if PAL_RCON_PASSWORD != "YOUR_PAL_RCON_PASSWORD_HERE" and PAL_RCON_HOST:
        pal_auto_save.start()
        print(f"Palworld Auto-Save task started, interval: {PAL_SAVE_INTERVAL} min.")
        
    if ASA_RCON_PASSWORD != "YOUR_ASA_RCON_PASSWORD_HERE" and ASA_RCON_HOST:
        asa_auto_save.start()
        print(f"ASA Auto-Save task started, interval: {ASA_SAVE_INTERVAL} min.")


@bot.command(name='help', help="Shows available commands and their usage.")
async def help_command(ctx):
    """Generates a detailed help message."""
    embed = Embed(
        title="🎮 Multi-Game Monitor Bot Commands",
        description="Prefix: `!` | Commands are case-sensitive.\n\n"
                    "⚠️ Admin commands require **Administrator** permission and must be run in "
                    f"the admin channel (<#{ADMIN_CHANNEL_ID}>).",
        colour=Colour.teal()
    )

    # General Commands (Status, Players, RCON Raw)
    embed.add_field(
        name="📊 General Status & Raw RCON",
        value="`!status <game>`: Get server status (online/offline).\n"
              "`!players <game>`: List connected players.\n"
              "`!rcon_raw <game> <command>`: [ADMIN] Send a raw RCON command to the server.\n"
              "*(Game: mc, pal, asa)*",
        inline=False
    )
    
    # Admin Commands (Server Management)
    admin_commands = [
        "`!save <game>`: [ADMIN] Manually force a server save.",
        "`!broadcast <game> <message>` or `!say <game> <message>`: [ADMIN] Send a message to all players.",
        "`!kick <game> <identifier> [reason]`:[ADMIN] Kick a player (name/ID).",
        "`!ban <game> <identifier> [reason]`:[ADMIN] Ban a player (name/ID).",
        "`!unban_<game> <identifier>`: [ADMIN] Unban a player. (e.g., `!unban_pal 12345`)",
    ]
    
    embed.add_field(
        name="🔨 Server Administration",
        value="\n".join(admin_commands),
        inline=False
    )

    # Minecraft Specific Commands
    mc_commands = [
        "`!mc_whitelist <player_name>`: [ADMIN] Adds player to Minecraft whitelist.",
        "`!mc_unwhitelist <player_name>`: [ADMIN] Removes player from Minecraft whitelist.",
    ]
    embed.add_field(
        name="⛏️ Minecraft Specific",
        value="\n".join(mc_commands),
        inline=False
    )
    
    await ctx.send(embed=embed)


# ==============================================================================
# GENERAL PURPOSE RCON COMMANDS (Applicable to MC, PAL, ASA)
# ==============================================================================

@bot.command(name='rcon_raw', help="[ADMIN] Sends a raw RCON command to a game server.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def rcon_raw(ctx, game: str, *, command: str):
    """Sends a raw RCON command to the specified game server."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")
    
    host, port, password = RCON_SETTINGS[game]
    
    await ctx.send(f"Sending raw command to **{game.upper()}**: `{command}`")
    
    # Use a generic success message since we don't know the expected output
    response = await run_rcon_command_with_feedback(
        ctx, host, port, password, command, 
        success_message=f"Raw command execution complete for {game.upper()}."
    )


@bot.command(name='status', help="Get the status of a server.")
async def status(ctx, game: str):
    """Checks RCON connectivity to determine server status."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")
    
    host, port, password = RCON_SETTINGS[game]
    
    if not password or password == "YOUR_MC_RCON_PASSWORD_HERE":
        return await ctx.send(f"❌ RCON not configured for **{game.upper()}**. Check the `.env` file.")

    try:
        # A simple command that should always work (e.g., list players for status check)
        await run_rcon_command(host, port, password, "ListPlayers" if game != 'mc' else "list")
        await ctx.send(f"🟢 **{game.upper()} Server** is Online and RCON is responsive!")
    except RCONException:
        await ctx.send(f"🔴 **{game.upper()} Server** is Offline or RCON is unresponsive.")
    except Exception as e:
        await ctx.send(f"⚠️ An unexpected error occurred while checking status: `{e}`")


@bot.command(name='players', help="List players currently on a server.")
async def players(ctx, game: str):
    """Lists players currently connected to the specified server."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")
    
    host, port, password = RCON_SETTINGS[game]
    
    command = "ShowPlayers" if game == 'asa' else "ListPlayers" if game == 'pal' else "list"
    
    await ctx.send(f"Requesting player list from **{game.upper()}**...")
    response = await run_rcon_command_with_feedback(ctx, host, port, password, command, success_message=f"Current Players on {game.upper()}:")


@bot.command(name='save', help="[ADMIN] Manually force a server save.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def save(ctx, game: str):
    """Forces the specified game server to save."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")
    
    host, port, password = RCON_SETTINGS[game]
    
    save_command = "save-all" if game == 'mc' else "Save" if game == 'pal' else "SaveWorld"
    
    await ctx.send(f"Attempting to manually save **{game.upper()}**...")
    await run_rcon_command_with_feedback(ctx, host, port, password, save_command, 
                                        success_message=f"Manual save command sent to {game.upper()} server.")

@bot.command(name='broadcast', aliases=['say'], help="[ADMIN] Send a message to all players.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def broadcast(ctx, game: str, *, message: str):
    """Sends a broadcast message to all players on the specified server."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")
    
    host, port, password = RCON_SETTINGS[game]
    
    if game == 'mc':
        command = f"say {message}"
    elif game == 'pal':
        command = f"Broadcast {message}"
    elif game == 'asa':
        command = f"ServerChat {message}" # Use ServerChat for simple messages
    else:
        return await ctx.send("❌ Broadcast not supported for that game.")
    
    await ctx.send(f"Broadcasting message to **{game.upper()}**: `{message}`")
    await run_rcon_command_with_feedback(ctx, host, port, password, command, 
                                        success_message=f"Message broadcasted to {game.upper()}.")


# ==============================================================================
# MINECRAFT (MC) SPECIFIC COMMANDS
# ==============================================================================

@bot.group(invoke_without_command=True)
@is_admin_channel()
async def mc(ctx):
    """Placeholder for Minecraft subcommands."""
    if ctx.invoked_subcommand is None:
        await ctx.send("Please use a subcommand like `!mc_whitelist` or check `!help`.")

@bot.command(name='mc_whitelist', help="[ADMIN] Adds a player to the Minecraft whitelist.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def mc_whitelist(ctx, player_name: str):
    """Adds a player to the Minecraft whitelist."""
    await ctx.send(f"Attempting to add **{player_name}** to Minecraft whitelist...")
    response = await run_rcon_command_with_feedback(ctx, MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, f"whitelist add {player_name}")
    
    if response:
        await ctx.send(f"✅ Player **{player_name}** added to Minecraft whitelist.")

@bot.command(name='mc_unwhitelist', help="[ADMIN] Removes a player from the Minecraft whitelist.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def mc_unwhitelist(ctx, player_name: str):
    """Removes a player from the Minecraft whitelist."""
    await ctx.send(f"Attempting to remove **{player_name}** from Minecraft whitelist...")
    response = await run_rcon_command_with_feedback(ctx, MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, f"whitelist remove {player_name}")
    
    if response:
        await ctx.send(f"✅ Player **{player_name}** removed from Minecraft whitelist.")


# ==============================================================================
# PLAYER MANAGEMENT COMMANDS
# ==============================================================================

@bot.command(name='kick', help="[ADMIN] Kick a player from a server.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def kick(ctx, game: str, identifier: str, *, reason: str = "Kicked by Admin"):
    """Kicks a player from the specified server."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")

    host, port, password = RCON_SETTINGS[game]
    
    if game == 'mc':
        command = f"kick {identifier} {reason}"
    elif game == 'pal':
        # Palworld KickPlayer requires Steam ID (identifier)
        command = f"KickPlayer {identifier}"
    elif game == 'asa':
        # ASA KickPlayer requires Steam ID or Player ID (identifier)
        command = f"KickPlayer {identifier}"
    else:
        return await ctx.send("❌ Kick not supported for that game.")
    
    await run_rcon_command_with_feedback(ctx, host, port, password, command)
    await ctx.send(f"🔨 Player **{identifier}** kicked from {game.upper()}. Reason: {reason}")


@bot.command(name='ban', help="[ADMIN] Ban a player from a server.")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def ban(ctx, game: str, identifier: str, *, reason: str = "Banned by Admin"):
    """Bans a player from the specified server."""
    game = game.lower()
    if game not in RCON_SETTINGS:
        return await ctx.send("❌ Invalid game specified. Use `mc`, `pal`, or `asa`.")

    host, port, password = RCON_SETTINGS[game]
    
    if game == 'mc':
        # Minecraft uses '/ban <playername> [reason]'
        command = f"ban {identifier} {reason}"
    elif game == 'pal':
        # Palworld BanPlayer requires Steam ID (identifier)
        command = f"BanPlayer {identifier}"
    elif game == 'asa':
        # ASA BanPlayer requires Steam ID or Player ID (identifier)
        command = f"BanPlayer {identifier}"
    else:
        return await ctx.send("❌ Ban not supported for that game.")
    
    await run_rcon_command_with_feedback(ctx, host, port, password, command)
    await ctx.send(f"🔨 Player **{identifier}** banned from {game.upper()}. Reason: {reason}")


@bot.command(name='unban_mc', help="[ADMIN] Unbans a player from the Minecraft server (requires player name).")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def unban_mc(ctx, identifier: str):
    """Unbans a player from the Minecraft server using their player name."""
    await ctx.send(f"Attempting to unban **{identifier}** from Minecraft...")
    response = await run_rcon_command_with_feedback(ctx, MC_RCON_HOST, MC_RCON_PORT, MC_RCON_PASSWORD, f"pardon {identifier}")
    
    if response:
        await ctx.send(f"🔨 Player **{identifier}** unbanned from MC.")


@bot.command(name='unban_pal', help="[ADMIN] Unbans a player from the Palworld server (requires Steam ID).")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def unban_pal(ctx, identifier: str):
    """Unbans a player from the Palworld server using their Steam ID."""
    await ctx.send(f"Attempting to unban **{identifier}** from Palworld...")
    response = await run_rcon_command_with_feedback(ctx, PAL_RCON_HOST, PAL_RCON_PORT, PAL_RCON_PASSWORD, f"UnBanPlayer {identifier}")
    
    if response:
        await ctx.send(f"🔨 Player **{identifier}** unbanned from Palworld.")


@bot.command(name='unban_asa', help="[ADMIN] Unbans a player from the ASA server (requires Steam ID/Player ID).")
@commands.has_permissions(administrator=True)
@is_admin_channel()
async def unban_asa(ctx, identifier: str):
    """Unbans a player from the ASA server using their Steam ID or Player ID."""
    await ctx.send(f"Attempting to unban **{identifier}** from ASA...")
    # ARK uses the RCON command 'UnBanPlayer <SteamIDOrPlayerID>'
    response = await run_rcon_command_with_feedback(ctx, ASA_RCON_HOST, ASA_RCON_PORT, ASA_RCON_PASSWORD, f"UnBanPlayer {identifier}")
    
    if response:
        await ctx.send(f"🔨 Player **{identifier}** unbanned from ASA.")


# ==============================================================================
# ERROR HANDLING
# ==============================================================================

@bot.event
async def on_command_error(ctx, error):
    """Global command error handler."""
    if isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors to avoid spamming the channel
        return
    
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ **Missing Argument!** You are missing required arguments for this command. Usage: `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
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
