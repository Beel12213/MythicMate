import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio
import pytz
import sqlite3
from sqlite3 import Error

# Load environment variables from .env file
load_dotenv()

# Get the bot token from environment variables
TOKEN = os.getenv('BOT_TOKEN')

# At the start, after load_dotenv()
print(f"Token loaded from environment: {'Yes' if TOKEN else 'No'}")
print(f"Token length: {len(TOKEN) if TOKEN else 0}")

# Configure the bot with the necessary intents (permissions)
intents = discord.Intents.default()
intents.reactions = True
intents.guilds = True

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Define the available dungeons and their abbreviations
# This dictionary maps full dungeon names to a list of their common abbreviations or shorthand names
dungeon_aliases = {
    "Ara-Kara, City of Echoes": ["ara", "city of echoes", "coe", "arakara", "ak"],
    "City of Threads": ["threads", "city of threads", "cot"],
    "The Stonevault": ["stonevault", "vault", "sv"],
    "The Dawnbreaker": ["dawnbreaker", "breaker", "db", "dawn"],
    "Mists of Tirna Scithe": ["mists", "tirna", "scithe", "mots", "tirna schithe"],
    "The Necrotic Wake": ["nw", "necrotic wake", "necrotic", "the necrotic wake"],
    "Siege of Boralus": ["siege", "boralus", "sob", "siege of boralus"],
    "Grim Batol": ["grim", "batol", "gb"],
    "Operation: Floodgate": ["flood", "floodgate", "of", "operation", "operation floodgate"],
    "Cinderbrew Meadery": ["cinder", "meadery", "brew", "cm", "cinderbrew"],
    "Darkflame Cleft": ["dark", "flame", "cleft", "dc", "darkflame"],
    "The Rookery": ["rook", "rookery", "tr"],
    "Priory of the Sacred Flame": ["priory", "sacred", "flame", "psf"],
    "The MOTHERLODE!!": ["ml", "mother", "motherlode"],
    "Theater of Pain": ["top", "theater", "pain", "tp"],
    "Operation: Mechagon: Workshop": ["workshop", "mech", "omw", "mechagon"],
    "Other": ["other"]
}

# Convert to a more efficient structure using sets for O(1) lookup
dungeon_lookup = {}
for full_name, aliases in dungeon_aliases.items():
    for alias in aliases + [full_name.lower()]:
        dungeon_lookup[alias] = full_name

def translate_dungeon_name(user_input):
    return dungeon_lookup.get(user_input.lower())

# Define the roles for Tank, Healer, and DPS using emoji symbols
role_emojis = {
    "Tank": "🛡️",
    "Healer": "💚",
    "DPS": "⚔️",
    "Clear Role": "❌"  # This emoji is used to allow users to clear their selected role
}

# Event handler for when the bot is ready and connected to Discord
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()  # Synchronize the command tree with Discord
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# Global dictionary to store active groups
active_groups = {}

async def update_group_embed(message, embed, group_state):
    """
    Updates the embed message with current group composition and backup information.
    
    Args:
        message: The Discord message to update
        embed: The embed object to modify
        group_state: Current state of the group including members and backups
    """
    if not message or not embed or not group_state:
        print("Missing required parameters for update_group_embed")
        return
        
    try:
        embed.clear_fields()
        
        # Display main role assignments
        embed.add_field(
            name="🛡️ Tank",
            value=group_state.members["Tank"].mention if group_state.members["Tank"] else "None",
            inline=False
        )
        embed.add_field(
            name="💚 Healer",
            value=group_state.members["Healer"].mention if group_state.members["Healer"] else "None",
            inline=False
        )
        
        # Display DPS slots (filled or empty)
        dps_value = "\n".join([dps_user.mention for dps_user in group_state.members["DPS"]] + ["None"] * (3 - len(group_state.members["DPS"])))
        embed.add_field(name="⚔️ DPS", value=dps_value, inline=False)
        
        # Display backup players for each role
        backup_text = ""
        for role, backups in group_state.backups.items():
            if backups:
                backup_text += f"\n**{role}**: " + ", ".join(backup.mention for backup in backups)
        
        if backup_text:
            embed.add_field(name="📋 Backups", value=backup_text.strip(), inline=False)

        # Changed to use fetch_message and edit
        try:
            # Fetch a fresh message object before editing
            current_message = await message.channel.fetch_message(message.id)
            await current_message.edit(embed=embed)
        except discord.NotFound:
            print("Message not found - it may have been deleted")
        except discord.Forbidden:
            print("Bot doesn't have permission to edit the message")
        except Exception as e:
            print(f"Error updating message: {e}")

    except Exception as e:
        print(f"Error in update_group_embed: {e}")

