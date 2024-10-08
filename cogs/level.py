# SPDX-License-Identifier: CC-BY-NC-SA-4.0
# Author: Miriel (@mirielnet)

import discord
from discord import app_commands
from discord.ext import commands
from core.connect import db  # Import the global db instance

def setup_db() -> None:
    create_users_table = """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT,
            server_id BIGINT,
            xp FLOAT DEFAULT 0,
            level INT DEFAULT 1,
            PRIMARY KEY (user_id, server_id)
        )
    """
    create_settings_table = """
        CREATE TABLE IF NOT EXISTS settings (
            server_id BIGINT PRIMARY KEY,
            level_enabled BOOLEAN DEFAULT FALSE,
            notify_channel_id BIGINT
        )
    """
    db.execute_query(create_users_table)
    db.execute_query(create_settings_table)

class LevelSystem(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def get_level(self, xp: float) -> int:
        return min(100, int(xp ** (1 / 2.5)))

    async def handle_error(self, interaction: discord.Interaction, error_message: str) -> None:
        embed = discord.Embed(title="エラー", description=error_message, color=0xFF0000)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def check_level_enabled(self, interaction: discord.Interaction) -> bool:
        server_id = interaction.guild.id
        query = "SELECT level_enabled FROM settings WHERE server_id = $1"
        result = await db.execute_query(query, (server_id,))
        if not result or not result[0]['level_enabled']:
            await self.handle_error(
                interaction,
                "レベル機能が無効になっています。サーバー管理者にお問い合わせください。",
            )
            return False
        return True

    @app_commands.command(name="level", description="あなたのレベルを表示します。")
    async def level(self, interaction: discord.Interaction) -> None:
        if not await self.check_level_enabled(interaction):
            return

        user_id = interaction.user.id
        server_id = interaction.guild.id

        try:
            query = "SELECT xp, level FROM users WHERE user_id = $1 AND server_id = $2"
            result = await db.execute_query(query, (user_id, server_id))

            if result:
                xp, level = result[0]['xp'], result[0]['level']
            else:
                xp, level = 0, 1

            embed = discord.Embed(
                title="レベル",
                description=f"{interaction.user.name}さんのレベル情報",
                color=0x00FF00,
            )
            embed.add_field(name="レベル", value=level)
            embed.add_field(name="XP", value=xp)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await self.handle_error(
                interaction, "レベル情報の取得中にエラーが発生しました。"
            )

    @app_commands.command(
        name="level-server", description="サーバーのレベルランキングを表示します。"
    )
    async def level_server(self, interaction: discord.Interaction) -> None:
        if not await self.check_level_enabled(interaction):
            return

        server_id = interaction.guild.id

        try:
            query = """
                SELECT user_id, level, xp FROM users 
                WHERE server_id = $1 
                ORDER BY level DESC, xp DESC 
                LIMIT 10
            """
            rankings = await db.execute_query(query, (server_id,))

            embed = discord.Embed(
                title="レベルランキング",
                description=f"{interaction.guild.name}のトップ10",
                color=0x00FF00,
            )

            for i, row in enumerate(rankings, 1):
                user_id = row['user_id']
                level = row['level']
                xp = row['xp']
                user = await self.bot.fetch_user(user_id)
                embed.add_field(
                    name=f"{i}. {user.name}",
                    value=f"レベル {level}, XP {xp}",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await self.handle_error(
                interaction, "レベルランキングの取得中にエラーが発生しました。"
            )

    @app_commands.command(
        name="level-settings", description="サーバーのレベル設定を行います。"
    )
    @app_commands.describe(enable="レベルシステムを有効化するかどうか")
    @app_commands.describe(notify_channel="レベルアップ通知チャンネル (オプション)")
    @commands.has_permissions(administrator=True)
    async def level_settings(
        self,
        interaction: discord.Interaction,
        enable: bool,
        notify_channel: discord.TextChannel = None,
    ) -> None:
        server_id = interaction.guild.id

        try:
            if not enable:
                delete_users_query = "DELETE FROM users WHERE server_id = $1"
                await db.execute_query(delete_users_query, (server_id,))

            replace_settings_query = """
                INSERT INTO settings (server_id, level_enabled, notify_channel_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (server_id) 
                DO UPDATE SET level_enabled = EXCLUDED.level_enabled, notify_channel_id = EXCLUDED.notify_channel_id
            """
            await db.execute_query(replace_settings_query, (
                server_id,
                enable,
                notify_channel.id if notify_channel else None,
            ))

            status = "有効" if enable else "無効"
            embed = discord.Embed(
                title="レベル設定",
                description=f"レベルシステムが{status}になりました。",
                color=0x00FF00,
            )
            if notify_channel:
                embed.add_field(name="通知チャンネル", value=notify_channel.mention)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await self.handle_error(interaction, "設定の更新中にエラーが発生しました。")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        server_id = message.guild.id
        user_id = message.author.id

        try:
            query = "SELECT level_enabled FROM settings WHERE server_id = $1"
            result = await db.execute_query(query, (server_id,))

            if not result or not result[0]['level_enabled']:
                return

            xp_gain = 0.5  # XPの増加量は任意で調整可能
            select_user_query = "SELECT xp, level FROM users WHERE user_id = $1 AND server_id = $2"
            result = await db.execute_query(select_user_query, (user_id, server_id))

            if result:
                xp, level = result[0]['xp'], result[0]['level']
                new_xp = xp + xp_gain
                new_level = self.get_level(new_xp)

                if new_level > level:
                    select_notify_channel_query = "SELECT notify_channel_id FROM settings WHERE server_id = $1"
                    channel_id = (await db.execute_query(select_notify_channel_query, (server_id,)))[0]['notify_channel_id']
                    if channel_id:
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            msg = f"{message.author.mention} レベルが{new_level}に上がりました！ おめでとうございます！"
                            await channel.send(msg)

                update_user_query = "UPDATE users SET xp = $1, level = $2 WHERE user_id = $3 AND server_id = $4"
                await db.execute_query(update_user_query, (new_xp, new_level, user_id, server_id))
            else:
                insert_user_query = "INSERT INTO users (user_id, server_id, xp, level) VALUES ($1, $2, $3, 1)"
                await db.execute_query(insert_user_query, (user_id, server_id, xp_gain))

        except Exception as e:
            print(f"XPの更新中にエラーが発生しました: {e}")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelSystem(bot))
