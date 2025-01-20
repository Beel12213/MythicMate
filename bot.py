import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import datetime

# Load environment variables from .env file
load_dotenv()

# Get the bot token from environment variables
TOKEN = os.getenv('BOT_TOKEN')

# Configure the bot with the necessary intents (permissions)
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Define the available dungeons and their abbreviations
# This dictionary maps full dungeon names to a list of their common abbreviations or shorthand names
dungeon_aliases = {
    "Ara-Kara, City of Echoes": ["ara", "city of echoes", "coe"],
    "City of Threads": ["threads", "city of threads", "cot"],
    "The Stonevault": ["stonevault", "vault"],
    "The Dawnbreaker": ["dawnbreaker", "breaker"],
    "Mists of Tirna Scithe": ["mists", "tirna", "scithe", "mots"],
    "The Necrotic Wake": ["nw", "necrotic wake", "necrotic"],
    "Siege of Boralus": ["siege", "boralus", "sob"],
    "Grim Batol": ["grim", "batol", "gb"]
}

# Function to translate user input to the full dungeon name
# This function takes user input and matches it to the correct full dungeon name
def translate_dungeon_name(user_input):
    user_input = user_input.lower()
    for full_name, aliases in dungeon_aliases.items():
        if user_input in aliases or user_input == full_name.lower():
            return full_name
    return None

# Function to formats a date string (YYYY-MM-DD) into a descriptive format
def format_descriptive_date(date_str: str) -> str:
    """
    Formats a date string (YYYY-MM-DD) into a descriptive format like
    'Monday, 20th of January of 2025'.

    Args:
        date_str (str): The input date string in the format 'YYYY-MM-DD'.

    Returns:
        str: The formatted descriptive date string.
    """
    # Parse the date string into a datetime object
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")

    # Determine the ordinal suffix for the day
    day = date_obj.day
    if 10 <= day % 100 <= 20:  # Handles 11th to 20th
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    # Format the date descriptively
    formatted_date = date_obj.strftime(f"%A, {day}{suffix} of %B of %Y")
    return formatted_date

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

