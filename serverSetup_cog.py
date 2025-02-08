import nextcord
from nextcord.ext import commands
from nextcord.ui import Button, View
import sqlite3
import os

class ServerSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_in_progress = False
        self.verified_role_name = None  # Instance variable to store the verified role name

    def admin_only():
        async def predicate(ctx):
            return ctx.author.guild_permissions.administrator
        return commands.check(predicate)

    @commands.command(name="setup_server")
    @admin_only()
    async def setup_server(self, ctx):
        if self.setup_in_progress:
            await ctx.send("A setup process is already in progress. Please wait for it to complete.")
            return
        
        self.setup_in_progress = True

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Step 1: Collect all setup information

        # Ask for the name of the Verified role
        await ctx.send("Enter the name of the Verified role:")
        verified_role_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
        self.verified_role_name = verified_role_msg.content

        # Ask for the name of the Admin role
        await ctx.send("Enter the name for the Admin role (this role will have full administrator rights):")
        admin_role_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
        admin_role_name = admin_role_msg.content

        # Ask for the name of the Team role
        await ctx.send("Enter the name for the Team role (this role will have moderator abilities):")
        team_role_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
        team_role_name = team_role_msg.content

        # Ask for number of additional categories
        await ctx.send("How many additional categories do you want to create?")
        num_categories_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
        num_categories = int(num_categories_msg.content)

        categories = []
        for i in range(num_categories):
            await ctx.send(f"Enter the name for category {i+1}:")
            cat_name_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
            cat_name = cat_name_msg.content

            channels = ["announcements"] if i == 0 else []

            await ctx.send(f"How many additional channels do you want in the '{cat_name}' category?")
            num_channels_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
            num_channels = int(num_channels_msg.content)

            for j in range(num_channels):
                await ctx.send(f"Enter the name for channel {j+1} in '{cat_name}' category:")
                channel_name_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
                channels.append(channel_name_msg.content)
            
            categories.append({"name": cat_name, "channels": channels})

        # Ask for additional roles
        await ctx.send("How many additional roles do you want to create?")
        num_roles_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
        num_roles = int(num_roles_msg.content)

        roles = [self.verified_role_name]
        for i in range(num_roles):
            await ctx.send(f"Enter the name for role {i+1}:")
            role_name_msg = await self.bot.wait_for("message", check=check, timeout=300.0)
            roles.append(role_name_msg.content)

        # Step 2: Create roles, categories, and channels after all information is gathered

        role_objects = {}

        # Create roles
        admin_role = await ctx.guild.create_role(name=admin_role_name, permissions=nextcord.Permissions(administrator=True))
        role_objects[admin_role_name] = admin_role

        team_permissions = nextcord.Permissions(
            manage_channels=True,
            kick_members=True,
            ban_members=True,
            manage_messages=True,
            mute_members=True,
            deafen_members=True,
            move_members=True,
            moderate_members=True
        )
        team_role = await ctx.guild.create_role(name=team_role_name, permissions=team_permissions)
        role_objects[team_role_name] = team_role

        for role_name in roles:
            role = await ctx.guild.create_role(name=role_name)
            role_objects[role_name] = role

        # Create Welcome category and verify channel
        welcome_category = await ctx.guild.create_category("Welcome")
        verify_channel = await welcome_category.create_text_channel("verify", overwrites={
            ctx.guild.default_role: nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
            role_objects[self.verified_role_name]: nextcord.PermissionOverwrite(read_messages=False),
        })

        # Create additional categories and channels
        for category in categories:
            cat = await ctx.guild.create_category(category["name"])
            for channel_name in category["channels"]:
                await cat.create_text_channel(channel_name, overwrites={
                    ctx.guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                    role_objects[self.verified_role_name]: nextcord.PermissionOverwrite(read_messages=True),
                })

        # Create Admin category and channels
        admin_category = await ctx.guild.create_category("Admin")
        admin_channels = ["admin-commands", "admin-chat", "admin-announcements", "admin-logs"]
        for channel_name in admin_channels:
            await admin_category.create_text_channel(channel_name, overwrites={
                ctx.guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                role_objects[admin_role_name]: nextcord.PermissionOverwrite(read_messages=True),
                role_objects[team_role_name]: nextcord.PermissionOverwrite(read_messages=True),
                ctx.guild.me: nextcord.PermissionOverwrite(read_messages=True),
            })

        # Create the storage thread
        storage_parent_channel = await admin_category.create_text_channel("admin-storage", overwrites={
            ctx.guild.default_role: nextcord.PermissionOverwrite(read_messages=False, send_messages=False),
            role_objects[admin_role_name]: nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
        })
        storage_thread = await storage_parent_channel.create_thread(
            name="storage",
            type=nextcord.ChannelType.public_thread,
            auto_archive_duration=1440
        )

        # Create Tickets category and ticket channel
        ticket_category = await ctx.guild.create_category("Tickets")
        ticket_channel = await ticket_category.create_text_channel("create-ticket", overwrites={
            ctx.guild.default_role: nextcord.PermissionOverwrite(read_messages=True),
            role_objects[self.verified_role_name]: nextcord.PermissionOverwrite(read_messages=True),
        })

        ticket_ctx = await self.bot.get_context(await ticket_channel.send('Setting up tickets...'))
        await self.bot.get_command("ticket").invoke(ticket_ctx)

        # Send the verification message to the verify channel
        await self.send_verification_message(verify_channel)

        # Check or create the database
        self.check_or_create_database()

        await ctx.send("Server setup is complete!")
        self.setup_in_progress = False

    
    async def send_verification_message(self, channel):
        view = View()

        leave_button = Button(label="Leave", style=nextcord.ButtonStyle.danger)
        verify_button = Button(label="Verify", style=nextcord.ButtonStyle.success)

        async def leave_callback(interaction):
            await interaction.user.kick(reason="Left through verification process")
            await interaction.send("You have left the server.", ephemeral=True)

        async def verify_callback(interaction):
            role = nextcord.utils.get(interaction.guild.roles, name=self.verified_role_name)
            if role:
                await interaction.user.add_roles(role)
                await interaction.send("You have been verified!", ephemeral=True)
            else:
                await interaction.send("Verification failed. Role not found.", ephemeral=True)

        leave_button.callback = leave_callback
        verify_button.callback = verify_callback

        view.add_item(leave_button)
        view.add_item(verify_button)

        await channel.send("Welcome! Please verify to gain access to the server.", view=view)

    def check_or_create_database(self):
        # Check if the database exists, if not, create it
        conn = sqlite3.connect("database1.db")
        c = conn.cursor()

        # Check if the 'users' table exists
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    discord_username TEXT,
                    x_profile_url TEXT,
                    wallet_address TEXT,
                    tokens INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    rank TEXT,
                    inventory TEXT,
                    dao_member BOOLEAN DEFAULT 0,
                    profile_picture TEXT  -- Add this line
                    )''')

        # Check if 'profile_picture' column exists; if not, add it
        c.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in c.fetchall()]
        if "profile_picture" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")

        conn.commit()
        conn.close()


    @commands.command(name="disable_setup")
    @admin_only()
    async def disable_setup(self, ctx):
        if not self.setup_in_progress:
            await ctx.send("No setup process is currently in progress.")
            return
        
        self.setup_in_progress = False
        await ctx.send("Setup process has been cancelled.")

    @commands.command(name="nuke")
    @admin_only()
    async def delete_all_channels_and_roles(self, ctx):
        # Channel ID to keep
        channel_to_keep_id = 1252370390047527022

        # Delete all channels except the one with the given ID
        for channel in ctx.guild.channels:
            if channel.id != channel_to_keep_id:
                try:
                    await channel.delete()
                except nextcord.Forbidden:
                    await ctx.send(f"Missing permissions to delete channel: {channel.name}")
                except Exception as e:
                    await ctx.send(f"An error occurred while deleting channel {channel.name}: {str(e)}")

        # Delete all roles except the @everyone role
        for role in ctx.guild.roles:
            if role != ctx.guild.default_role:
                try:
                    await role.delete()
                except nextcord.Forbidden:
                    await ctx.send(f"Missing permissions to delete role: {role.name}")
                except Exception as e:
                    await ctx.send(f"An error occurred while deleting role {role.name}: {str(e)}")

        await ctx.send("All channels and roles (except the specified ones) have been deleted.")

def setup(bot):
    bot.add_cog(ServerSetup(bot))
