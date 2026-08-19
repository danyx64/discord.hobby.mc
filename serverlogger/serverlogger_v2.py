import asyncio
from typing import Optional

import discord
from redbot.core import commands

from .serverlogger import ServerLogger as BaseServerLogger


class ServerLogger(BaseServerLogger):
    """ServerLogger v1.2: invio affidabile e embed semplice a lista."""

    __version__ = "1.2.0"
    MESSAGE_CACHE_MAX_PER_GUILD = 10000

    def __init__(self, bot):
        super().__init__(bot)
        self._init_message_cache()

    def _init_message_cache(self):
        with self._connect() as db:
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

    def _display_member(self, guild: discord.Guild, object_id: Optional[int]) -> str:
        if not object_id:
            return "—"
        member = guild.get_member(object_id)
        if member is not None:
            return discord.utils.escape_markdown(member.display_name)
        user = self.bot.get_user(object_id)
        if user is not None:
            return discord.utils.escape_markdown(user.name)
        return str(object_id)

    @staticmethod
    def _display_channel(guild: discord.Guild, channel_id: Optional[int]) -> str:
        if not channel_id:
            return "—"
        channel = guild.get_channel(channel_id) or guild.get_thread(channel_id)
        if channel is not None:
            return f"#{discord.utils.escape_markdown(channel.name)}"
        return str(channel_id)

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
        return discord.Embed(description=self._clean_text("\n".join(lines), 4000), colour=discord.Colour.blurple())

    async def _emit(self, guild, action, *, staffer=None, user=None, channel=None, details=None, when=None):
        if guild is None or not await self.config.guild(guild).enabled():
            return
        when = when or discord.utils.utcnow()
        staffer_id = self._object_id(staffer)
        user_id = self._object_id(user)
        channel_id = self._object_id(channel)
        log_id = await self._insert_log(guild.id, action, staffer_id, user_id, channel_id, when, details)
        cid = await self.config.guild(guild).log_channel_id()
        log_channel = guild.get_channel(int(cid)) if cid else None
        if not isinstance(log_channel, (discord.TextChannel, discord.Thread)):
            return
        embed = self._make_embed(guild, log_id, action, staffer_id, user_id, channel_id, when, details)
        for attempt in range(3):
            try:
                await log_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.Forbidden:
                return
            except discord.HTTPException:
                if attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))

    async def _find_audit_actor(self, guild, action, *, target_id=None, channel_id=None):
        if guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None
        for delay in (0, 0.65, 1.25):
            if delay:
                await asyncio.sleep(delay)
            actor = await super()._find_audit_actor(guild, action, target_id=target_id, channel_id=channel_id)
            if actor is not None:
                return actor
        return None

    async def _cache_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        async with self._db_lock:
            await asyncio.to_thread(self._cache_message_sync, message.id, message.guild.id, message.author.id, message.channel.id, message.content or "", discord.utils.utcnow().isoformat())

    def _cache_message_sync(self, message_id, guild_id, author_id, channel_id, content, created_at):
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO message_cache (message_id, guild_id, author_id, channel_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?)", (message_id, guild_id, author_id, channel_id, content, created_at))
            db.execute("DELETE FROM message_cache WHERE guild_id = ? AND message_id NOT IN (SELECT message_id FROM message_cache WHERE guild_id = ? ORDER BY message_id DESC LIMIT ?)", (guild_id, guild_id, self.MESSAGE_CACHE_MAX_PER_GUILD))
            db.commit()

    async def _pop_cached_message(self, message_id: int):
        async with self._db_lock:
            return await asyncio.to_thread(self._pop_cached_message_sync, message_id)

    def _pop_cached_message_sync(self, message_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM message_cache WHERE message_id = ?", (message_id,)).fetchone()
            db.execute("DELETE FROM message_cache WHERE message_id = ?", (message_id,))
            db.commit()
            return row

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
        actor = await self._find_audit_actor(guild, discord.AuditLogAction.message_delete, target_id=author_id, channel_id=payload.channel_id)
        if actor is None and author is not None:
            actor = author
        await self._emit(guild, "Messaggio eliminato", staffer=actor, user=author, channel=channel, details={"Messaggio ID": payload.message_id, "Contenuto": self._clean_text(content, 450)})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        actor = await self._find_audit_actor(guild, discord.AuditLogAction.message_bulk_delete, channel_id=payload.channel_id)
        for message_id in payload.message_ids:
            await self._pop_cached_message(message_id)
        await self._emit(guild, "Eliminazione massiva messaggi", staffer=actor, channel=channel, details={"Quantita": len(payload.message_ids)})

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        await self._cache_message(after)
        await self._emit(before.guild, "Messaggio modificato", user=before.author, channel=before.channel, details={"Messaggio ID": before.id, "Prima": self._clean_text(before.content, 400), "Dopo": self._clean_text(after.content, 400)})
