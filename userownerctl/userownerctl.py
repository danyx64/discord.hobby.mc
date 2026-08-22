from datetime import datetime, timezone

import discord
from redbot.core import Config, commands


class UserOwnerControl(commands.Cog):
    """Console owner-only per gestire gli utenti conosciuti tramite User Install/interazioni."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=641732805112, force_registration=True)
        self.config.register_global(known_users={})

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        async with self.config.known_users() as data:
            data.pop(str(user_id), None)

    async def _remember(self, user: discord.abc.User, interaction: discord.Interaction = None):
        now = int(datetime.now(timezone.utc).timestamp())
        guild_id = interaction.guild.id if interaction and interaction.guild else None
        channel_id = interaction.channel_id if interaction else None
        context = "dm" if interaction and interaction.guild is None else "guild"
        command_name = None
        if interaction is not None:
            command = getattr(interaction, "command", None)
            command_name = getattr(command, "qualified_name", None) or getattr(command, "name", None)

        async with self.config.known_users() as data:
            entry = data.get(str(user.id), {})
            first_seen = entry.get("first_seen", now)
            contexts = entry.get("contexts", {"dm": 0, "guild": 0})
            contexts.setdefault("dm", 0)
            contexts.setdefault("guild", 0)
            contexts[context] += 1

            commands_used = entry.get("commands_used", {})
            if command_name:
                commands_used[command_name] = commands_used.get(command_name, 0) + 1

            entry.update({
                "id": user.id,
                "name": str(user),
                "display_name": getattr(user, "display_name", str(user)),
                "first_seen": first_seen,
                "last_seen": now,
                "last_guild_id": guild_id,
                "last_channel_id": channel_id,
                "interactions": int(entry.get("interactions", 0)) + 1,
                "contexts": contexts,
                "commands_used": commands_used,
            })
            data[str(user.id)] = entry

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        user = getattr(interaction, "user", None)
        if user is None or getattr(user, "bot", False):
            return
        await self._remember(user, interaction)

    async def _get_user(self, user_id: int):
        user = self.bot.get_user(user_id)
        if user is not None:
            return user
        try:
            return await self.bot.fetch_user(user_id)
        except (discord.NotFound, discord.HTTPException):
            return None

    def _mutual_guilds(self, user_id: int):
        found = []
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                found.append((guild, member))
        return found

    @commands.group(name="uoc", aliases=["userowner", "userctl"])
    @commands.is_owner()
    async def uoc(self, ctx: commands.Context):
        """Controllo owner-only degli utenti conosciuti tramite User Install/interazioni."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @uoc.command(name="list", aliases=["known", "users"])
    async def list_users(self, ctx: commands.Context, page: int = 1):
        """Elenca gli utenti conosciuti dal bot. Pagina da 20 utenti."""
        data = await self.config.known_users()
        if not data:
            return await ctx.send("Nessun utente conosciuto registrato finora.")

        rows = sorted(data.values(), key=lambda x: x.get("last_seen", 0), reverse=True)
        per_page = 20
        total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        selected = rows[start:start + per_page]

        embed = discord.Embed(
            title="User Install - utenti conosciuti",
            description=(
                "Questa lista contiene gli utenti che Discord ha reso visibili al bot tramite almeno "
                "un'interazione. Non e' una lista garantita di tutte le installazioni passive."
            ),
            colour=discord.Colour.blurple(),
        )
        for row in selected:
            first = row.get("first_seen", 0)
            last = row.get("last_seen", 0)
            interactions = row.get("interactions", 0)
            value = (
                f"ID: `{row.get('id')}`\n"
                f"Prima volta: {f'<t:{first}:R>' if first else 'sconosciuta'} | "
                f"Ultima: {f'<t:{last}:R>' if last else 'sconosciuta'}\n"
                f"Interazioni: **{interactions}**"
            )
            embed.add_field(name=row.get("name", "sconosciuto"), value=value, inline=False)
        embed.set_footer(text=f"Pagina {page}/{total_pages} - Totale conosciuti: {len(rows)}")
        await ctx.send(embed=embed)

    @uoc.command(name="find", aliases=["search"])
    async def find_user(self, ctx: commands.Context, *, query: str):
        """Cerca nel registro per nome, display name o ID."""
        query = query.strip().lower()
        data = await self.config.known_users()
        matches = []
        for row in data.values():
            haystack = " ".join([
                str(row.get("id", "")),
                str(row.get("name", "")),
                str(row.get("display_name", "")),
            ]).lower()
            if query in haystack:
                matches.append(row)

        if not matches:
            return await ctx.send("Nessun utente trovato nel registro.")
        lines = []
        for row in sorted(matches, key=lambda x: x.get("last_seen", 0), reverse=True)[:50]:
            lines.append(f"`{row.get('id')}` - **{row.get('name', 'sconosciuto')}**")
        await ctx.send("\n".join(lines))

    @uoc.command(name="info")
    async def info(self, ctx: commands.Context, user_id: int):
        """Mostra tutte le informazioni disponibili su un utente conosciuto."""
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
            first = saved.get("first_seen")
            last = saved.get("last_seen")
            if first:
                embed.add_field(name="Prima interazione", value=f"<t:{first}:F>", inline=True)
            if last:
                embed.add_field(name="Ultima interazione", value=f"<t:{last}:R>", inline=True)
            embed.add_field(name="Interazioni registrate", value=str(saved.get("interactions", 0)), inline=True)

            contexts = saved.get("contexts", {})
            embed.add_field(
                name="Contesti",
                value=f"DM: **{contexts.get('dm', 0)}** | Server: **{contexts.get('guild', 0)}**",
                inline=False,
            )
            if saved.get("last_guild_id"):
                embed.add_field(name="Ultimo server visto", value=f"`{saved['last_guild_id']}`", inline=True)
            if saved.get("last_channel_id"):
                embed.add_field(name="Ultimo canale visto", value=f"`{saved['last_channel_id']}`", inline=True)

            commands_used = saved.get("commands_used", {})
            if commands_used:
                top = sorted(commands_used.items(), key=lambda item: item[1], reverse=True)[:10]
                embed.add_field(
                    name="Comandi/interazioni piu' usati",
                    value="\n".join(f"`{name}` - {count}" for name, count in top),
                    inline=False,
                )

        mutuals = self._mutual_guilds(user_id)
        embed.add_field(
            name="Server in comune visibili al bot",
            value="\n".join(f"**{guild.name}** (`{guild.id}`)" for guild, _ in mutuals[:20]) or "Nessuno",
            inline=False,
        )
        await ctx.send(embed=embed)

    @uoc.command(name="dm")
    async def dm(self, ctx: commands.Context, user_id: int, *, message: str):
        """Tenta di inviare un singolo DM all'utente indicato."""
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
        await ctx.send(f"DM inviato a **{user}** (`{user.id}`).")

    @uoc.command(name="mutuals")
    async def mutuals(self, ctx: commands.Context, user_id: int):
        """Elenca i server in cui il bot vede quell'utente."""
        found = self._mutual_guilds(user_id)
        if not found:
            return await ctx.send("Nessun server in comune visibile al bot.")
        lines = [f"`{guild.id}` - **{guild.name}** - {member}" for guild, member in found]
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
                invite = await channel.create_invite(
                    max_age=3600,
                    max_uses=1,
                    unique=True,
                    reason="UserOwnerControl: owner invite",
                )
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

    @uoc.command(name="refresh")
    async def refresh(self, ctx: commands.Context, user_id: int):
        """Aggiorna nome/display name dell'utente nel registro, se recuperabile."""
        user = await self._get_user(user_id)
        if user is None:
            return await ctx.send("Utente non recuperabile da Discord.")
        async with self.config.known_users() as data:
            entry = data.get(str(user_id), {})
            entry.update({
                "id": user.id,
                "name": str(user),
                "display_name": getattr(user, "display_name", str(user)),
            })
            data[str(user_id)] = entry
        await ctx.send(f"Dati aggiornati per **{user}** (`{user.id}`).")

    @uoc.command(name="forget")
    async def forget(self, ctx: commands.Context, user_id: int):
        """Rimuove un utente dal registro locale del cog."""
        async with self.config.known_users() as data:
            existed = data.pop(str(user_id), None)
        await ctx.send("Utente rimosso dal registro." if existed else "Utente non presente nel registro.")

    @uoc.command(name="stats")
    async def stats(self, ctx: commands.Context):
        """Statistiche complete del registro User Install conosciuto."""
        data = await self.config.known_users()
        cached_users = {member.id for guild in self.bot.guilds for member in guild.members}
        total_interactions = sum(int(row.get("interactions", 0)) for row in data.values())
        dm_interactions = sum(int(row.get("contexts", {}).get("dm", 0)) for row in data.values())
        guild_interactions = sum(int(row.get("contexts", {}).get("guild", 0)) for row in data.values())

        embed = discord.Embed(title="User Install Control - statistiche", colour=discord.Colour.blurple())
        embed.add_field(name="Utenti conosciuti", value=str(len(data)), inline=True)
        embed.add_field(name="Interazioni registrate", value=str(total_interactions), inline=True)
        embed.add_field(name="Server del bot", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Interazioni DM", value=str(dm_interactions), inline=True)
        embed.add_field(name="Interazioni server", value=str(guild_interactions), inline=True)
        embed.add_field(name="Utenti visibili nei server", value=str(len(cached_users)), inline=True)
        embed.set_footer(text="Discord non espone al bot una lista completa delle installazioni utente passive.")
        await ctx.send(embed=embed)
