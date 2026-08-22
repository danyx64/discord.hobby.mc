import discord
from redbot.core import commands


class OwnerControl(commands.Cog):
    """Strumenti remoti riservati esclusivamente al proprietario del bot."""

    def __init__(self, bot):
        self.bot = bot

    async def red_delete_data_for_user(self, **kwargs):
        return

    @commands.group(name="ownerctl", aliases=["oc"])
    @commands.is_owner()
    async def ownerctl(self, ctx: commands.Context):
        """Controllo remoto owner-only dei server in cui si trova il bot."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ownerctl.command(name="guilds")
    async def guilds(self, ctx: commands.Context):
        """Elenca i server in cui si trova il bot."""
        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())
        if not guilds:
            return await ctx.send("Il bot non si trova in nessun server.")

        lines = []
        for g in guilds:
            lines.append(f"`{g.id}` — **{g.name}** — {g.member_count or 0} membri")

        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 1800:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)

        for chunk in chunks:
            await ctx.send(chunk)

    @ownerctl.command(name="guildinfo")
    async def guildinfo(self, ctx: commands.Context, guild_id: int):
        """Mostra informazioni su un server."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")

        me = guild.me
        owner = guild.owner
        embed = discord.Embed(title=guild.name, colour=discord.Colour.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="Membri", value=str(guild.member_count or 0), inline=True)
        embed.add_field(name="Owner", value=f"{owner} (`{owner.id}`)" if owner else "Sconosciuto", inline=False)
        embed.add_field(name="Canali", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Ruoli", value=str(len(guild.roles)), inline=True)
        if me:
            embed.add_field(name="Permessi bot", value=f"`{me.guild_permissions.value}`", inline=False)
        await ctx.send(embed=embed)

    @ownerctl.command(name="channels")
    async def channels(self, ctx: commands.Context, guild_id: int):
        """Elenca i canali testuali visibili al bot in un server."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")

        lines = []
        for channel in guild.text_channels:
            me = guild.me
            if me and channel.permissions_for(me).view_channel:
                lines.append(f"`{channel.id}` — #{channel.name}")

        if not lines:
            return await ctx.send("Nessun canale testuale visibile al bot.")
        await ctx.send("\n".join(lines[:60]))

    @ownerctl.command(name="send")
    async def send_message(self, ctx: commands.Context, guild_id: int, channel_id: int, *, message: str):
        """Invia un messaggio tramite il bot in un canale specifico."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Canale testuale non trovato.")

        me = guild.me
        if me is None or not channel.permissions_for(me).send_messages:
            return await ctx.send("Il bot non ha il permesso di scrivere in quel canale.")

        try:
            sent = await channel.send(message)
        except discord.Forbidden:
            return await ctx.send("Discord ha negato l'invio del messaggio.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore Discord durante l'invio: `{exc}`")

        await ctx.send(f"Messaggio inviato in {channel.mention}: {sent.jump_url}")

    @ownerctl.command(name="invite")
    async def create_invite(self, ctx: commands.Context, guild_id: int, channel_id: int = 0):
        """Crea un invito nel server, solo dove il bot ha il permesso necessario."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")

        candidates = []
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel is not None:
                candidates.append(channel)
        else:
            if guild.system_channel:
                candidates.append(guild.system_channel)
            candidates.extend(guild.text_channels)

        me = guild.me
        for channel in candidates:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
                continue
            if me is None:
                break
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.create_instant_invite):
                continue
            try:
                invite = await channel.create_invite(
                    max_age=3600,
                    max_uses=1,
                    unique=True,
                    reason="OwnerControl: invito richiesto dal proprietario del bot",
                )
                return await ctx.send(f"Invito monouso valido 1 ora: {invite.url}")
            except (discord.Forbidden, discord.HTTPException):
                continue

        await ctx.send("Non posso creare un invito: il bot non ha `Crea invito` in nessun canale utilizzabile.")

    @ownerctl.command(name="botnick")
    async def botnick(self, ctx: commands.Context, guild_id: int, *, nickname: str = ""):
        """Cambia il nickname del bot in un server."""
        guild = self.bot.get_guild(guild_id)
        if guild is None or guild.me is None:
            return await ctx.send("Server non trovato.")
        try:
            await guild.me.edit(nick=nickname or None, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non ha il permesso di cambiare il proprio nickname.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore Discord: `{exc}`")
        await ctx.send("Nickname aggiornato.")

    @ownerctl.command(name="leave")
    async def leave_guild(self, ctx: commands.Context, guild_id: int, confirmation: str = ""):
        """Fa uscire il bot da un server. Richiede: conferma."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        if confirmation.lower() != "conferma":
            return await ctx.send(f"Per uscire da **{guild.name}**, usa: `{ctx.clean_prefix}ownerctl leave {guild_id} conferma`")
        name = guild.name
        await guild.leave()
        await ctx.send(f"Uscito da **{name}**.")

    @ownerctl.command(name="presence")
    async def presence(self, ctx: commands.Context, *, text: str = ""):
        """Imposta l'attivita' globale del bot."""
        activity = discord.Game(name=text) if text else None
        await self.bot.change_presence(activity=activity)
        await ctx.send("Presenza aggiornata.")
