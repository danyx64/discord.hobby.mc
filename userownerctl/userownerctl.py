from datetime import datetime, timezone

import discord
from redbot.core import Config, commands


class UserOwnerControl(commands.Cog):
    """Console owner-only per User Install, utenti conosciuti e messaggi DM ricevuti dal bot."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=641732805112, force_registration=True)
        self.config.register_global(
            known_users={},
            dm_inbox=[],
            dm_forward=True,
            dm_forward_channel=0,
        )

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        async with self.config.known_users() as data:
            data.pop(str(user_id), None)
        async with self.config.dm_inbox() as inbox:
            inbox[:] = [row for row in inbox if int(row.get("user_id", 0)) != int(user_id)]

    async def _remember_user(self, user: discord.abc.User, *, guild_id=None, channel_id=None, command_name=None, context="dm"):
        now = int(datetime.now(timezone.utc).timestamp())
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
            entry.update(
                {
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
                }
            )
            data[str(user.id)] = entry

    async def _remember_interaction(self, interaction: discord.Interaction):
        user = interaction.user
        command = getattr(interaction, "command", None)
        command_name = getattr(command, "qualified_name", None) or getattr(command, "name", None)
        await self._remember_user(
            user,
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=interaction.channel_id,
            command_name=command_name,
            context="dm" if interaction.guild is None else "guild",
        )

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

    async def _store_dm(self, message: discord.Message):
        row = {
            "message_id": message.id,
            "user_id": message.author.id,
            "user_name": str(message.author),
            "content": message.content or "",
            "attachments": [a.url for a in message.attachments],
            "stickers": [str(s.name) for s in message.stickers],
            "created_at": int(message.created_at.timestamp()),
        }
        async with self.config.dm_inbox() as inbox:
            inbox.append(row)
            if len(inbox) > 200:
                del inbox[:-200]

    async def _forward_dm(self, message: discord.Message):
        if not await self.config.dm_forward():
            return

        content = message.content.strip() if message.content else "*(nessun testo)*"
        if len(content) > 1400:
            content = content[:1400] + "…"
        extras = []
        if message.attachments:
            extras.append("Allegati: " + " ".join(a.url for a in message.attachments[:5]))
        if message.stickers:
            extras.append("Sticker: " + ", ".join(s.name for s in message.stickers[:5]))

        embed = discord.Embed(
            title="Nuovo DM ricevuto dal bot",
            description=content,
            colour=discord.Colour.blurple(),
            timestamp=message.created_at,
        )
        embed.add_field(name="Utente", value=f"{message.author} (`{message.author.id}`)", inline=False)
        if extras:
            embed.add_field(name="Contenuti", value="\n".join(extras), inline=False)
        embed.set_footer(text=f"Message ID: {message.id}")

        channel_id = await self.config.dm_forward_channel()
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.send(embed=embed)
                    return
                except (discord.Forbidden, discord.HTTPException):
                    pass

        owner_ids = set(getattr(self.bot, "owner_ids", set()) or set())
        owner_id = getattr(self.bot, "owner_id", None)
        if owner_id:
            owner_ids.add(owner_id)
        for oid in owner_ids:
            owner = await self._get_user(int(oid))
            if owner is None:
                continue
            try:
                await owner.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                continue

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        user = getattr(interaction, "user", None)
        if user is None or getattr(user, "bot", False):
            return
        await self._remember_interaction(interaction)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None:
            return
        await self._remember_user(
            message.author,
            channel_id=message.channel.id,
            command_name="normal_dm_message",
            context="dm",
        )
        await self._store_dm(message)
        await self._forward_dm(message)

    @commands.group(name="uoc", aliases=["userowner", "userctl"])
    @commands.is_owner()
    async def uoc(self, ctx: commands.Context):
        """Controllo owner-only degli utenti e dei DM ricevuti dal bot."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @uoc.command(name="list", aliases=["known", "users"])
    async def list_users(self, ctx: commands.Context, page: int = 1):
        data = await self.config.known_users()
        if not data:
            return await ctx.send("Nessun utente conosciuto registrato finora.")
        rows = sorted(data.values(), key=lambda x: x.get("last_seen", 0), reverse=True)
        per_page = 20
        total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        embed = discord.Embed(
            title="User Install - utenti conosciuti",
            description="Utenti resi visibili al bot tramite interazioni o DM ricevuti.",
            colour=discord.Colour.blurple(),
        )
        for row in rows[start:start + per_page]:
            last = row.get("last_seen", 0)
            embed.add_field(
                name=row.get("name", "sconosciuto"),
                value=f"ID: `{row.get('id')}` | Ultima attivita': {f'<t:{last}:R>' if last else 'n/d'} | Eventi: **{row.get('interactions', 0)}**",
                inline=False,
            )
        embed.set_footer(text=f"Pagina {page}/{total_pages} - Totale: {len(rows)}")
        await ctx.send(embed=embed)

    @uoc.command(name="find", aliases=["search"])
    async def find_user(self, ctx: commands.Context, *, query: str):
        query = query.strip().lower()
        data = await self.config.known_users()
        matches = []
        for row in data.values():
            haystack = f"{row.get('id', '')} {row.get('name', '')} {row.get('display_name', '')}".lower()
            if query in haystack:
                matches.append(row)
        if not matches:
            return await ctx.send("Nessun utente trovato nel registro.")
        await ctx.send("\n".join(f"`{r.get('id')}` - **{r.get('name', 'sconosciuto')}**" for r in matches[:50]))

    @uoc.command(name="info")
    async def info(self, ctx: commands.Context, user_id: int):
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
            embed.add_field(name="Prima attivita'", value=f"<t:{first}:F>" if first else "n/d", inline=True)
            embed.add_field(name="Ultima attivita'", value=f"<t:{last}:R>" if last else "n/d", inline=True)
            embed.add_field(name="Eventi registrati", value=str(saved.get("interactions", 0)), inline=True)
            contexts = saved.get("contexts", {})
            embed.add_field(name="Contesti", value=f"DM: **{contexts.get('dm', 0)}** | Server: **{contexts.get('guild', 0)}**", inline=False)
        mutuals = self._mutual_guilds(user_id)
        embed.add_field(
            name="Server in comune visibili al bot",
            value="\n".join(f"**{g.name}** (`{g.id}`)" for g, _ in mutuals[:20]) or "Nessuno",
            inline=False,
        )
        await ctx.send(embed=embed)

    @uoc.command(name="dm")
    async def dm(self, ctx: commands.Context, user_id: int, *, message: str):
        """Invia un DM all'utente indicato."""
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

    @uoc.command(name="reply")
    async def reply(self, ctx: commands.Context, user_id: int, *, message: str):
        """Alias comodo per rispondere a un DM ricevuto."""
        await self.dm(ctx, user_id, message=message)

    @uoc.command(name="inbox")
    async def inbox(self, ctx: commands.Context, page: int = 1):
        """Mostra i DM normali ricevuti dal bot, 10 per pagina."""
        rows = await self.config.dm_inbox()
        if not rows:
            return await ctx.send("La casella DM del bot e' vuota.")
        rows = list(reversed(rows))
        per_page = 10
        total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        embed = discord.Embed(title="DM Inbox del bot", colour=discord.Colour.blurple())
        for row in rows[start:start + per_page]:
            text = row.get("content") or "*(nessun testo)*"
            if len(text) > 300:
                text = text[:300] + "…"
            attach_count = len(row.get("attachments", []))
            if attach_count:
                text += f"\n📎 Allegati: **{attach_count}**"
            ts = row.get("created_at", 0)
            embed.add_field(
                name=f"{row.get('user_name', 'sconosciuto')} - {row.get('user_id')}",
                value=f"{text}\n{f'<t:{ts}:R>' if ts else ''} | Msg `{row.get('message_id')}`",
                inline=False,
            )
        embed.set_footer(text=f"Pagina {page}/{total_pages} - Conservati ultimi {len(rows)} DM")
        await ctx.send(embed=embed)

    @uoc.command(name="inboxuser")
    async def inbox_user(self, ctx: commands.Context, user_id: int, limit: int = 10):
        """Mostra gli ultimi DM ricevuti da un utente specifico."""
        limit = max(1, min(limit, 30))
        rows = [r for r in await self.config.dm_inbox() if int(r.get("user_id", 0)) == user_id]
        if not rows:
            return await ctx.send("Nessun DM registrato per questo utente.")
        lines = []
        for row in rows[-limit:]:
            text = (row.get("content") or "[nessun testo]").replace("\n", " ")
            if len(text) > 250:
                text = text[:250] + "…"
            lines.append(f"`{row.get('message_id')}` <t:{row.get('created_at', 0)}:R> - {text}")
        await ctx.send("\n".join(lines))

    @uoc.command(name="forward")
    async def forward(self, ctx: commands.Context, mode: str):
        """Attiva/disattiva l'inoltro live dei DM: on/off."""
        mode = mode.lower().strip()
        if mode not in {"on", "off"}:
            return await ctx.send(f"Uso: `{ctx.clean_prefix}uoc forward on` oppure `off`.")
        enabled = mode == "on"
        await self.config.dm_forward.set(enabled)
        await ctx.send(f"Inoltro live DM **{'attivato' if enabled else 'disattivato'}**.")

    @uoc.command(name="forwardchannel")
    async def forward_channel(self, ctx: commands.Context, channel_id: int = 0):
        """Imposta un canale per ricevere i DM inoltrati. 0 = DM agli owner del bot."""
        if channel_id == 0:
            await self.config.dm_forward_channel.set(0)
            return await ctx.send("I DM verranno inoltrati direttamente agli owner del bot.")
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Canale testuale non trovato o non visibile al bot.")
        me = channel.guild.me
        if me is None or not channel.permissions_for(me).send_messages:
            return await ctx.send("Il bot non puo' scrivere in quel canale.")
        await self.config.dm_forward_channel.set(channel.id)
        await ctx.send(f"I DM ricevuti verranno inoltrati in {channel.mention}.")

    @uoc.command(name="clearinbox")
    async def clear_inbox(self, ctx: commands.Context, confirmation: str = ""):
        """Svuota il registro DM. Richiede 'conferma'."""
        if confirmation.lower() != "conferma":
            return await ctx.send(f"Per svuotare usa `{ctx.clean_prefix}uoc clearinbox conferma`.")
        await self.config.dm_inbox.set([])
        await ctx.send("Registro DM svuotato.")

    @uoc.command(name="mutuals")
    async def mutuals(self, ctx: commands.Context, user_id: int):
        found = self._mutual_guilds(user_id)
        if not found:
            return await ctx.send("Nessun server in comune visibile al bot.")
        await ctx.send("\n".join(f"`{g.id}` - **{g.name}** - {m}" for g, m in found[:50]))

    @uoc.command(name="invite")
    async def invite(self, ctx: commands.Context, user_id: int, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await ctx.send("Server non trovato.")
        user = await self._get_user(user_id)
        if user is None:
            return await ctx.send("Utente non trovato.")
        me = guild.me
        if me is None:
            return await ctx.send("Il bot non e' membro di quel server.")
        candidates = ([guild.system_channel] if guild.system_channel else []) + list(guild.text_channels) + list(guild.voice_channels)
        invite = None
        for channel in candidates:
            try:
                perms = channel.permissions_for(me)
                if perms.view_channel and perms.create_instant_invite:
                    invite = await channel.create_invite(max_age=3600, max_uses=1, unique=True, reason="UserOwnerControl")
                    break
            except (discord.Forbidden, discord.HTTPException):
                continue
        if invite is None:
            return await ctx.send("Non posso creare un invito con i permessi attuali.")
        try:
            await user.send(f"Invito a **{guild.name}**: {invite.url}")
        except discord.Forbidden:
            return await ctx.send(f"Invito creato ({invite.url}), ma Discord ha bloccato il DM.")
        await ctx.send(f"Invito inviato a **{user}** per **{guild.name}**.")

    @uoc.command(name="refresh")
    async def refresh(self, ctx: commands.Context, user_id: int):
        user = await self._get_user(user_id)
        if user is None:
            return await ctx.send("Utente non recuperabile da Discord.")
        async with self.config.known_users() as data:
            entry = data.get(str(user_id), {})
            entry.update({"id": user.id, "name": str(user), "display_name": getattr(user, "display_name", str(user))})
            data[str(user_id)] = entry
        await ctx.send(f"Dati aggiornati per **{user}** (`{user.id}`).")

    @uoc.command(name="forget")
    async def forget(self, ctx: commands.Context, user_id: int):
        async with self.config.known_users() as data:
            existed = data.pop(str(user_id), None)
        await ctx.send("Utente rimosso dal registro." if existed else "Utente non presente nel registro.")

    @uoc.command(name="stats")
    async def stats(self, ctx: commands.Context):
        data = await self.config.known_users()
        inbox = await self.config.dm_inbox()
        cached_users = {member.id for guild in self.bot.guilds for member in guild.members}
        total_events = sum(int(row.get("interactions", 0)) for row in data.values())
        embed = discord.Embed(title="User Install Control - statistiche", colour=discord.Colour.blurple())
        embed.add_field(name="Utenti conosciuti", value=str(len(data)), inline=True)
        embed.add_field(name="Eventi registrati", value=str(total_events), inline=True)
        embed.add_field(name="DM in inbox", value=str(len(inbox)), inline=True)
        embed.add_field(name="Server del bot", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Utenti visibili nei server", value=str(len(cached_users)), inline=True)
        embed.add_field(name="Inoltro DM", value="ON" if await self.config.dm_forward() else "OFF", inline=True)
        embed.set_footer(text="Discord non espone al bot una lista completa delle installazioni utente passive.")
        await ctx.send(embed=embed)
