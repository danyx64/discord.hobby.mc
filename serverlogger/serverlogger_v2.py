import asyncio
from collections import defaultdict
from typing import Optional

import discord
from redbot.core import commands

from .serverlogger import ServerLogger as BaseServerLogger


class ServerLogger(BaseServerLogger):
    """ServerLogger v1.4: logging rapido, affidabile e con mention Discord."""

    __version__ = "1.4.0"
    MESSAGE_CACHE_MAX_PER_GUILD = 10000
    CACHE_PRUNE_EVERY = 250

    def __init__(self, bot):
        super().__init__(bot)
        self._cache_write_count = defaultdict(int)
        self._init_message_cache()

    def _init_message_cache(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS message_cache (
                    message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    content TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_message_cache_guild ON message_cache(guild_id, message_id)")
            db.commit()

    @staticmethod
    def _display_member(guild: discord.Guild, object_id: Optional[int]) -> str:
        if not object_id:
            return "—"
        return f"<@{int(object_id)}>"

    @staticmethod
    def _display_channel(guild: discord.Guild, channel_id: Optional[int]) -> str:
        if not channel_id:
            return "—"
        return f"<#{int(channel_id)}>"

    @staticmethod
    def _display_role(role) -> str:
        if role is None:
            return "—"
        return f"<@&{int(role.id)}>"

    @staticmethod
    def _display_channels(channels) -> str:
        values = [f"<#{int(ch.id)}>" for ch in channels if ch is not None]
        return ", ".join(values) if values else "—"

    @staticmethod
    def _display_roles(roles) -> str:
        values = [f"<@&{int(role.id)}>" for role in roles if role is not None]
        return ", ".join(values) if values else "—"

    @property
    def _italy_tz(self):
        from .serverlogger import ITALY_TZ
        return ITALY_TZ

    def _make_embed(self, guild, log_id, action, staffer_id, user_id, channel_id, when, details=None):
        local = when.astimezone(self._italy_tz)
        lines = [
            f"**Azione:** {self._clean_text(action)}",
            f"**Staffer:** {self._display_member(guild, staffer_id)}",
            f"**Utente:** {self._display_member(guild, user_id)}",
            f"**Canale:** {self._display_channel(guild, channel_id)}",
            f"**Data:** {local.strftime('%d/%m/%Y')}",
            f"**Ora:** {local.strftime('%H:%M:%S')}",
        ]
        if details:
            for key, value in details.items():
                if value not in (None, "", [], {}, ()):
                    lines.append(f"**{key}:** {self._clean_text(value, 450)}")
        return discord.Embed(
            description=self._clean_text("\n".join(lines), 4000),
            colour=discord.Colour.blurple(),
        )

    async def _emit(self, guild, action, *, staffer=None, user=None, channel=None, details=None, when=None):
        if guild is None or not await self.config.guild(guild).enabled():
            return

        when = when or discord.utils.utcnow()
        staffer_id = self._object_id(staffer)
        user_id = self._object_id(user)
        channel_id = self._object_id(channel)

        log_id = await self._insert_log(
            guild.id, action, staffer_id, user_id, channel_id, when, details
        )

        cid = await self.config.guild(guild).log_channel_id()
        if not cid:
            return

        log_channel = guild.get_channel(int(cid)) or guild.get_thread(int(cid))
        if not isinstance(log_channel, (discord.TextChannel, discord.Thread)):
            return

        embed = self._make_embed(
            guild, log_id, action, staffer_id, user_id, channel_id, when, details
        )

        for attempt, delay in enumerate((0, 0.25, 0.6)):
            if delay:
                await asyncio.sleep(delay)
            try:
                await log_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=True, everyone=False, replied_user=False
                    ),
                )
                return
            except discord.Forbidden:
                return
            except discord.HTTPException:
                if attempt == 2:
                    return

    async def _find_audit_actor(self, guild, action, *, target_id=None, channel_id=None):
        if guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None

        for delay in (0, 0.18, 0.42):
            if delay:
                await asyncio.sleep(delay)
            actor = await super()._find_audit_actor(
                guild,
                action,
                target_id=target_id,
                channel_id=channel_id,
            )
            if actor is not None:
                return actor
        return None

    async def _cache_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        guild_id = message.guild.id
        self._cache_write_count[guild_id] += 1
        prune = self._cache_write_count[guild_id] >= self.CACHE_PRUNE_EVERY
        if prune:
            self._cache_write_count[guild_id] = 0

        async with self._db_lock:
            await asyncio.to_thread(
                self._cache_message_sync,
                message.id,
                guild_id,
                message.author.id,
                message.channel.id,
                message.content or "",
                discord.utils.utcnow().isoformat(),
                prune,
            )

    def _cache_message_sync(
        self, message_id, guild_id, author_id, channel_id, content, created_at, prune
    ):
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO message_cache "
                "(message_id, guild_id, author_id, channel_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, guild_id, author_id, channel_id, content, created_at),
            )
            if prune:
                db.execute(
                    "DELETE FROM message_cache WHERE guild_id = ? AND message_id NOT IN "
                    "(SELECT message_id FROM message_cache WHERE guild_id = ? "
                    "ORDER BY message_id DESC LIMIT ?)",
                    (guild_id, guild_id, self.MESSAGE_CACHE_MAX_PER_GUILD),
                )
            db.commit()

    async def _pop_cached_message(self, message_id: int):
        async with self._db_lock:
            return await asyncio.to_thread(self._pop_cached_message_sync, message_id)

    def _pop_cached_message_sync(self, message_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM message_cache WHERE message_id = ?", (message_id,)
            ).fetchone()
            db.execute("DELETE FROM message_cache WHERE message_id = ?", (message_id,))
            db.commit()
            return row

    async def _remove_cached_messages(self, message_ids):
        ids = tuple(int(mid) for mid in message_ids)
        if not ids:
            return
        async with self._db_lock:
            await asyncio.to_thread(self._remove_cached_messages_sync, ids)

    def _remove_cached_messages_sync(self, message_ids):
        placeholders = ",".join("?" for _ in message_ids)
        with self._connect() as db:
            db.execute(
                f"DELETE FROM message_cache WHERE message_id IN ({placeholders})",
                message_ids,
            )
            db.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        await self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        return

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        return

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        cached = payload.cached_message
        stored = await self._pop_cached_message(payload.message_id)
        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)

        author = None
        author_id = None
        content = "—"

        if cached is not None:
            if cached.author.bot:
                return
            author = cached.author
            author_id = cached.author.id
            content = cached.content or "—"
        elif stored is not None:
            author_id = int(stored["author_id"])
            author = guild.get_member(author_id) or self.bot.get_user(author_id)
            content = stored["content"] or "—"

        actor = await self._find_audit_actor(
            guild,
            discord.AuditLogAction.message_delete,
            target_id=author_id,
            channel_id=payload.channel_id,
        )

        if actor is None and author is not None:
            actor = author

        await self._emit(
            guild,
            "Messaggio eliminato",
            staffer=actor,
            user=author,
            channel=channel,
            details={
                "Messaggio ID": payload.message_id,
                "Contenuto": self._clean_text(content, 450),
            },
        )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        actor = await self._find_audit_actor(
            guild,
            discord.AuditLogAction.message_bulk_delete,
            channel_id=payload.channel_id,
        )

        await self._remove_cached_messages(payload.message_ids)

        await self._emit(
            guild,
            "Eliminazione massiva messaggi",
            staffer=actor,
            channel=channel,
            details={"Quantita": len(payload.message_ids)},
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild is None or before.author.bot or before.content == after.content:
            return

        await self._cache_message(after)
        await self._emit(
            before.guild,
            "Messaggio modificato",
            user=before.author,
            channel=before.channel,
            details={
                "Messaggio ID": before.id,
                "Prima": self._clean_text(before.content, 400),
                "Dopo": self._clean_text(after.content, 400),
            },
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild

        if before.nick != after.nick:
            actor = await self._find_audit_actor(
                guild, discord.AuditLogAction.member_update, target_id=after.id
            )
            await self._emit(
                guild,
                "Nickname modificato",
                staffer=actor,
                user=after,
                details={"Prima": before.nick or before.name, "Dopo": after.nick or after.name},
            )

        before_roles = {role.id: role for role in before.roles}
        after_roles = {role.id: role for role in after.roles}
        added = [role for rid, role in after_roles.items() if rid not in before_roles]
        removed = [role for rid, role in before_roles.items() if rid not in after_roles]

        if added or removed:
            actor = await self._find_audit_actor(
                guild, discord.AuditLogAction.member_role_update, target_id=after.id
            )
            if added:
                await self._emit(
                    guild,
                    "Ruolo aggiunto",
                    staffer=actor,
                    user=after,
                    details={"Ruolo": self._display_roles(added)},
                )
            if removed:
                await self._emit(
                    guild,
                    "Ruolo rimosso",
                    staffer=actor,
                    user=after,
                    details={"Ruolo": self._display_roles(removed)},
                )

        if before.timed_out_until != after.timed_out_until:
            actor = await self._find_audit_actor(
                guild, discord.AuditLogAction.member_update, target_id=after.id
            )
            until = (
                after.timed_out_until.astimezone(self._italy_tz).strftime("%d/%m/%Y %H:%M:%S")
                if after.timed_out_until
                else None
            )
            await self._emit(
                guild,
                "Timeout applicato/modificato" if after.timed_out_until else "Timeout rimosso",
                staffer=actor,
                user=after,
                details={"Fino a": until},
            )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild

        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                await self._emit(guild, "Ingresso in vocale", user=member, channel=after.channel)
            elif before.channel is not None and after.channel is None:
                actor = await self._find_audit_actor(guild, discord.AuditLogAction.member_disconnect)
                await self._emit(
                    guild,
                    "Disconnesso dalla vocale" if actor else "Uscita dalla vocale",
                    staffer=actor,
                    user=member,
                    channel=before.channel,
                )
            elif before.channel is not None and after.channel is not None:
                actor = await self._find_audit_actor(guild, discord.AuditLogAction.member_move)
                await self._emit(
                    guild,
                    "Spostato in un altro canale vocale" if actor else "Cambio canale vocale",
                    staffer=actor,
                    user=member,
                    channel=after.channel,
                    details={"Da": before.channel.mention, "A": after.channel.mention},
                )

        for old, new, on, off in (
            (before.mute, after.mute, "Server mute", "Server unmute"),
            (before.deaf, after.deaf, "Server deafen", "Server undeafen"),
        ):
            if old != new:
                actor = await self._find_audit_actor(
                    guild, discord.AuditLogAction.member_update, target_id=member.id
                )
                await self._emit(
                    guild,
                    on if new else off,
                    staffer=actor,
                    user=member,
                    channel=after.channel or before.channel,
                )

        for old, new, on, off in (
            (before.self_mute, after.self_mute, "Self mute", "Self unmute"),
            (before.self_deaf, after.self_deaf, "Self deafen", "Self undeafen"),
            (before.self_stream, after.self_stream, "Streaming avviato", "Streaming terminato"),
            (before.self_video, after.self_video, "Webcam attivata", "Webcam disattivata"),
        ):
            if old != new:
                await self._emit(
                    guild,
                    on if new else off,
                    user=member,
                    channel=after.channel or before.channel,
                )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        actor = await self._find_audit_actor(
            role.guild, discord.AuditLogAction.role_create, target_id=role.id
        )
        await self._emit(
            role.guild,
            "Ruolo creato",
            staffer=actor,
            details={"Ruolo": role.mention, "ID": role.id},
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        actor = await self._find_audit_actor(
            after.guild, discord.AuditLogAction.role_update, target_id=after.id
        )
        details = {"Ruolo": after.mention}
        if before.name != after.name:
            details["Nome"] = f"{before.name} → {after.name}"
        if before.permissions != after.permissions:
            details["Permessi"] = "Modificati"
        if before.colour != after.colour:
            details["Colore"] = f"{before.colour} → {after.colour}"
        await self._emit(after.guild, "Ruolo modificato", staffer=actor, details=details)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        actor = await self._find_audit_actor(
            role.guild, discord.AuditLogAction.role_delete, target_id=role.id
        )
        await self._emit(
            role.guild,
            "Ruolo eliminato",
            staffer=actor,
            details={"Ruolo": role.name, "ID": role.id},
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        actor = await self._find_audit_actor(
            after.guild, discord.AuditLogAction.channel_update, target_id=after.id
        )
        details = {"Canale": after.mention}
        if before.name != after.name:
            details["Nome"] = f"{before.name} → {after.name}"
        before_category = getattr(before, "category", None)
        after_category = getattr(after, "category", None)
        if self._object_id(before_category) != self._object_id(after_category):
            details["Categoria prima"] = before_category.mention if before_category else "—"
            details["Categoria dopo"] = after_category.mention if after_category else "—"
        if getattr(before, "position", None) != getattr(after, "position", None):
            details["Posizione"] = f"{getattr(before, 'position', '—')} → {getattr(after, 'position', '—')}"
        await self._emit(
            after.guild,
            "Canale modificato",
            staffer=actor,
            channel=after,
            details=details,
        )