@bot.tree.command(name="lfm", description="Start looking for members for a Mythic+ run.")
@app_commands.describe(
    dungeon="Enter the dungeon name, abbreviation or Other",
    key_level="Enter the key level (e.g., +10)",
    role="Select your role in the group (Tank, Dps, Healer)",
    schedule="When to run (e.g., 'now' or 'YYYY-MM-DD HH:MM' in server time)"
)
async def lfm(interaction: discord.Interaction, dungeon: str, key_level: str, role: str, schedule: str):
    """
    Creates a new Mythic+ group and manages signups through reactions.
    
    Args:
        interaction: The Discord interaction context
        dungeon: Name or abbreviation of the dungeon
        key_level: Difficulty level of the key
        role: Initial role of the group creator
        schedule: When the group will start
    """
    print("Starting LFM command...")
    
    # Validate dungeon name
    full_dungeon_name = translate_dungeon_name(dungeon)
    if not full_dungeon_name:
        await interaction.response.send_message(
            f"Sorry, I couldn't recognize the dungeon name '{dungeon}'. Please try again with a valid name or abbreviation.",
            ephemeral=True
        )
        return

    # Handle scheduling
    schedule_time = None
    if schedule.lower() != "now":
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p"]  # 24h and 12h formats

        for fmt in formats:
            try:
                schedule_time = datetime.strptime(schedule, fmt)
                schedule_time = pytz.UTC.localize(schedule_time)

                # Ensure scheduled time is in the future
                if schedule_time <= datetime.now(pytz.UTC):
                    await interaction.response.send_message(
                        "The scheduled time must be in the future.",
                        ephemeral=True
                    )
                    return
                break  # exit the loop if time is parsed successfully
            except ValueError:
                continue  # try the next format if the current one fails

        if schedule_time is None:  # if none of the formats worked
            await interaction.response.send_message(
                "Invalid date/time format. Please use 'now' or 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM AM/PM'.",
                ephemeral=True
            )
            return
    else:
        schedule_time = datetime.now(pytz.UTC)

    # Format schedule string and send initial response
    schedule_str = "now" if schedule.lower() == "now" else schedule_time.strftime("%Y-%m-%d %H:%M")
    await interaction.response.defer()

    # Initialize group state and create embed
    group_state = GroupState(interaction, role, schedule_time)
    embed = discord.Embed(
        title=f"Dungeon: {full_dungeon_name}",
        description=f"Difficulty: {key_level}\nScheduled: {schedule_str}",
        color=discord.Color.blue()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url)
    embed.set_thumbnail(url="https://example.com/path/to/your/image.png")

    # Create and store group message - Changed to use channel.send instead of interaction.followup
    group_message = await interaction.channel.send(embed=embed)
    active_groups[group_message.id] = {
        "state": group_state,
        "embed": embed,
        "message": group_message,
        "dungeon": full_dungeon_name,
        "key_level": key_level
    }

    # Update embed with initial group composition
    await update_group_embed(group_message, embed, group_state)

    # Add role selection reactions
    for emoji in role_emojis.values():
        await group_message.add_reaction(emoji)

    # Set up reminder if scheduled for later
    if schedule_time:
        group_state.reminder_task = asyncio.create_task(
            group_state.send_reminder(interaction.channel)
        )

