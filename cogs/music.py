# SPDX-License-Identifier: CC-BY-NC-SA-4.0
# Author: Miriel (@mirielnet)

import asyncio
import re
import time
import traceback

import discord
import yt_dlp as youtube_dl
from discord import app_commands
from discord.ext import commands


FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 64k -analyzeduration 2147483647 -probesize 2147483647",
}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.duration = data.get("duration")
        self.start_time = time.time()
        self.seek_time = 0
        self.paused = False
        self.pause_start_time = 0

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        print(f"Fetching URL: {url}")
        loop = loop or asyncio.get_event_loop()
        ytdl = youtube_dl.YoutubeDL(
            {
                "format": "bestaudio/best",
                "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
                "restrictfilenames": True,
                "noplaylist": False,  # Allow playlists
                "nocheckcertificate": True,
                "ignoreerrors": False,
                "logtostderr": False,
                "quiet": True,
                "no_warnings": True,
                "default_search": "auto",
                "source_address": "0.0.0.0",
                "cookiefile": "./yt-cookie.txt",
            }
        )
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )

        if "entries" in data:
            entries = data["entries"]
            return [
                cls(discord.FFmpegPCMAudio(entry["url"], **FFMPEG_OPTIONS), data=entry)
                for entry in entries
            ]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        print(f"Filename: {filename}")
        return [cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)]

    def get_current_time(self):
        if self.paused:
            return self.seek_time
        return time.time() - self.start_time + self.seek_time

    def set_current_time(self, current_time):
        self.seek_time = current_time
        self.start_time = time.time()

    def pause(self):
        if not self.paused:
            self.paused = True
            self.pause_start_time = time.time()

    def resume(self):
        if self.paused:
            self.paused = False
            self.seek_time += time.time() - self.pause_start_time


