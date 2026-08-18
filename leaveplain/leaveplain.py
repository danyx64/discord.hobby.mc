import discord
from redbot.core import Config, commands


class LeavePlain(commands.Cog):
    """Avvisi testuali quando un membro lascia il server."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=64642026081801, force_registration=True
        )
        self.config.register_guild(
            channel_id=None,
            enabled=True,
            message="👋 È uscito {mention} | {name} | ID: {id}",
        )

    @commands.group(name="leaveplain", invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def leaveplain(self, ctx):
        """Configura gli avvisi testuali per i membri che escono."""
        await ctx.send_help()

    @leaveplain.command(name="canale", aliases=["channel"])
    async def canale(self, ctx, channel: discord.TextChannel):
        """Imposta il canale dove inviare gli avvisi."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"✅ Canale delle uscite impostato su {channel.mention}.")

    @leaveplain.command(name="messaggio", aliases=["message"])
    async def messaggio(self, ctx, *, message: str):
        """Imposta il testo. Variabili: {mention}, {name}, {display_name}, {id}."""
        try:
            message.format(
                mention="@Utente",
                name="utente",
                display_name="Utente",
                id="123456789",
            )
        except (KeyError, ValueError, IndexError):
            await ctx.send(
                "❌ Il messaggio contiene una variabile non valida. Usa solo: "
                "`{mention}`, `{name}`, `{display_name}`, `{id}`."
            )
            return
        await self.config.guild(ctx.guild).message.set(message)
        await ctx.send("✅ Messaggio delle uscite aggiornato.")

    @leaveplain.command(name="attiva", aliases=["enable"])
    async def attiva(self, ctx):
        """Attiva gli avvisi."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ Avvisi di uscita attivati.")

    @leaveplain.command(name="disattiva", aliases=["disable"])
    async def disattiva(self, ctx):
        """Disattiva gli avvisi."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("✅ Avvisi di uscita disattivati.")

    @leaveplain.command(name="mostra", aliases=["show"])
    async def mostra(self, ctx):
        """Mostra la configurazione corrente."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data["channel_id"]) if data["channel_id"] else None
        stato = "attivi" if data["enabled"] else "disattivati"
        await ctx.send(
            f"**Avvisi:** {stato}\n"
            f"**Canale:** {channel.mention if channel else 'non impostato'}\n"
            f"**Messaggio:** {data['message']}"
        )

    @leaveplain.command(name="test")
    async def test(self, ctx):
        """Invia un avviso di prova usando il tuo account."""
        await self._send_leave_message(ctx.guild, ctx.author)
        await ctx.send("✅ Test eseguito. Controlla il canale delle uscite.")

    async def _send_leave_message(self, guild, member):
        data = await self.config.guild(guild).all()
        if not data["enabled"] or not data["channel_id"]:
            return False

        channel = guild.get_channel(data["channel_id"])
        if channel is None:
            return False

        try:
            text = data["message"].format(
                mention=member.mention,
                name=str(member),
                display_name=member.display_name,
                id=member.id,
            )
        except (KeyError, ValueError, IndexError):
            text = f"👋 È uscito {member.mention} | {member} | ID: {member.id}"

        try:
            await channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            return False
        return True

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._send_leave_message(member.guild, member)