@bot.event
async def on_reaction_add(reaction, user):
    """
    Handles when users add reactions to join or leave the group.
    
    Args:
        reaction: The reaction emoji added
        user: The user who added the reaction
    """
    if user == bot.user:
        return

    group_info = active_groups.get(reaction.message.id)
    if not group_info:
        return

    group_state = group_info["state"]
    group_message = group_info["message"]
    embed = group_info["embed"]

    # Handle role clearing
    if str(reaction.emoji) == role_emojis["Clear Role"]:
        role, promoted_user = group_state.remove_user(user)
        if promoted_user:
            await group_message.channel.send(
                f"{promoted_user.mention} has been promoted from backup to {role}!",
                delete_after=10
            )
        # Remove all role reactions from the user
        for role_name, emoji in role_emojis.items():
            if emoji != role_emojis["Clear Role"]:
                await group_message.remove_reaction(emoji, user)
        await update_group_embed(group_message, embed, group_state)
        await group_message.remove_reaction(reaction.emoji, user)
        return

    # Prevent users from selecting multiple roles
    current_role = group_state.get_user_role(user)
    if current_role:
        await group_message.remove_reaction(reaction.emoji, user)
        await user.send("You can only select one role. Please remove your current role first.")
        return

    # Handle role selection
    role_added = False
    if str(reaction.emoji) == role_emojis["Tank"]:
        role_added = group_state.add_member("Tank", user)
    elif str(reaction.emoji) == role_emojis["Healer"]:
        role_added = group_state.add_member("Healer", user)
    elif str(reaction.emoji) == role_emojis["DPS"]:
        role_added = group_state.add_member("DPS", user)

    # Notify user if added to backup
    if not role_added:
        await user.send("You've been added to the backup list for this role.")

    await update_group_embed(group_message, embed, group_state)

    # Add completion marker if group is full
    if group_state.is_complete():
        await group_message.add_reaction("✅")

@bot.event
async def on_reaction_remove(reaction, user):
    """
    Handles when users remove their role reactions.
    
    Args:
        reaction: The reaction emoji removed
        user: The user who removed the reaction
    """
    if user == bot.user:
        return

    group_info = active_groups.get(reaction.message.id)
    if not group_info:
        return

    group_state = group_info["state"]
    group_message = group_info["message"]
    embed = group_info["embed"]

    # Remove user from their role
    if str(reaction.emoji) == role_emojis["Tank"] and group_state.members["Tank"] == user:
        group_state.members["Tank"] = None
    elif str(reaction.emoji) == role_emojis["Healer"] and group_state.members["Healer"] == user:
        group_state.members["Healer"] = None
    elif str(reaction.emoji) == role_emojis["DPS"] and user in group_state.members["DPS"]:
        group_state.members["DPS"].remove(user)

    await update_group_embed(group_message, embed, group_state)

