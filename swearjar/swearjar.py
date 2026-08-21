import re
import unicodedata
from typing import List

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


DEFAULT_WORDS = [
    "porco dio",
    "dio cane",
    "dio porco",
    "madonna puttana",
    "cazzo",
    "merda",
    "stronzo",
    "stronza",
    "vaffanculo",
    "fanculo",
    "coglione",
    "cogliona",
    "coglioni",
    "testa di cazzo",
    "figlio di puttana",
    "figlia di puttana",
    "puttana",
    "troia",
    "bastardo",
    "bastarda",
]

# Questi termini, da soli, non devono mai fare punteggio.
STANDALONE_IGNORED = {
    "dio",
    "gesu",
    "gesu cristo",
    "allah",
    "madonna",
    "cristo",
}

DEFAULT_REPLY = "{mention} ha bestemmiato per la {count}ª volta."


class SwearJar(commands.Cog):
    """Conta bestemmie/parolacce, risponde al messaggio e mostra una leaderboard."""

    __author__ = "danyx64"
    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=927315640118477221, force_registration=True)
        self.config.register_guild(
            enabled=True,
            words=DEFAULT_WORDS,
            reply_message=DEFAULT_REPLY,
            channel_mode="all",
            channels=[],
        )
        self.config.register_member(count=0)

    async def cog_load(self):
        # Migrazione automatica dalle vecchie configurazioni: rimuove i nomi
        # religiosi che erano stati salvati come trigger autonomi.
        ignored = {self._normalize(term) for term in STANDALONE_IGNORED}
        for guild in self.bot.guilds:
            words = await self.config.guild(guild).words()
            filtered = [word for word in words if self._normalize(word) not in ignored]
            if filtered != words:
                await self.config.guild(guild).words.set(filtered)

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKD", text.casefold())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _raw_normalize(text: str) -> str:
        """Lowercase + rimozione accenti, mantenendo i separatori per il matcher."""
        text = unicodedata.normalize("NFKD", text.casefold())
        return "".join(ch for ch in text if not unicodedata.combining(ch))

    @classmethod
    def _contains_term(cls, content: str, term: str) -> bool:
        term_n = cls._normalize(term)
        if not term_n or term_n in {cls._normalize(x) for x in STANDALONE_IGNORED}:
            return False

        content_raw = cls._raw_normalize(content)
        tokens = term_n.split()

        # Una frase configurata viene riconosciuta sia separata che attaccata:
        # "porco dio", "porcodio", "porco-dio", "porco.dio", ecc.
        if len(tokens) > 1:
            pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(re.escape(token) for token in tokens) + r"(?![a-z0-9])"
            return re.search(pattern, content_raw, flags=re.IGNORECASE) is not None

        # Per una singola parolaccia manteniamo i confini di parola per evitare
        # falsi positivi dentro parole innocue.
        token = re.escape(tokens[0])
        return re.search(rf"(?<![a-z0-9]){token}(?![a-z0-9])", content_raw, flags=re.IGNORECASE) is not None

    async def _channel_allowed(self, guild: discord.Guild, channel_id: int) -> bool:
        mode = await self.config.guild(guild).channel_mode()
        channels = set(await self.config.guild(guild).channels())
        if mode == "all":
            return True
        if mode == "include":
            return channel_id in channels
        if mode == "exclude":
            return channel_id not in channels
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.content:
            return
        if not await self.config.guild(message.guild).enabled():
            return
        if not await self._channel_allowed(message.guild, message.channel.id):
            return

        words = await self.config.guild(message.guild).words()
        matched = next((word for word in words if self._contains_term(message.content, word)), None)
        if matched is None:
            return

        member_group = self.config.member(message.author)
        current = await member_group.count()
        new_count = current + 1
        await member_group.count.set(new_count)

        template = await self.config.guild(message.guild).reply_message()
        reply = template.format(
            mention=message.author.mention,
            user=message.author.mention,
            username=message.author.name,
            displayname=message.author.display_name,
            user_id=message.author.id,
            count=new_count,
            word=matched,
            channel=getattr(message.channel, "mention", f"#{message.channel}"),
            guild=message.guild.name,
            server=message.guild.name,
        )
        try:
            await message.reply(reply[:2000], mention_author=False, allowed_mentions=discord.AllowedMentions(users=True))
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.group(name="swearjar", aliases=["swear"], invoke_without_command=True)
    @commands.guild_only()
    async def swearjar(self, ctx: commands.Context):
        """Configura il contatore di bestemmie/parolacce."""
        await ctx.send_help(ctx.command)

    @swearjar.command(name="enable")
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_enable(self, ctx: commands.Context):
        """Abilita il controllo dei messaggi."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("SwearJar abilitato.")

    @swearjar.command(name="disable")
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_disable(self, ctx: commands.Context):
        """Disabilita il controllo dei messaggi."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("SwearJar disabilitato.")

    @swearjar.command(name="status")
    async def swear_status(self, ctx: commands.Context):
        """Mostra configurazione attuale e numero di parole controllate."""
        enabled = await self.config.guild(ctx.guild).enabled()
        mode = await self.config.guild(ctx.guild).channel_mode()
        channels = await self.config.guild(ctx.guild).channels()
        words = await self.config.guild(ctx.guild).words()
        await ctx.send(
            f"Stato: **{'attivo' if enabled else 'disattivato'}**\n"
            f"Modalità canali: **{mode}**\n"
            f"Canali configurati: `{len(channels)}`\n"
            f"Parole/frasi controllate: `{len(words)}`"
        )

    @swearjar.group(name="message", invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_message(self, ctx: commands.Context):
        """Visualizza o modifica il messaggio di risposta."""
        await ctx.send_help(ctx.command)

    @swear_message.command(name="view")
    async def swear_message_view(self, ctx: commands.Context):
        """Mostra il messaggio automatico impostato."""
        value = await self.config.guild(ctx.guild).reply_message()
        await ctx.send(f"Messaggio attuale:\n```\n{value}\n```")

    @swear_message.command(name="set")
    async def swear_message_set(self, ctx: commands.Context, *, text: str):
        """Imposta la risposta automatica inviata al messaggio rilevato."""
        await self.config.guild(ctx.guild).reply_message.set(text[:2000])
        await ctx.send("Messaggio aggiornato.")

    @swear_message.command(name="reset")
    async def swear_message_reset(self, ctx: commands.Context):
        """Ripristina `{mention} ha bestemmiato per la {count}ª volta.`"""
        await self.config.guild(ctx.guild).reply_message.set(DEFAULT_REPLY)
        await ctx.send("Messaggio ripristinato.")

    @swear_message.command(name="usage")
    async def swear_message_usage(self, ctx: commands.Context):
        """Mostra i placeholder disponibili nel messaggio."""
        await ctx.send(
            "Placeholder: `{mention}`, `{user}`, `{username}`, `{displayname}`, `{user_id}`, "
            "`{count}`, `{word}`, `{channel}`, `{guild}`, `{server}`."
        )

    @swearjar.group(name="words", aliases=["parole"], invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_words(self, ctx: commands.Context):
        """Gestisce bestemmie e parolacce rilevate."""
        await ctx.send_help(ctx.command)

    @swear_words.command(name="list")
    async def swear_words_list(self, ctx: commands.Context):
        """Elenca tutte le parole/frasi controllate."""
        words = await self.config.guild(ctx.guild).words()
        if not words:
            return await ctx.send("Nessuna parola configurata.")
        text = "\n".join(f"`{i}.` {word}" for i, word in enumerate(words, 1))
        for start in range(0, len(text), 1800):
            await ctx.send(text[start:start + 1800])

    @swear_words.command(name="add")
    async def swear_words_add(self, ctx: commands.Context, *, term: str):
        """Aggiunge una parola o frase da rilevare."""
        term = term.strip()
        if not term:
            return await ctx.send("Inserisci una parola o frase.")
        if self._normalize(term) in {self._normalize(x) for x in STANDALONE_IGNORED}:
            return await ctx.send("Quel termine religioso da solo non viene conteggiato. Aggiungi una frase completa, ad esempio `porco dio`.")
        async with self.config.guild(ctx.guild).words() as words:
            normalized = {self._normalize(w) for w in words}
            if self._normalize(term) in normalized:
                return await ctx.send("Questa parola/frase è già presente.")
            words.append(term)
        await ctx.send(f"Aggiunta: `{term}`")

    @swear_words.command(name="remove", aliases=["del", "delete"])
    async def swear_words_remove(self, ctx: commands.Context, *, term: str):
        """Rimuove una parola o frase dalla lista."""
        target = self._normalize(term)
        async with self.config.guild(ctx.guild).words() as words:
            index = next((i for i, w in enumerate(words) if self._normalize(w) == target), None)
            if index is None:
                return await ctx.send("Parola/frase non trovata.")
            removed = words.pop(index)
        await ctx.send(f"Rimossa: `{removed}`")

    @swear_words.command(name="reset")
    async def swear_words_reset(self, ctx: commands.Context):
        """Ripristina la lista predefinita di bestemmie/parolacce."""
        await self.config.guild(ctx.guild).words.set(DEFAULT_WORDS)
        await ctx.send("Lista predefinita ripristinata.")

    @swearjar.group(name="channels", aliases=["canali"], invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_channels(self, ctx: commands.Context):
        """Configura in quali canali SwearJar ascolta."""
        await ctx.send_help(ctx.command)

    @swear_channels.command(name="mode")
    async def swear_channels_mode(self, ctx: commands.Context, mode: str):
        """Imposta `all`, `include` (solo lista) o `exclude` (tutti tranne lista)."""
        mode = mode.lower().strip()
        if mode not in {"all", "include", "exclude"}:
            return await ctx.send("Modalità valida: `all`, `include`, `exclude`.")
        await self.config.guild(ctx.guild).channel_mode.set(mode)
        await ctx.send(f"Modalità canali impostata su **{mode}**.")

    @swear_channels.command(name="add")
    async def swear_channels_add(self, ctx: commands.Context, channel_id: int):
        """Aggiunge un canale alla lista include/exclude usando l'ID."""
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            return await ctx.send("Canale non trovato.")
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel_id not in channels:
                channels.append(channel_id)
        await ctx.send(f"Canale aggiunto: {getattr(channel, 'mention', channel.name)}")

    @swear_channels.command(name="remove")
    async def swear_channels_remove(self, ctx: commands.Context, channel_id: int):
        """Rimuove un canale dalla lista include/exclude."""
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel_id not in channels:
                return await ctx.send("Quel canale non è nella lista.")
            channels.remove(channel_id)
        await ctx.send("Canale rimosso dalla lista.")

    @swear_channels.command(name="list")
    async def swear_channels_list(self, ctx: commands.Context):
        """Mostra modalità e canali configurati."""
        mode = await self.config.guild(ctx.guild).channel_mode()
        ids = await self.config.guild(ctx.guild).channels()
        lines: List[str] = []
        for cid in ids:
            channel = ctx.guild.get_channel(cid)
            lines.append(f"{getattr(channel, 'mention', None) or '`'+str(cid)+'`'}")
        await ctx.send(f"Modalità: **{mode}**\n" + ("\n".join(lines) if lines else "Nessun canale in lista."))

    @commands.command(name="leadswear")
    @commands.guild_only()
    async def leadswear(self, ctx: commands.Context):
        """Mostra la leaderboard pubblica Top 10 di bestemmie/parolacce."""
        all_members = await self.config.all_members(ctx.guild)
        ranking = sorted(
            ((int(uid), data.get("count", 0)) for uid, data in all_members.items() if data.get("count", 0) > 0),
            key=lambda item: item[1],
            reverse=True,
        )[:10]
        if not ranking:
            return await ctx.send("La leaderboard è ancora vuota.")

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, (uid, count) in enumerate(ranking, 1):
            member = ctx.guild.get_member(uid)
            name = member.mention if member else f"`{uid}`"
            prefix = medals[index - 1] if index <= 3 else f"**{index}.**"
            lines.append(f"{prefix} {name} — **{count}**")

        embed = discord.Embed(
            title="🏆 Classifica Swear Jar",
            description="\n".join(lines),
            colour=discord.Colour.gold(),
        )
        embed.set_footer(text="Top 10 bestemmie/parolacce")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
