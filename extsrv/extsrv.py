import re
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from redbot.core import Config, commands


INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]+)",
    re.IGNORECASE,
)


class ExtSrv(commands.Cog):
    """Informazioni on-demand su un server Discord esterno tramite invito."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=927441853, force_registration=True)
        self.config.register_guild(invite=None)
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if not self.session.closed:
            await self.session.close()

    @staticmethod
    def _invite_code(value: str) -> Optional[str]:
        value = value.strip()
        match = INVITE_RE.search(value)
        if match:
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9-]+", value):
            return value
        return None

    async def _fetch_invite(self, code: str):
        url = f"https://discord.com/api/v10/invites/{code}"
        params = {"with_counts": "true", "with_expiration": "true"}
        async with self.session.get(url, params=params) as response:
            if response.status == 404:
                return None, "Invito non valido, scaduto o non più disponibile."
            if response.status == 429:
                return None, "Discord sta limitando temporaneamente le richieste. Riprova tra poco."
            if response.status != 200:
                return None, f"Discord API ha restituito HTTP {response.status}."
            return await response.json(), None

    @app_commands.command(name="extsrv", description="Mostra il server Discord esterno monitorato.")
    @app_commands.guild_only()
    async def extsrv(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        invite = await self.config.guild(interaction.guild).invite()
        if not invite:
            await interaction.followup.send("Nessun server esterno configurato.", ephemeral=True)
            return

        code = self._invite_code(invite)
        data, error = await self._fetch_invite(code)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return

        guild = data.get("guild") or {}
        name = guild.get("name") or "Server esterno"
        guild_id = guild.get("id")
        members = data.get("approximate_member_count")
        online = data.get("approximate_presence_count")
        description = guild.get("description")

        embed = discord.Embed(
            title=name,
            description=description or "Informazioni pubbliche del server monitorato.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Membri",
            value=f"{members:,}".replace(",", ".") if members is not None else "Non disponibile",
            inline=True,
        )
        if online is not None:
            embed.add_field(name="Online", value=f"{online:,}".replace(",", "."), inline=True)
        if guild_id:
            embed.add_field(name="Server ID", value=guild_id, inline=True)

        icon_hash = guild.get("icon")
        if guild_id and icon_hash:
            ext = "gif" if str(icon_hash).startswith("a_") else "png"
            embed.set_thumbnail(url=f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}?size=256")

        embed.set_footer(text="Conteggi approssimativi forniti da Discord")
        await interaction.followup.send(embed=embed)

    @commands.group(name="extsrvset", invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def extsrvset(self, ctx: commands.Context):
        """Configura ExtSrv tramite normali comandi con prefisso."""
        await ctx.send_help(ctx.command)

    @extsrvset.command(name="invite")
    async def extsrvset_invite(self, ctx: commands.Context, *, invito: str):
        """Imposta il link/codice invito del server esterno."""
        code = self._invite_code(invito)
        if not code:
            await ctx.send("Invito Discord non valido.")
            return

        data, error = await self._fetch_invite(code)
        if error:
            await ctx.send(error)
            return

        await self.config.guild(ctx.guild).invite.set(code)
        guild = data.get("guild") or {}
        await ctx.send(f"Server monitorato impostato su **{guild.get('name') or 'server esterno'}**.")

    @extsrvset.command(name="show")
    async def extsrvset_show(self, ctx: commands.Context):
        """Mostra l'invito attualmente configurato."""
        invite = await self.config.guild(ctx.guild).invite()
        if not invite:
            await ctx.send("Nessun invito configurato.")
            return
        await ctx.send(f"Invito monitorato: `https://discord.gg/{invite}`")

    @extsrvset.command(name="clear")
    async def extsrvset_clear(self, ctx: commands.Context):
        """Rimuove la configurazione corrente."""
        await self.config.guild(ctx.guild).invite.clear()
        await ctx.send("Configurazione ExtSrv rimossa.")