class GroupState:
    """
    Manages the state of a Mythic+ group including members, backups, and reminders.
    
    Attributes:
        members: Dictionary containing current group members by role
        backups: Dictionary containing backup players by role
        reminder_task: Optional asyncio task for scheduled groups
    """
    def __init__(self, interaction, initial_role, schedule_time=None):
        """
        Initializes a new group state.
        
        Args:
            interaction: Discord interaction that created the group
            initial_role: Starting role of the group creator
            schedule_time: Optional datetime for scheduled groups
        """
        self.members = {
            "Tank": None,
            "Healer": None,
            "DPS": []
        }
        self.backups = {
            "Tank": [],
            "Healer": [],
            "DPS": []
        }
        self.reminder_task = None
        self.schedule_time = schedule_time
        
        # Add the command user to their selected role
        user = interaction.user
        self.add_member(initial_role, user)

    def add_member(self, role, user):
        """
        Adds a user to a role, or to backup if role is full.
        
        Args:
            role: The role to add the user to
            user: The Discord user to add
            
        Returns:
            bool: True if added to main role, False if added to backup
        """
        if role == "Tank":
            if not self.members["Tank"]:
                self.members["Tank"] = user
                return True
            else:
                self.backups["Tank"].append(user)
                return False
        elif role == "Healer":
            if not self.members["Healer"]:
                self.members["Healer"] = user
                return True
            else:
                self.backups["Healer"].append(user)
                return False
        elif role == "DPS":
            if len(self.members["DPS"]) < 3:
                self.members["DPS"].append(user)
                return True
            else:
                self.backups["DPS"].append(user)
                return False
        return False

    def remove_user(self, user):
        """
        Removes a user from their role and promotes a backup if available.
        
        Args:
            user: The Discord user to remove
            
        Returns:
            tuple: (role_removed_from, promoted_user) or (None, None) if user not found
        """
        # Check main roles first
        if self.members["Tank"] == user:
            self.members["Tank"] = None
            if self.backups["Tank"]:
                promoted_user = self.backups["Tank"].pop(0)
                self.members["Tank"] = promoted_user
                return "Tank", promoted_user
            return "Tank", None

        if self.members["Healer"] == user:
            self.members["Healer"] = None
            if self.backups["Healer"]:
                promoted_user = self.backups["Healer"].pop(0)
                self.members["Healer"] = promoted_user
                return "Healer", promoted_user
            return "Healer", None

        if user in self.members["DPS"]:
            self.members["DPS"].remove(user)
            if self.backups["DPS"]:
                promoted_user = self.backups["DPS"].pop(0)
                self.members["DPS"].append(promoted_user)
                return "DPS", promoted_user
            return "DPS", None

        # Check backups
        for role in ["Tank", "Healer", "DPS"]:
            if user in self.backups[role]:
                self.backups[role].remove(user)
                return role, None

        return None, None

    def get_user_role(self, user):
        """
        Gets the current role of a user in the group.
        
        Args:
            user: The Discord user to check
            
        Returns:
            str: The user's role or None if not in group
        """
        if self.members["Tank"] == user:
            return "Tank"
        if self.members["Healer"] == user:
            return "Healer"
        if user in self.members["DPS"]:
            return "DPS"
        
        # Check backups
        for role, backups in self.backups.items():
            if user in backups:
                return f"Backup {role}"
        return None

    def is_complete(self):
        """
        Checks if the group has all required roles filled.
        
        Returns:
            bool: True if group is complete, False otherwise
        """
        return (
            self.members["Tank"] is not None and
            self.members["Healer"] is not None and
            len(self.members["DPS"]) == 3
        )

    async def send_reminder(self, channel):
        """
        Sends reminders to group members before scheduled start time.
        
        Args:
            channel: The Discord channel to send fallback messages to
        """
        if not self.reminder_task:
            return

        try:
            # Wait until 15 minutes before scheduled time
            await asyncio.sleep(max(0, (self.schedule_time - datetime.now(pytz.UTC)).total_seconds() - 900))
            
            # Send DMs to all members
            all_members = [
                self.members["Tank"],
                self.members["Healer"],
                *self.members["DPS"]
            ]
            
            for member in all_members:
                if member:
                    try:
                        await member.send(f"Reminder: Your M+ run starts in 15 minutes!")
                    except discord.Forbidden:
                        await channel.send(
                            f"{member.mention} (Could not send DM: Your M+ run starts in 15 minutes!)",
                            delete_after=60
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error in reminder task: {e}")

def create_connection():
    try:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        conn = sqlite3.connect('data/mythicmate.db')
        return conn
    except Error as e:
        print(f"Error connecting to database: {e}")
        return None

# Modify the stats command to include server_id
@bot.tree.command(name="mystats", description="View your M+ statistics")
@app_commands.guild_only()
async def mystats(interaction: discord.Interaction):
    conn = create_connection()
    if conn is None:
        await interaction.response.send_message("Unable to access statistics at this time.", ephemeral=True)
        return

    try:
        c = conn.cursor()
        
        # Ensure server is registered
        c.execute('''
            INSERT OR IGNORE INTO servers (server_id, server_name)
            VALUES (?, ?)
        ''', (str(interaction.guild_id), interaction.guild.name))
        
        # Get total runs for this server
        c.execute('''
            SELECT COUNT(*), role 
            FROM participants 
            WHERE user_id = ? AND server_id = ?
            GROUP BY role
        ''', (str(interaction.user.id), str(interaction.guild_id)))
        role_counts = c.fetchall()
        
        # Get average key level for this server
        c.execute('''
            SELECT AVG(r.key_level) 
            FROM runs r 
            JOIN participants p ON r.run_id = p.run_id 
            WHERE p.user_id = ? AND p.server_id = ?
        ''', (str(interaction.user.id), str(interaction.guild_id)))
        avg_key = c.fetchone()[0]
        
        # Create stats embed
        embed = discord.Embed(
            title=f"M+ Statistics for {interaction.user.display_name}",
            description=f"Server: {interaction.guild.name}",
            color=discord.Color.blue()
        )
        
        # ... rest of embed creation ...

    except Error as e:
        await interaction.response.send_message(f"Error retrieving statistics: {e}", ephemeral=True)
    finally:
        conn.close()

@bot.tree.command(name="leaderboard", description="View M+ leaderboards")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction, category: str, timeframe: str):
    conn = create_connection()
    if conn is None:
        await interaction.response.send_message("Unable to access leaderboard at this time.", ephemeral=True)
        return

    try:
        c = conn.cursor()
        
        # Build time constraint
        time_constraint = ""
        if timeframe == "month":
            time_constraint = "AND r.completion_time >= date('now', 'start of month')"
        elif timeframe == "week":
            time_constraint = "AND r.completion_time >= date('now', '-6 days')"
        
        if category == "runs":
            query = f'''
                SELECT p.user_id, COUNT(*) as run_count 
                FROM participants p 
                JOIN runs r ON p.run_id = r.run_id 
                WHERE r.completion_time IS NOT NULL 
                AND p.server_id = ? {time_constraint}
                GROUP BY p.user_id 
                ORDER BY run_count DESC 
                LIMIT 10
            '''
        elif category == "keys":
            query = f'''
                SELECT p.user_id, MAX(r.key_level) as max_key 
                FROM participants p 
                JOIN runs r ON p.run_id = r.run_id 
                WHERE r.completion_time IS NOT NULL 
                AND p.server_id = ? {time_constraint}
                GROUP BY p.user_id 
                ORDER BY max_key DESC 
                LIMIT 10
            '''
        
        c.execute(query, (str(interaction.guild_id),))
        results = c.fetchall()
        
        # Create leaderboard embed
        embed = discord.Embed(
            title=f"M+ Leaderboard - {category.title()}",
            description=f"Server: {interaction.guild.name}\nTimeframe: {timeframe.title()}",
            color=discord.Color.gold()
        )
        
        # ... rest of embed creation ...

    except Error as e:
        await interaction.response.send_message(f"Error retrieving leaderboard: {e}", ephemeral=True)
    finally:
        conn.close()

