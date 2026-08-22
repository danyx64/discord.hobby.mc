import discord
from redbot.core import commands


class OwnerControl(commands.Cog):
    """Strumenti remoti owner-only, limitati ai permessi reali del bot in ogni server."""

    def __init__(self, bot):
        self.bot = bot

    async def red_delete_data_for_user(self, **kwargs):
        return

    def get_guild(self, guild_id: int):
        return self.bot.get_guild(guild_id)

    @commands.group(name="ownerctl", aliases=["oc"])
    @commands.is_owner()
    async def ownerctl(self, ctx: commands.Context):
        """Console owner-only per amministrare i server tramite i permessi del bot."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ownerctl.command(name="guilds")
    async def guilds(self, ctx: commands.Context):
        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())
        if not guilds:
            return await ctx.send("Il bot non si trova in nessun server.")
        lines = [f"`{g.id}` - **{g.name}** - {g.member_count or 0} membri" for g in guilds]
        for i in range(0, len(lines), 30):
            await ctx.send("\n".join(lines[i:i + 30]))

    @ownerctl.command(name="guildinfo")
    async def guildinfo(self, ctx: commands.Context, guild_id: int):
        guild = self.get_guild(guild_id)
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

    @ownerctl.command(name="permissions")
    async def permissions(self, ctx: commands.Context, guild_id: int):
        guild = self.get_guild(guild_id)
        if guild is None or guild.me is None:
            return await ctx.send("Server non trovato.")
        perms = guild.me.guild_permissions
        enabled = [name.replace("_", " ") for name, value in perms if value]
        text = ", ".join(enabled) or "Nessun permesso"
        for i in range(0, len(text), 1800):
            await ctx.send(text[i:i + 1800])

    @ownerctl.command(name="channels")
    async def channels(self, ctx: commands.Context, guild_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        me = guild.me
        lines = []
        for channel in guild.channels:
            if me and not channel.permissions_for(me).view_channel:
                continue
            kind = type(channel).__name__.replace("Channel", "")
            lines.append(f"`{channel.id}` - **{kind}** - {getattr(channel, 'name', 'senza nome')}")
        if not lines:
            return await ctx.send("Nessun canale visibile al bot.")
        for i in range(0, len(lines), 30):
            await ctx.send("\n".join(lines[i:i + 30]))

    @ownerctl.command(name="roles")
    async def roles(self, ctx: commands.Context, guild_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        lines = [f"`{r.id}` - **{r.name}** - pos {r.position}" for r in reversed(guild.roles)]
        for i in range(0, len(lines), 30):
            await ctx.send("\n".join(lines[i:i + 30]))

    @ownerctl.command(name="members")
    async def members(self, ctx: commands.Context, guild_id: int, limit: int = 50):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        limit = max(1, min(limit, 200))
        members = list(guild.members)[:limit]
        if not members:
            return await ctx.send("Nessun membro disponibile in cache. Potrebbe mancare il Members Intent.")
        lines = [f"`{m.id}` - {m} - {'BOT' if m.bot else 'utente'}" for m in members]
        for i in range(0, len(lines), 30):
            await ctx.send("\n".join(lines[i:i + 30]))

    @ownerctl.command(name="send")
    async def send_message(self, ctx: commands.Context, guild_id: int, channel_id: int, *, message: str):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            return await ctx.send("Canale testuale non trovato o non supportato.")
        me = guild.me
        if me is None or not channel.permissions_for(me).send_messages:
            return await ctx.send("Il bot non ha il permesso di scrivere in quel canale.")
        try:
            sent = await channel.send(message)
        except discord.Forbidden:
            return await ctx.send("Discord ha negato l'invio del messaggio.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore Discord: `{exc}`")
        await ctx.send(f"Messaggio inviato: {sent.jump_url}")

    @ownerctl.command(name="invite")
    async def create_invite(self, ctx: commands.Context, guild_id: int, channel_id: int = 0):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        candidates = []
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                candidates.append(channel)
        else:
            if guild.system_channel:
                candidates.append(guild.system_channel)
            candidates.extend(guild.text_channels)
            candidates.extend(guild.voice_channels)
        me = guild.me
        for channel in candidates:
            if me is None:
                break
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.create_instant_invite):
                continue
            try:
                invite = await channel.create_invite(max_age=3600, max_uses=1, unique=True, reason="OwnerControl")
                return await ctx.send(f"Invito monouso valido 1 ora: {invite.url}")
            except (discord.Forbidden, discord.HTTPException):
                continue
        await ctx.send("Il bot non ha il permesso di creare inviti in nessun canale utilizzabile.")

    @ownerctl.command(name="botnick")
    async def botnick(self, ctx: commands.Context, guild_id: int, *, nickname: str = ""):
        guild = self.get_guild(guild_id)
        if guild is None or guild.me is None:
            return await ctx.send("Server non trovato.")
        try:
            await guild.me.edit(nick=nickname or None, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Permesso negato.")
        await ctx.send("Nickname aggiornato.")

    @ownerctl.command(name="presence")
    async def presence(self, ctx: commands.Context, *, text: str = ""):
        await self.bot.change_presence(activity=discord.Game(name=text) if text else None)
        await ctx.send("Presenza aggiornata.")

    @ownerctl.command(name="kick")
    async def kick(self, ctx: commands.Context, guild_id: int, member_id: int, *, reason: str = "OwnerControl"):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        member = guild.get_member(member_id)
        if member is None:
            return await ctx.send("Membro non trovato.")
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' espellere questo membro.")
        await ctx.send("Membro espulso.")

    @ownerctl.command(name="ban")
    async def ban(self, ctx: commands.Context, guild_id: int, member_id: int, *, reason: str = "OwnerControl"):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        user = guild.get_member(member_id) or self.bot.get_user(member_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(member_id)
            except discord.HTTPException:
                return await ctx.send("Utente non trovato.")
        try:
            await guild.ban(user, reason=reason)
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' bannare questo utente.")
        await ctx.send("Utente bannato.")

    @ownerctl.command(name="unban")
    async def unban(self, ctx: commands.Context, guild_id: int, user_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        try:
            user = await self.bot.fetch_user(user_id)
            await guild.unban(user, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' rimuovere il ban.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore Discord: `{exc}`")
        await ctx.send("Ban rimosso.")

    @ownerctl.command(name="timeout")
    async def timeout(self, ctx: commands.Context, guild_id: int, member_id: int, minutes: int, *, reason: str = "OwnerControl"):
        from datetime import timedelta
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        member = guild.get_member(member_id)
        if member is None:
            return await ctx.send("Membro non trovato.")
        try:
            await member.timeout(timedelta(minutes=max(1, min(minutes, 40320))), reason=reason)
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' mettere in timeout questo membro.")
        await ctx.send("Timeout applicato.")

    @ownerctl.command(name="untimeout")
    async def untimeout(self, ctx: commands.Context, guild_id: int, member_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        member = guild.get_member(member_id)
        if member is None:
            return await ctx.send("Membro non trovato.")
        try:
            await member.timeout(None, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Permesso negato.")
        await ctx.send("Timeout rimosso.")

    @ownerctl.command(name="addrole")
    async def addrole(self, ctx: commands.Context, guild_id: int, member_id: int, role_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        member = guild.get_member(member_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            return await ctx.send("Membro o ruolo non trovato.")
        try:
            await member.add_roles(role, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' assegnare quel ruolo.")
        await ctx.send("Ruolo assegnato.")

    @ownerctl.command(name="removerole")
    async def removerole(self, ctx: commands.Context, guild_id: int, member_id: int, role_id: int):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        member = guild.get_member(member_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            return await ctx.send("Membro o ruolo non trovato.")
        try:
            await member.remove_roles(role, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' rimuovere quel ruolo.")
        await ctx.send("Ruolo rimosso.")

    @ownerctl.command(name="createtext")
    async def createtext(self, ctx: commands.Context, guild_id: int, *, name: str):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        try:
            channel = await guild.create_text_channel(name, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' creare canali.")
        await ctx.send(f"Creato {channel.mention} (`{channel.id}`).")

    @ownerctl.command(name="createvoice")
    async def createvoice(self, ctx: commands.Context, guild_id: int, *, name: str):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        try:
            channel = await guild.create_voice_channel(name, reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' creare canali vocali.")
        await ctx.send(f"Creato **{channel.name}** (`{channel.id}`).")

    @ownerctl.command(name="deletechannel")
    async def deletechannel(self, ctx: commands.Context, guild_id: int, channel_id: int, confirmation: str = ""):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        channel = guild.get_channel(channel_id)
        if channel is None:
            return await ctx.send("Canale non trovato.")
        if confirmation.lower() != "conferma":
            return await ctx.send(f"Usa `{ctx.clean_prefix}ownerctl deletechannel {guild_id} {channel_id} conferma`")
        try:
            await channel.delete(reason="OwnerControl")
        except discord.Forbidden:
            return await ctx.send("Il bot non puo' eliminare quel canale.")
        await ctx.send("Canale eliminato.")

    @ownerctl.command(name="leave")
    async def leave_guild(self, ctx: commands.Context, guild_id: int, confirmation: str = ""):
        guild = self.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        if confirmation.lower() != "conferma":
            return await ctx.send(f"Per uscire da **{guild.name}**, usa `{ctx.clean_prefix}ownerctl leave {guild_id} conferma`")
        name = guild.name
        await guild.leave()
        await ctx.send(f"Uscito da **{name}**.")
