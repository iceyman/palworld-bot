# **🎮 Multi-Game Dedicated Server Monitor Bot**

This Python-based Discord bot provides unified monitoring and administrative control for both **Palworld** and **Minecraft** dedicated servers using RCON (Remote Console) protocol. It tracks real-time player joins/leaves, manages scheduled maintenance (like auto-saves), and maintains persistent player statistics.

## **✨ Features**

* **Unified Monitoring:** Manages RCON connections and monitors player status for both Palworld and Minecraft simultaneously from a single bot process.  
* **Real-Time Player Tracking:** Reports player joins and leaves directly to a specified Discord channel.  
* **Persistent Player Stats:** Tracks and records each player's **First Join** date and **Total Playtime** using a local player\_stats.json file.  
* **Scheduled Maintenance:** Runs automatic hourly commands to force a world save for both servers (save-all for MC, Save for Pal).  
* **RCON Health Checks:** Continuously verifies the RCON connection status and reports connectivity issues to a designated log channel.  
* **Administrative Commands:** Allows Discord users with the Administrator role to execute server-side commands (broadcasts, kicks, status checks).

## **🛠️ Setup and Installation**

### **Prerequisites**

1. **Python:** Python 3.8+ installed on your host machine.  
2. **Discord Bot Token:** A Discord application bot token.  
3. **Discord Channel IDs:** The ID of the primary announcement channel and a private log channel.  
4. **RCON Enabled:** Ensure RCON is enabled and configured correctly on both your **Palworld** and **Minecraft** dedicated servers (including unique passwords and ports).

### **Dependencies**

This project requires two external Python libraries: discord.py and python-rcon.

pip install discord.py python-rcon

## **⚙️ Configuration**

All configuration is handled in the top section of the multi\_game\_monitor.py file, or preferably, via environment variables.

| Variable | Description | Example Value |
| :---- | :---- | :---- |
| DISCORD\_TOKEN | Your Discord bot token. | Njk2NzE4.B31E92.zN8-p-h-Z\_E1O1S |
| TARGET\_CHANNEL\_ID | The Discord channel ID for join/leave notifications. | 123456789012345678 |
| LOG\_CHANNEL\_ID | The Discord channel ID for admin/error logging (can be the same as TARGET). | 123456789012345678 |
| MC\_RCON\_HOST | Minecraft server IP or hostname. | 127.0.0.1 |
| MC\_RCON\_PORT | Minecraft RCON port (default is often 25575). | 25575 |
| MC\_RCON\_PASSWORD | Minecraft RCON password. | my-secret-mc-pass |
| PAL\_RCON\_HOST | Palworld server IP or hostname. | 127.0.0.1 |
| PAL\_RCON\_PORT | Palworld RCON port (default is often 25575). | 25575 |
| PAL\_RCON\_PASSWORD | Palworld RCON password. | my-secret-pal-pass |

### **Running the Bot**

Once the configuration is set and dependencies are installed, run the script:

python multi\_game\_monitor.py

## **🖥️ Command Reference**

All commands start with the prefix \!server-. All administrative commands require the Discord user to have the **Administrator** permission.

### **🧱 Minecraft Commands (\!server-mine-)**

| Command | Arguments | Description |
| :---- | :---- | :---- |
| \!server-mine-status | None | Checks RCON health and current player count. |
| \!server-mine-players | None | Lists online players, session time, and total playtime. |
| \!server-mine-say | \<message\> | Sends a message to the in-game chat, prefixed by \[Discord Admin\]. |
| \!server-mine-save | None | Forces the world to save (save-all). |
| \!server-mine-kick | \<Name\> | Kicks a player using their exact in-game name. |
| \!server-mine-ban | \<Name\> | Bans a player using their exact in-game name. |

### **🎮 Palworld Commands (\!server-pal-)**

| Command | Arguments | Description |
| :---- | :---- | :---- |
| \!server-pal-status | None | Checks RCON health and current player count. |
| \!server-pal-players | None | Lists online players, session time, and total playtime. |
| \!server-pal-broadcast | \<message\> | Sends a server-wide broadcast message to all players. |
| \!server-pal-save | None | Forces the world to save (Save). |
| \!server-pal-kick | \<SteamID\> | Kicks a player using their **SteamID** (not name). |
| \!server-pal-shutdown | \<seconds\> \<message\> | Initiates server shutdown after a delay with a broadcast. |