class ControlView(discord.ui.View):
    def __init__(self, cog):
        self.cog = cog
        super().__init__()

    @discord.ui.button(label="⏯️ 再生/一時停止", style=discord.ButtonStyle.primary)
    async def play_pause(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if voice_client.is_playing():
            self.cog.current[interaction.guild.id].pause()
            voice_client.pause()
            await interaction.response.send_message(
                "音楽を一時停止しました。", ephemeral=True
            )
        else:
            voice_client.resume()
            self.cog.current[guild_id].resume()
            await interaction.response.send_message(
                "音楽を再生しました。", ephemeral=True
            )
            if guild_id in self.cog.progress_tasks:
                self.cog.progress_tasks[guild_id].cancel()
            self.cog.progress_tasks[guild_id] = interaction.client.loop.create_task(
                self.cog.update_progress_bar(interaction.guild)
            )

    @discord.ui.button(label="⏹️ 停止", style=discord.ButtonStyle.danger)
    async def stop(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        voice_client = interaction.guild.voice_client
        voice_client.stop()
        self.cog.queues[interaction.guild.id] = []  # キューをクリア
        self.cog.current[interaction.guild.id] = None
        await self.cog.update_queue_message(interaction)

    @discord.ui.button(label="🔊 切断", style=discord.ButtonStyle.danger)
    async def disconnect(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            "ボイスチャンネルから切断します。", ephemeral=True
        )
        await interaction.guild.voice_client.disconnect()


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Manage queues per guild
        self.current = {}  # Manage current song per guild
        self.requesters = {}  # Manage requesters per guild
        self.current_messages = {}  # Manage messages per guild
        self.progress_tasks = {}  # Manage progress tasks per guild

    async def play_next(self, interaction):
        guild_id = interaction.guild.id
        print(f"Playing next in queue for guild: {guild_id}")
        if self.queues[guild_id]:
            self.current[guild_id], self.requesters[guild_id] = self.queues[
                guild_id
            ].pop(0)
            self.current[guild_id].set_current_time(
                0
            )  # Reset the progress to 0 for new song
            print(f"Now playing: {self.current[guild_id].title}")

            def after_playing(error):
                if error:
                    print(f"Error in after_playing: {error}")
                coro = self.play_next(interaction)
                fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
                try:
                    fut.result()
                except Exception as e:
                    print(f"Error in after_playing coroutine: {e}")

            try:
                interaction.guild.voice_client.play(
                    self.current[guild_id], after=after_playing
                )
                await self.update_now_playing(interaction)
            except Exception as e:
                print(f"Error playing audio: {e}")
                await self.play_next(interaction)
        else:
            self.current[guild_id] = None
            await self.update_queue_message(interaction)
            print("Queue is empty, waiting for next command")

    async def update_now_playing(self, interaction):
        guild_id = interaction.guild.id
        if self.current[guild_id]:
            embed = discord.Embed(title="再生中")
            embed.add_field(
                name=self.current[guild_id].title,
                value=f"{self.requesters[guild_id].mention}",
                inline=False,
            )
            embed.add_field(
                name="再生時間",
                value=self.format_progress_bar(0, self.current[guild_id].duration),
                inline=False,
            )
            view = ControlView(self)
            message = await interaction.followup.send(embed=embed, view=view)
            self.current_messages[guild_id] = message
            if guild_id in self.progress_tasks:
                self.progress_tasks[guild_id].cancel()
            self.progress_tasks[guild_id] = self.bot.loop.create_task(
                self.update_progress_bar(interaction.guild)
            )

    async def update_progress_bar(self, guild: discord.Guild):
        while (
            guild.voice_client
            and (guild.voice_client.is_playing() or guild.voice_client.is_paused())
            and self.current_messages[guild.id]
        ):
            await asyncio.sleep(1)
            if self.current[guild.id]:
                current_time = self.current[guild.id].get_current_time()
                embed = discord.Embed(title="再生中")
                embed.add_field(
                    name=self.current[guild.id].title,
                    value=f"{self.requesters[guild.id].mention}",
                    inline=False,
                )
                embed.add_field(
                    name="再生時間",
                    value=self.format_progress_bar(
                        current_time, self.current[guild.id].duration
                    ),
                    inline=False,
                )
                view = ControlView(self)
                await self.current_messages[guild.id].edit(embed=embed, view=view)

    async def update_queue_message(self, interaction):
        guild_id = interaction.guild.id
        embed = discord.Embed(title="再生キュー")
        if self.current[guild_id]:
            embed.add_field(
                name="再生中",
                value=f"{self.current[guild_id].title} / {self.requesters[guild_id].mention}",
                inline=False,
            )
        if self.queues[guild_id]:
            for i, (player, requester) in enumerate(self.queues[guild_id]):
                embed.add_field(
                    name=f"#{i + 1}",
                    value=f"{player.title} / {requester.mention}",
                    inline=False,
                )
        else:
            embed.description = "再生キューは空です。"
        await interaction.followup.send(embed=embed)

    def format_progress_bar(self, current, total, length=20):
        filled_length = int(length * current // total)
        bar = "─" * filled_length + "●" + "─" * (length - filled_length)
        return f"{self.format_time(current)} {bar} {self.format_time(total)}"

    def format_time(self, seconds):
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02}:{int(seconds):02}"

    @app_commands.command(
        name="play", description="YouTubeまたはSoundCloudの音楽を再生します。"
    )
    async def play(
        self, interaction: discord.Interaction, url: str, channel: discord.VoiceChannel
    ):
        #ログに記録を残す
        guild_id = interaction.guild.id
        print(f"Received play command for guild: {guild_id}")
        
        #url引数がurlであるか確認
        #urlの正規表現を定義
        url_pattern = re.compile(
            r'^(https?):\/\/'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # ドメイン名
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
            r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'
            r'(?::\d+)?'
            r'(?:\/[^\s]*)?$', re.IGNORECASE)
        
        #条件のマッチを確認
        if re.match(url_pattern, url) is not None:
            await self._play(interaction, url, channel)
        else:
            await interaction.response.defer()
            #urlでないときは検索してSelectを送信
            with youtube_dl.YoutubeDL(
                {
                    "format": 'bestaudio',
                    "noplaylist": True,
                    "nocheckcertificate": True,
                    "ignoreerrors": False,
                    "logtostderr": False,
                    "quiet": True,
                    "no_warnings": True,
                    "cookiefile": "./yt-cookie.txt",
                }
            ) as ytdl:
                #検索結果を5件取得
                videos = ytdl.extract_info(
                    f"ytsearch5:{url}", download=False
                )['entries']
            #配列から必要な情報を抽出
            entries = [(entry['title'], f"https://www.youtube.com/watch?v={entry['id']}") for entry in videos]
            select = discord.ui.Select(
                placeholder="検索結果",
                options=[discord.SelectOption(label=title, description=url, value=url) for title, url in entries],
                custom_id="video-select"
            )

            view = discord.ui.View()
            view.add_item(select)

            #Select menuを送信
            await interaction.followup.send("どの曲を再生するか選んでください", view=view)

    async def _play(
        self, interaction: discord.Interaction, url: str, channel: discord.VoiceChannel
    ):
        guild_id = interaction.guild.id

        if not interaction.user.voice:
            await interaction.response.send_message(
                "音楽を再生するためにボイスチャンネルに接続してください。"
            )
            return

        await interaction.response.defer()

        if not interaction.guild.voice_client:
            await channel.connect()

        try:
            players = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
        except Exception as e:
            print(f"Error fetching URL: {e}")
            traceback.print_exc()
            await interaction.followup.send("無効なURLです。")
            return

        for player in players:
            if guild_id not in self.queues:
                self.queues[guild_id] = []
            self.queues[guild_id].append((player, interaction.user))
            if not self.current.get(guild_id):
                await self.play_next(interaction)

        await self.update_queue_message(interaction)

    @app_commands.command(name="skip", description="再生中の曲をスキップします。")
    async def skip(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        print(f"Received skip command for guild: {guild_id}")
        if (
            guild.voice_client is not None
            and interaction.guild.voice_client.is_playing()
        ):
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("スキップしました。")
        else:
            await interaction.response.send_message("スキップする曲がありません。")

    @app_commands.command(
        name="stop", description="再生を停止し、再生キューをクリアします。"
    )
    async def stop(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        print(f"Received stop command for guild: {guild_id}")
        if (
            interaction.guild.voice_client is not None
            and interaction.guild.voice_client.is_playing()
        ):
            interaction.guild.voice_client.stop()
            self.queues[guild_id] = []
            await interaction.response.send_message(
                "再生を停止し、再生キューをクリアしました。"
            )
        else:
            await interaction.response.send_message("停止する曲がありません。")

    @app_commands.command(name="queue", description="再生キューを表示します。")
    async def queue(self, interaction: discord.Interaction):
        print(f"Received queue command for guild: {interaction.guild.id}")
        await interaction.response.defer()
        await self.update_queue_message(interaction)

    @app_commands.command(name="pause", description="再生を一時停止します。")
    async def pause(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        print(f"Received pause command for guild: {guild_id}")
        if (
            interaction.guild.voice_client is not None
            and interaction.guild.voice_client.is_playing()
        ):
            interaction.guild.voice_client.pause()
            self.current[guild_id].pause()
            await interaction.response.send_message("再生を一時停止しました。")
        else:
            await interaction.response.send_message("一時停止する曲がありません。")

    @app_commands.command(name="resume", description="一時停止した再生を再開します。")
    async def resume(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        print(f"Received resume command for guild: {guild_id}")
        if (
            interaction.guild.voice_client is not None
            and interaction.guild.voice_client.is_paused()
        ):
            interaction.guild.voice_client.resume()
            self.current[guild_id].resume()
            await interaction.response.send_message("再生を再開しました。")
        else:
            await interaction.response.send_message("再開する曲がありません。")

    @app_commands.command(
        name="disconnect", description="ボイスチャンネルから切断します。"
    )
    async def disconnect(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        print(f"Received disconnect command for guild: {guild_id}")
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.disconnect()
            self.queues[guild_id] = []
            self.current[guild_id] = None
            await interaction.response.send_message(
                "ボイスチャンネルから切断しました。"
            )
        else:
            await interaction.response.send_message(
                "切断するボイスチャンネルがありません。"
            )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        print(f"Error in command {ctx.command}: {error}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        
        interaction.data.setdefault("custom_id", None)

        #検索のSelectの時
        if interaction.data["custom_id"] == "video-select":
            #選択された動画のurlを取得
            selected_url = interaction.data["values"][0]
            if not interaction.user.voice:
                await interaction.response.send_message(
                    "音楽を再生するためにボイスチャンネルに接続してください。"
                )
                return
            
            #urlが取得できた時は再生を行う
            await self._play(interaction, selected_url, interaction.user.voice.channel)



async def setup(bot):
    await bot.add_cog(Music(bot))
