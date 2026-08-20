from datetime import timezone
from zoneinfo import ZoneInfo

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


ITALY_TZ = ZoneInfo("Europe/Rome")


class Welcome(commands.Cog):
    """Invia un messaggio personalizzato quando un membro entra nel server."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=581244918377421006, force_registration=True)
        self.config.register_guild(
            enabled=False,
            channel_id=None,
            message="Benvenuto {user} in {guild}! Sei il membro numero {member_count}.",
        )

    @staticmethod
    def _format_message(member: discord.Member, template: str) -> str:
        guild = member.guild
        now = discord.utils.utcnow().astimezone(ITALY_TZ)
        created = member.created_at.astimezone(ITALY_TZ)
        joined = member.joined_at.astimezone(ITALY_TZ) if member.joined_at else None
        avatar = member.display_avatar.url if member.display_avatar else ""

        values = {
            "user": member.mention,
            "mention": member.mention,
            "user_mention": member.mention,
            "username": member.name,
            "displayname": member.display_name,
            "user_tag": str(member),
            "user_id": str(member.id),
            "user_avatar": avatar,
            "guild": guild.name,
            "server": guild.name,
            "guild_id": str(guild.id),
            "server_id": str(guild.id),
            "member_count": str(guild.member_count or len(guild.members)),
            "date": now.strftime("%d/%m/%Y"),
            "time": now.strftime("%H:%M:%S"),
            "datetime": now.strftime("%d/%m/%Y %H:%M:%S"),
            "account_created": created.strftime("%d/%m/%Y %H:%M:%S"),
            "joined_at": joined.strftime("%d/%m/%Y %H:%M:%S") if joined else "—",
        }

        result = template
        for key, value in values.items():
            result = result.replace("{" + key + "}", value)
        return result[:2000]

    async def _send_welcome(self, member: discord.Member, *, force: bool = False):
        data = await self.config.guild(member.guild).all()
        if not force and not data.get("enabled"):
            return False

        channel_id = data.get("channel_id")
        if not channel_id:
            return False
        channel = member.guild.get_channel(int(channel_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        me = member.guild.me
        if me is None:
            return False
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages):
            return False

        content = self._format_message(member, str(data.get("message") or "Benvenuto {user}!"))
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False),
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        await self._send_welcome(member)

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx: commands.Context):
        """Configura il messaggio di benvenuto."""
        await ctx.send_help(ctx.command)

    @welcome.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_setchannel(self, ctx: commands.Context, channel_id: int):
        """Imposta il canale di benvenuto usando il suo ID."""
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Non trovo un canale testuale con questo ID.")
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.view_channel and perms.send_messages):
            return await ctx.send("Mi servono Visualizza canale e Invia messaggi in quel canale.")
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Canale welcome impostato su {channel.mention} (`{channel.id}`).")

    @welcome.command(name="message")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_message(self, ctx: commands.Context, *, text: str):
        """Imposta il messaggio inviato ai nuovi membri."""
        if not text.strip():
            return await ctx.send("Il messaggio non può essere vuoto.")
        if len(text) > 2000:
            return await ctx.send("Il messaggio non può superare 2000 caratteri.")
        await self.config.guild(ctx.guild).message.set(text)
        await ctx.send("Messaggio di benvenuto aggiornato. Usa `.welcome preview` per provarlo.")

    @welcome.command(name="view")
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_view(self, ctx: commands.Context):
        """Mostra il messaggio attualmente configurato."""
        text = await self.config.guild(ctx.guild).message()
        await ctx.send(f"Messaggio configurato:\n```\n{text}\n```")

    @welcome.command(name="usage", aliases=["placeholders"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_usage(self, ctx: commands.Context):
        """Mostra tutti i placeholder disponibili nel messaggio."""
        text = (
            "**Placeholder disponibili**\n"
            "`{user}` / `{mention}` / `{user_mention}` → menzione cliccabile del membro\n"
            "`{username}` → username\n"
            "`{displayname}` → nome visualizzato\n"
            "`{user_tag}` → nome Discord completo\n"
            "`{user_id}` → ID utente\n"
            "`{user_avatar}` → URL avatar\n"
            "`{guild}` / `{server}` → nome del server\n"
            "`{guild_id}` / `{server_id}` → ID del server\n"
            "`{member_count}` → numero membri\n"
            "`{date}` → data\n"
            "`{time}` → ora\n"
            "`{datetime}` → data e ora\n"
            "`{account_created}` → creazione account Discord\n"
            "`{joined_at}` → ingresso nel server\n\n"
            "Esempio:\n"
            "`.welcome message Benvenuto {user} in {guild}! Sei il membro numero {member_count}.`"
        )
        await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    @welcome.command(name="enable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_enable(self, ctx: commands.Context):
        """Abilita i messaggi di benvenuto."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Welcome abilitato.")

    @welcome.command(name="disable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_disable(self, ctx: commands.Context):
        """Disabilita i messaggi di benvenuto."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Welcome disabilitato.")

    @welcome.command(name="status")
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_status(self, ctx: commands.Context):
        """Mostra stato, canale e messaggio configurati."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data.get("channel_id")) if data.get("channel_id") else None
        await ctx.send(
            f"Stato: **{'attivo' if data.get('enabled') else 'disattivato'}**\n"
            f"Canale: {channel.mention if channel else '—'}\n"
            f"Messaggio: `{data.get('message')}`",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome.command(name="preview", aliases=["test"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_preview(self, ctx: commands.Context):
        """Invia nel canale configurato un'anteprima usando il tuo account."""
        ok = await self._send_welcome(ctx.author, force=True)
        if ok:
            await ctx.send("Anteprima inviata nel canale welcome.")
        else:
            await ctx.send("Non sono riuscito a inviare l'anteprima. Controlla `.welcome status` e i permessi del bot.")
