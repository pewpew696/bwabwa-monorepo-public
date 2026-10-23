# cogs/ping.py
import time
import discord
from discord import app_commands
from discord.ext import commands


class PingCog(commands.Cog):
    """ngukur latency bot"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping_prefix(self, ctx: commands.Context):
        start = time.monotonic()
        gateway_latency = self.bot.latency * 1000

        msg = await ctx.send(f"🏓 Pong! Gateway: `{gateway_latency:.2f}ms`")
        total = (time.monotonic() - start) * 1000

        await msg.edit(
            content=f"🏓 Pong!\nGateway latency: `{gateway_latency:.2f}ms`\nRound-trip: `{total:.2f}ms`"
        )
        print(f"[PING] gateway={gateway_latency:.2f}ms | total={total:.2f}ms")

    @app_commands.command(name="ping", description="Cek response time bot")
    async def ping_slash(self, interaction: discord.Interaction):
        start = time.monotonic()
        gateway_latency = self.bot.latency * 1000

        await interaction.response.defer()
        defer_ms = (time.monotonic() - start) * 1000

        await interaction.followup.send(
            f"🏓 Pong!\n"
            f"Gateway latency: `{gateway_latency:.2f}ms`\n"
            f"Defer time: `{defer_ms:.2f}ms`"
        )
        total = (time.monotonic() - start) * 1000
        print(f"[PING] gateway={gateway_latency:.2f}ms | defer={defer_ms:.2f}ms | total={total:.2f}ms")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingCog(bot))