async def record_completed_run(group_state, dungeon_name, key_level, guild_id, guild_name):
    conn = create_connection()
    if conn is None:
        return
    
    try:
        c = conn.cursor()
        
        # Ensure server is registered
        c.execute('''
            INSERT OR IGNORE INTO servers (server_id, server_name)
            VALUES (?, ?)
        ''', (str(guild_id), guild_name))
        
        # Insert run record
        c.execute('''
            INSERT INTO runs (server_id, dungeon_name, key_level, completion_time)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (str(guild_id), dungeon_name, int(key_level.strip('+'))))
        run_id = c.lastrowid
        
        # Record participants
        if group_state.members["Tank"]:
            c.execute('''
                INSERT INTO participants (run_id, server_id, user_id, role)
                VALUES (?, ?, ?, ?)
            ''', (run_id, str(guild_id), str(group_state.members["Tank"].id), "Tank"))
            
        if group_state.members["Healer"]:
            c.execute('''
                INSERT INTO participants (run_id, server_id, user_id, role)
                VALUES (?, ?, ?, ?)
            ''', (run_id, str(guild_id), str(group_state.members["Healer"].id), "Healer"))
            
        for dps in group_state.members["DPS"]:
            if dps:
                c.execute('''
                    INSERT INTO participants (run_id, server_id, user_id, role)
                    VALUES (?, ?, ?, ?)
                ''', (run_id, str(guild_id), str(dps.id), "DPS"))
        
        conn.commit()
    except Error as e:
        print(f"Error recording run: {e}")
    finally:
        conn.close()

# Run the bot with the token loaded from the environment variables
bot.run(TOKEN)
