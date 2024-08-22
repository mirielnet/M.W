# SPDX-License-Identifier: CC-BY-NC-SA-4.0
# Author: Miriel (@mirielnet)

import discord
from discord import app_commands
from discord.ext import commands

class RolePanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message_id_role_map = {}  # メッセージIDとロールのマッピングを保存する辞書

    @app_commands.command(
        name="panel", description="指定されたロールパネルを作成します。"
    )
    @app_commands.describe(
        role1="ロール1を選択してください。",
        role2="ロール2を選択してください。",
        role3="ロール3を選択してください。",
        role4="ロール4を選択してください。",
        role5="ロール5を選択してください。",
        role6="ロール6を選択してください。",
        role7="ロール7を選択してください。",
        role8="ロール8を選択してください。",
        role9="ロール9を選択してください。",
        role10="ロール10を選択してください。",
        description="説明を入力してください。",
    )
    async def panel(
        self,
        interaction: discord.Interaction,
        role1: discord.Role = None,
        role2: discord.Role = None,
        role3: discord.Role = None,
        role4: discord.Role = None,
        role5: discord.Role = None,
        role6: discord.Role = None,
        role7: discord.Role = None,
        role8: discord.Role = None,
        role9: discord.Role = None,
        role10: discord.Role = None,
        description: str = None,
    ):
        await interaction.response.defer(ephemeral=True)

        roles = [role1, role2, role3, role4, role5, role6, role7, role8, role9, role10]
        roles = [role for role in roles if role is not None]
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        embed = discord.Embed(
            title="Role Panel",
            description=description or "リアクションを付けてロールを取得しましょう！",
        )
        for i, role in enumerate(roles):
            embed.add_field(name=f"Option {i+1}", value=role.mention, inline=False)

        # ここでembed付きメッセージを送信し、そのメッセージオブジェクトを取得する
        message = await interaction.channel.send(embed=embed)

        # メッセージIDとロールのマッピングを保存
        self.message_id_role_map[message.id] = {emoji: role.id for emoji, role in zip(emojis, roles)}

        # リアクションをメッセージに追加
        for emoji in emojis[: len(roles)]:
            await message.add_reaction(emoji)

        await interaction.followup.send("ロールパネルを作成しました。", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        if payload.message_id not in self.message_id_role_map:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        role_id = self.message_id_role_map[payload.message_id].get(str(payload.emoji))
        if role_id is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None:
            return

        await member.add_roles(role)
        channel = guild.get_channel(payload.channel_id)
        if channel:
            await channel.send(
                f"{member.mention} に {role.name} ロールが付与されました。",
                delete_after=10,
            )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        if payload.message_id not in self.message_id_role_map:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        role_id = self.message_id_role_map[payload.message_id].get(str(payload.emoji))
        if role_id is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None:
            return

        await member.remove_roles(role)
        channel = guild.get_channel(payload.channel_id)
        if channel:
            await channel.send(
                f"{member.mention} から {role.name} ロールが削除されました。",
                delete_after=10,
            )


async def setup(bot):
    await bot.add_cog(RolePanel(bot))
