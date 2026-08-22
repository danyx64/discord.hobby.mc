from datetime import datetime, timezone

import discord
from redbot.core import Config, commands


class UserOwnerControl(commands.Cog):
    """Console owner-only per gli utenti conosciuti tramite interazioni/app."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=641732805112, force_registration=True)
        self.config.register_global(known_users={})

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        async with self.config.known_users() as data:
            data.pop(str(user_id), None)

    async def _remember(self, user: discord.abc.User, guild_id=None):
        now = int(datetime.now(timezone.utc).timestamp())
        async with self.config.known_users() as data:
            entry = data.get(str(user.id), {})
            entry.update({
                "id": user.id,
                "name": str(user),
                "display_name": getattr(user, "display_name", str(user)),
                "last_seen": now,
                "last_guild_id": guild_id,
            })
            data[str(user.id)] = entry

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        user = getattr(interaction, "user", None)
        if user is None or getattr(user, "bot", False):
            return
        guild_id = interaction.guild.id if interaction.guild else None
        await self._remember(user, guild_id)

    async def _get_user(self, user_id: int):
        user = self.bot.get_user(user_id)
        if user is not None:
            return user
        try:
            return await self.bot.fetch_user(user_id)
        except (discord.NotFound, discord.HTTPException):
            return None

    @commands.group(name="uoc", aliases=["userowner", "userctl"])
    @commands.is_owner()
    async def uoc(self, ctx: commands.Context):
        """Controllo owner-only degli utenti conosciuti dall'app."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @uoc.command(name="known")
    async def known(self, ctx: commands.Context):
        """Elenca gli utenti che hanno interagito con l'app e sono stati registrati."""
        data = await self.config.known_users()
        if not data:
            return await ctx.send("Nessun utente conosciuto registrato finora.")

        rows = sorted(data.values(), key=lambda x: x.get("last_seen", 0), reverse=True)
        lines = []
        for row in rows[:100]:
            last = row.get("last_seen", 0)
            when = f"<t:{last}:R>" if last else "sconosciuto"
            lines.append(f"`{row.get('id')}` — **{row.get('name', 'sconosciuto')}** — visto {when}")

        chunks, current = [], ""
        for line in lines:
            if len(current) + len(line) + 1 > 1800:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)
        for chunk in chunks:
            await ctx.send(chunk)

    @uoc.command(name="info")
    async def info(self, ctx: commands.Context, user_id: int):
        """Mostra quello che il bot sa di un utente specifico."""
        data = await self.config.known_users()
        saved = data.get(str(user_id))
        user = await self._get_user(user_id)

        if saved is None and user is None:
            return await ctx.send("Utente non conosciuto e non recuperabile da Discord.")

        embed = discord.Embed(title="User Install / Known User", colour=discord.Colour.blurple())
        if user:
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Utente", value=f"{user} (`{user.id}`)", inline=False)
            embed.add_field(name="Account creato", value=f"<t:{int(user.created_at.timestamp())}:F>", inline=False)
        if saved:
            if saved.get("last_seen"):
                embed.add_field(name="Ultima interazione", value=f"<t:{saved['last_seen']}:R>", inline=True)
            if saved.get("last_guild_id"):
                embed.add_field(name="Ultimo server visto", value=f"`{saved['last_guild_id']}`", inline=True)

        mutuals = []
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                mutuals.append(f"**{guild.name}** (`{guild.id}`)")
        embed.add_field(name="Server in comune visibili al bot", value="\n".join(mutuals[:20]) or "Nessuno", inline=False)
        await ctx.send(embed=embed)

    @uoc.command(name="dm")
    async def dm(self, ctx: commands.Context, user_id: int, *, message: str):
        """Tenta di inviare un singolo DM a un utente specifico."""
        if len(message) > 1900:
            return await ctx.send("Messaggio troppo lungo: massimo 1900 caratteri.")
        user = await self._get_user(user_id)
        if user is None:
            return await ctx.send("Utente non trovato.")
        try:
            await user.send(message)
        except discord.Forbidden:
            return await ctx.send("Discord ha bloccato il DM per privacy/contesto.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore Discord: `{exc}`")
        await self._remember(user)
        await ctx.send(f"DM inviato a **{user}** (`{user.id}`).")

    @uoc.command(name="mutuals")
    async def mutuals(self, ctx: commands.Context, user_id: int):
        """Elenca i server in cui il bot vede quell'utente."""
        lines = []
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                lines.append(f"`{guild.id}` — **{guild.name}** — {member}")
        if not lines:
            return await ctx.send("Nessun server in comune visibile al bot.")
        await ctx.send("\n".join(lines[:50]))

    @uoc.command(name="invite")
    async def invite(self, ctx: commands.Context, user_id: int, guild_id: int):
        """Crea un invito dove consentito e prova a inviarlo via DM all'utente."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        user = await self._get_user(user_id)
        if user is None:
            return await ctx.send("Utente non trovato.")

        me = guild.me
        if me is None:
            return await ctx.send("Il bot non e' membro di quel server.")

        candidates = []
        if guild.system_channel:
            candidates.append(guild.system_channel)
        candidates.extend(guild.text_channels)
        candidates.extend(guild.voice_channels)

        invite = None
        for channel in candidates:
            try:
                perms = channel.permissions_for(me)
                if not (perms.view_channel and perms.create_instant_invite):
                    continue
                invite = await channel.create_invite(max_age=3600, max_uses=1, unique=True, reason="UserOwnerControl")
                break
            except (discord.Forbidden, discord.HTTPException):
                continue

        if invite is None:
            return await ctx.send("Non posso creare un invito in quel server con i permessi attuali.")

        try:
            await user.send(f"Invito a **{guild.name}**: {invite.url}")
        except discord.Forbidden:
            return await ctx.send(f"Invito creato ({invite.url}), ma Discord ha bloccato il DM all'utente.")
        except discord.HTTPException as exc:
            return await ctx.send(f"Invito creato ({invite.url}), ma il DM ha dato errore: `{exc}`")

        await ctx.send(f"Invito inviato a **{user}** per **{guild.name}**.")

    @uoc.command(name="forget")
    async def forget(self, ctx: commands.Context, user_id: int):
        """Rimuove un utente dal registro locale del cog."""
        async with self.config.known_users() as data:
            existed = data.pop(str(user_id), None)
        await ctx.send("Utente rimosso dal registro." if existed else "Utente non presente nel registro.")

    @uoc.command(name="stats")
    async def stats(self, ctx: commands.Context):
        """Statistiche del registro e della visibilita' del bot."""
        data = await self.config.known_users()
        cached_users = {member.id for guild in self.bot.guilds for member in guild.members}
        await ctx.send(
            f"**Utenti registrati da interazioni:** {len(data)}\n"
            f"**Server del bot:** {len(self.bot.guilds)}\n"
            f"**Utenti visibili nei server:** {len(cached_users)}\n\n"
            "Discord non fornisce una lista completa degli account che hanno installato l'app senza interagire con essa."
        )
