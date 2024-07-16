import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import glob

# .envファイルからトークンを読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# インテントの設定
intents = discord.Intents.default()
intents.message_content = True

# ボットのインスタンスを作成
bot = commands.Bot(command_prefix='!', intents=intents)

# コマンドのロード
async def load_commands():
    for filename in glob.glob('./commands/*.py'):
        if filename.endswith('.py') and not filename.endswith('__init__.py'):
            try:
                await bot.load_extension(f'commands.{os.path.basename(filename)[:-3]}')
            except Exception as e:
                print(f'Failed to load extension {filename}: {e}')

# グローバルスラッシュコマンドの登録
@bot.event
async def on_ready():
    # コマンドの同期と登録
    await bot.tree.sync()
    
    # グローバルコマンドの登録確認メッセージ
    print("グローバルコマンドが正常に登録されました。")

    # サーバー数を取得してステータスを設定
    server_count = len(bot.guilds)
    activity = discord.Game(name=f'v0.1α / {server_count} servers')
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f'{bot.user}がDiscordに接続され、{server_count}サーバーに参加しています。')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandError):
        print(f'Error in command {ctx.command}: {error}')

# ボットの起動
async def main():
    async with bot:
        try:
            await load_commands()
            await bot.start(TOKEN)
        except Exception as e:
            print(f'Failed to start bot: {e}')

import asyncio
asyncio.run(main())