# Define the /lfm slash command for looking for members for a Mythic+ run
@bot.tree.command(name="lfm", description="Start looking for members for a Mythic+ run.")
@app_commands.describe(
    schedule_date="Enter the desired day (YYYY-MM-DD).",
    schedule_time="Enter the desired time (HH:MM). ",
    dungeon="Enter the dungeon name or abbreviation",
    key_level="Enter the key level (e.g., +10)",
    role="Select your role in the group"
)
async def lfm(interaction: discord.Interaction, schedule_date: str, schedule_time: str, dungeon: str, key_level: str, role: str):

    # Validate the date and time inputs
    if schedule_date:
        try:
            datetime.datetime.strptime(schedule_date, "%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message(
                f"Invalid date format: '{schedule_date}'. Please use YYYY-MM-DD.",
                ephemeral=True
            )
            return

    if schedule_time:
        try:
            datetime.datetime.strptime(schedule_time, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                f"Invalid time format: '{schedule_time}'. Please use HH:MM.",
                ephemeral=True
            )
            return

    # Build the date and time string for the embed description
    date_time_str = ""
    if schedule_date or schedule_time:
        date_time_str = f"Scheduled for: {format_descriptive_date(schedule_date)} at {schedule_time}h"

    # Translate the dungeon name using the custom logic
    full_dungeon_name = translate_dungeon_name(dungeon)

    # If the dungeon name couldn't be recognized, send an error message
    if not full_dungeon_name:
        await interaction.response.send_message(f"Sorry, I couldn't recognize the dungeon name '{dungeon}'. Please try again with a valid name or abbreviation.", ephemeral=True)
        return

    # Send an initial message indicating that the group is being formed
    await interaction.response.send_message(f"Starting group for {full_dungeon_name} (Key: {key_level}) as {role}. Looking for members...", ephemeral=True)

    # Create an embed message to display the group information
    embed = discord.Embed(
        title=f"{date_time_str}\nDungeon: {full_dungeon_name}", # Include the full dungeon name in the title
        description=f"Difficulty: {key_level}",  # Display the difficulty (key level)
        color=discord.Color.blue()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url)

    # Set a thumbnail or image URL for the embed (use your own URL here)
    embed.set_thumbnail(url="https://example.com/path/to/your/image.png")

    # Initialize the members dictionary based on the role the user selected
    if role.lower() == "tank":
        members = {"Tank": interaction.user, "Healer": None, "DPS": []}
    elif role.lower() == "healer":
        members = {"Tank": None, "Healer": interaction.user, "DPS": []}
    elif role.lower() == "dps":
        members = {"Tank": None, "Healer": None, "DPS": [interaction.user]}
    else:
        members = {"Tank": None, "Healer": None, "DPS": []}

    # Initialize a dictionary to track which reactions correspond to which roles
    member_reactions = {"Tank": None, "Healer": None, "DPS": []}

    # Populate the embed with initial values for Tank, Healer, and DPS roles
    embed.add_field(name="🛡️", value=members["Tank"].mention if members["Tank"] else "None", inline=False)
    embed.add_field(name="💚", value=members["Healer"].mention if members["Healer"] else "None", inline=False)

    # Add one field for DPS with three descriptions underneath
    dps_value = "\n".join([dps_user.mention for dps_user in members["DPS"]] + ["None"] * (3 - len(members["DPS"])))
    embed.add_field(name="⚔️", value=dps_value, inline=False)

    # Send the embed message to the channel
    group_message = await interaction.followup.send(embed=embed)

    # Add reaction emojis for Tank, Healer, DPS, and Clear Role
    for emoji in role_emojis.values():
        await group_message.add_reaction(emoji)

    # Function to update the embed with the latest group information
    async def update_embed():
        # Update the embed fields with the current members
        embed.set_field_at(0, name="🛡️", value=members["Tank"].mention if members["Tank"] else "None", inline=False)
        embed.set_field_at(1, name="💚", value=members["Healer"].mention if members["Healer"] else "None", inline=False)

        # Update the DPS field with the current DPS members
        dps_value = "\n".join([dps_user.mention for dps_user in members["DPS"]] + ["None"] * (3 - len(members["DPS"])))
        embed.set_field_at(2, name="⚔️", value=dps_value, inline=False)

        try:
            # Try to edit the original embed message with the updated information
            await group_message.edit(embed=embed)
        except discord.errors.HTTPException as e:
            if e.status == 401:
                # If editing fails due to an invalid webhook token, recreate the message
                new_group_message = await interaction.followup.send(embed=embed)
                await group_message.delete()  # Delete the old message
                return new_group_message
            else:
                raise e

    # Function to check if a reaction is valid and relevant to the current group message
    def check_reaction(reaction, user):
        return user != bot.user and reaction.message.id == group_message.id

    # Event handler for when a user adds a reaction to the group message
    @bot.event
    async def on_reaction_add(reaction, user):
        if reaction.message.id != group_message.id or user == bot.user:
            return

        # Handle the "Clear Role" reaction to remove a user's role
        if str(reaction.emoji) == role_emojis["Clear Role"]:
            if user == members["Tank"]:
                members["Tank"] = None
            elif user == members["Healer"]:
                members["Healer"] = None
            elif user in members["DPS"]:
                members["DPS"].remove(user)

            # Remove the user's other role-related reactions
            for role, emoji in role_emojis.items():
                if emoji != role_emojis["Clear Role"]:
                    await group_message.remove_reaction(emoji, user)

            await update_embed()  # Update the embed with the cleared role
            await group_message.remove_reaction(reaction.emoji, user)
            return

        # Prevent users from selecting multiple roles
        if user in [members["Tank"], members["Healer"], *members["DPS"]]:
            await group_message.remove_reaction(reaction.emoji, user)
            await user.send("You can only select one role.")
            return

        # Assign the user to the selected role based on their reaction
        if str(reaction.emoji) == role_emojis["Tank"] and not members["Tank"]:
            members["Tank"] = user
            member_reactions["Tank"] = reaction

        elif str(reaction.emoji) == role_emojis["Healer"] and not members["Healer"]:
            members["Healer"] = user
            member_reactions["Healer"] = reaction

        elif str(reaction.emoji) == role_emojis["DPS"] and len(members["DPS"]) < 3:
            members["DPS"].append(user)
            member_reactions["DPS"].append(reaction)

        await update_embed()  # Update the embed with the new role assignments

        # If all roles are filled, add a "✅" reaction to indicate the group is ready
        if members["Tank"] and members["Healer"] and len(members["DPS"]) == 3:
            await group_message.add_reaction("✅")

    # Event handler for when a user removes a reaction from the group message
    @bot.event
    async def on_reaction_remove(reaction, user):
        if reaction.message.id != group_message.id or user == bot.user:
            return

        # Handle the removal of a reaction by clearing the user's role
        if str(reaction.emoji) == role_emojis["Tank"] and members["Tank"] == user:
            members["Tank"] = None

        elif str(reaction.emoji) == role_emojis["Healer"] and members["Healer"] == user:
            members["Healer"] = None

        elif str(reaction.emoji) == role_emojis["DPS"]:
            if user in members["DPS"]:
                members["DPS"].remove(user)

        await update_embed()  # Update the embed with the role removed

    # Function to check if all roles are filled and the group is complete
    def check_completion(reaction, user):
        return (
            reaction.message.id == group_message.id
            and str(reaction.emoji) == "✅"
            and user in [members["Tank"], members["Healer"], *members["DPS"]]
        )

    # Loop to wait for the "✅" reaction indicating the group is complete
    while True:
        reaction, user = await bot.wait_for('reaction_add', check=check_completion)

        if reaction.emoji == "✅" and user in [members["Tank"], members["Healer"], *members["DPS"]]:
            await group_message.delete()  # Delete the group message when the group is complete
            await interaction.followup.send(
                f"The group for {full_dungeon_name} has completed the dungeon. The message has been removed.",
                ephemeral=True
            )
            break
        else:
            await group_message.remove_reaction("✅", user)

# Run the bot with the token loaded from the environment variables
bot.run(TOKEN)
