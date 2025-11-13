# **🤖 Dual Server Discord Monitor (Palworld & Minecraft)**

This project provides a robust solution for running **two dedicated Discord bots simultaneously**: one to monitor your **Palworld** server and one to monitor your **Minecraft** server. This ensures stability and clean separation of logs and commands.

## **✨ 1\. Prerequisites**

Before starting, ensure you have the following:

1. **Python 3.8+** installed.  
2. **Discord Bot Token:** A single bot token can be used for both instances, but both bots must be added to your Discord server.  
3. **Discord Channel IDs:** You will likely need **two separate channel IDs**—one for Palworld logs (e.g., \#palworld-admin) and one for Minecraft logs (e.g., \#minecraft-admin).  
4. **Game Server RCON Access:**  
   * **Palworld:** The server must have RCON enabled (default port 25575).  
   * **Minecraft:** The server must have RCON enabled (default port 25575).  
5. **Required Python Libraries:**  
   pip install discord.py python-rcon

## **⚙️ 2\. Configuration (MANDATORY STEP)**

You must configure the dedicated files before running them. **Open each Python file and edit the CONFIGURATION block at the very top.**

### **A. Palworld Monitor (palworld\_monitor.py)**

Set the variables for your Palworld server and its dedicated Discord channel:

| Variable | Description | Example |
| :---- | :---- | :---- |
| DISCORD\_TOKEN | Your bot's authentication token. | "MY\_SECURE\_TOKEN\_XYZ" |
| TARGET\_CHANNEL\_ID | The Discord channel ID for Palworld logs. | 1234567890 |
| RCON\_HOST | IP or hostname of the Palworld server. | "192.168.1.10" |
| RCON\_PASSWORD | RCON admin password for Palworld. | "super-pal-secret" |

### **B. Minecraft Monitor (minecraft\_monitor.py)**

Set the variables for your Minecraft server and its dedicated Discord channel:

| Variable | Description | Example | |  
| :--- | :--- | :--- |  
| DISCORD\_TOKEN | Your bot's authentication token (can be the same as Palworld). | "MY\_SECURE\_TOKEN\_XYZ" |  
| TARGET\_CHANNEL\_ID| The Discord channel ID for Minecraft logs. | 9876543210 |  
| RCON\_HOST | IP or hostname of the Minecraft server. | "192.168.1.11" |  
| RCON\_PASSWORD | RCON admin password for Minecraft. | "super-mine-secret" |

## **🚀 3\. Execution**

Use the provided shell script, run\_dual\_monitors.sh, to launch both bots concurrently and ensure they continue running in the background.

1. **Make the script executable:**  
   chmod \+x run\_dual\_monitors.sh

2. **Launch both monitors:**  
   ./run\_dual\_monitors.sh

   This command starts the Palworld bot, places it in the background, and then starts the Minecraft bot.  
3. **Check the status:**  
   ps aux | grep monitor.py

4. **Stop the bots:** To stop both bots, you must manually find their process IDs (PIDs) using the command above and use the kill command for each process.

## **📝 4\. Bot Commands**

All commands are restricted to Discord users who have the **Administrator** permission in the server, ensuring only trusted users can execute critical server functions.

### **Palworld Commands (\!pal-)**

| Command | Action | Notes |
| :---- | :---- | :---- |
| \!pal-status | Displays current player count and server RCON status. |  |
| \!pal-players | Lists all players currently online, including their required Steam ID for kick/ban commands. |  |
| \!pal-broadcast \[message\] | Sends a global message to all players in-game. |  |
| \!pal-save | Forces the server to save the world immediately. |  |
| \!pal-shutdown | Forces the server to shut down (use this before stopping the hosting machine). |  |
| \!pal-kick \[SteamID\] | Kicks a player using their Steam ID (from \!pal-players). |  |
| \!pal-ban \[SteamID\] | Bans a player using their Steam ID (from \!pal-players). |  |
| \!pal-help | Displays this command list. |  |

### **Minecraft Commands (\!mine-)**

| Command | Action | Notes |
| :---- | :---- | :---- |
| \!mine-status | Displays current player count and server RCON status. |  |
| \!mine-players | Lists all players currently online (names only). |  |
| \!mine-say \[message\] | Sends a message to the in-game chat, prefixed by \[Discord Admin\]. |  |
| \!mine-save | Forces the server to save the world immediately (save-all). |  |
| \!mine-stop | Forces the server to shut down gracefully (stop). |  |
| \!mine-kick \[Name\] | Kicks a player using their exact in-game name. |  |
| \!mine-ban \[Name\] | Bans a player using their exact in-game name. |  |
| \!mine-help | Displays this command list. |  |

