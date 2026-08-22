import re
import unicodedata
from typing import List

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


DEFAULT_DEITIES = [
    "dio", "gesu", "gesu cristo", "cristo", "madonna", "allah",
    "signore", "padre eterno", "spirito santo", "vergine maria", "maria",
]

# Lista moderazione: da sola NON fa punteggio. Serve sempre anche una divinita'.
DEFAULT_PROFANITIES = [
    "cazzo", "cazzi", "cazzone", "cazzata", "cazzate", "minchia", "minchione",
    "merda", "merde", "stronzo", "stronza", "stronzi", "stronze",
    "vaffanculo", "fanculo", "affanculo", "fottiti", "fottere", "fottuto", "fottuta",
    "coglione", "cogliona", "coglioni", "coglionazzo", "coglionata",
    "puttana", "puttane", "troia", "troie", "zoccola", "zoccole",
    "bastardo", "bastarda", "bastardi", "bastarde", "figlio di puttana", "figlia di puttana",
    "testa di cazzo", "pezzo di merda", "faccia di merda", "rompicoglioni",
    "porco", "porca", "porci", "porche", "cane", "cagna", "maiale", "maiala",
    "idiota", "imbecille", "deficiente", "cretino", "cretina", "scemo", "scema",
    "ritardato", "ritardata", "mongoloide", "mongolo", "mongola", "down",
    "negro", "negra", "negri", "negre", "nigger", "nigga",
    "frocio", "frocia", "froci", "finocchio", "ricchione", "checca",
    "terrone", "terrona", "terroni", "zingaro", "zingara", "zingari", "rom di merda",
    "handicappato", "handicappata", "minorato", "minorata",
    "suca", "succhia", "succhiami", "inculato", "inculata", "inculare",
    "culo", "culone", "palle", "pallone", "pisello", "fica", "figa", "fessa",
    "mignotta", "bagascia", "baldracca", "vacca", "cesso", "cacata", "cagata",
    "fuck", "fucking", "fucker", "motherfucker", "shit", "bullshit", "asshole",
    "bitch", "slut", "whore", "dick", "cock", "cunt", "prick", "retard",
]

DEFAULT_REPLY = "{mention} ha bestemmiato per la {count}ª volta."


class SwearJar(commands.Cog):
    """Conta solo messaggi che contengono sia una divinita' sia una parolaccia."""

    __author__ = "danyx64"
    __version__ = "2.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=927315640118477221, force_registration=True)
        self.config.register_guild(
            enabled=True,
            words=[],  # mantenuto per compatibilita' con vecchie config
            deities=DEFAULT_DEITIES,
            profanities=DEFAULT_PROFANITIES,
            reply_message=DEFAULT_REPLY,
            channel_mode="all",
            channels=[],
        )
        self.config.register_member(count=0)

    async def cog_load(self):
        # Se la nuova configurazione e' vuota, ripristina i dizionari moderni.
        for guild in self.bot.guilds:
            if not await self.config.guild(guild).deities():
                await self.config.guild(guild).deities.set(DEFAULT_DEITIES)
            if not await self.config.guild(guild).profanities():
                await self.config.guild(guild).profanities.set(DEFAULT_PROFANITIES)

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKD", text.casefold())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}))
        text = re.sub(r"[^a-z]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _contains_term(cls, content: str, term: str) -> bool:
        content_n = cls._normalize(content)
        term_n = cls._normalize(term)
        if not term_n:
            return False
        tokens = term_n.split()
        pattern = r"(?<![a-z])" + r"\s*".join(re.escape(token) for token in tokens) + r"(?![a-z])"
        return re.search(pattern, content_n) is not None

    @classmethod
    def _find_violation(cls, content: str, deities: List[str], profanities: List[str]):
        deity = next((d for d in deities if cls._contains_term(content, d)), None)
        profanity = next((p for p in profanities if cls._contains_term(content, p)), None)
        if deity and profanity:
            return deity, profanity

        # Secondo passaggio per forme attaccate tipo "porcodio", "diocane", ecc.
        compact = cls._normalize(content).replace(" ", "")
        for d in deities:
            d_n = cls._normalize(d).replace(" ", "")
            if not d_n:
                continue
            for p in profanities:
                p_n = cls._normalize(p).replace(" ", "")
                if not p_n:
                    continue
                if d_n + p_n in compact or p_n + d_n in compact:
                    return d, p
        return None

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

        deities = await self.config.guild(message.guild).deities()
        profanities = await self.config.guild(message.guild).profanities()
        matched = self._find_violation(message.content, deities, profanities)
        if matched is None:
            return
        deity, profanity = matched

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
            word=f"{deity} + {profanity}",
            deity=deity,
            profanity=profanity,
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
        """Configura il contatore bestemmie: divinita' + parolaccia."""
        await ctx.send_help(ctx.command)

    @swearjar.command(name="enable")
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("SwearJar abilitato.")

    @swearjar.command(name="disable")
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("SwearJar disabilitato.")

    @swearjar.command(name="status")
    async def swear_status(self, ctx: commands.Context):
        enabled = await self.config.guild(ctx.guild).enabled()
        mode = await self.config.guild(ctx.guild).channel_mode()
        channels = await self.config.guild(ctx.guild).channels()
        deities = await self.config.guild(ctx.guild).deities()
        profanities = await self.config.guild(ctx.guild).profanities()
        await ctx.send(
            f"Stato: **{'attivo' if enabled else 'disattivato'}**\n"
            f"Regola: **serve sempre divinita' + parolaccia nello stesso messaggio**\n"
            f"Divinita': `{len(deities)}` | Parolacce/insulti: `{len(profanities)}`\n"
            f"Modalita' canali: **{mode}** | Canali configurati: `{len(channels)}`"
        )

    @swearjar.group(name="message", invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_message(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @swear_message.command(name="view")
    async def swear_message_view(self, ctx: commands.Context):
        value = await self.config.guild(ctx.guild).reply_message()
        await ctx.send(f"Messaggio attuale:\n```\n{value}\n```")

    @swear_message.command(name="set")
    async def swear_message_set(self, ctx: commands.Context, *, text: str):
        await self.config.guild(ctx.guild).reply_message.set(text[:2000])
        await ctx.send("Messaggio aggiornato.")

    @swear_message.command(name="reset")
    async def swear_message_reset(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).reply_message.set(DEFAULT_REPLY)
        await ctx.send("Messaggio ripristinato.")

    @swear_message.command(name="usage")
    async def swear_message_usage(self, ctx: commands.Context):
        await ctx.send(
            "Placeholder: `{mention}`, `{user}`, `{username}`, `{displayname}`, `{user_id}`, "
            "`{count}`, `{word}`, `{deity}`, `{profanity}`, `{channel}`, `{guild}`, `{server}`."
        )

    @swearjar.group(name="deities", aliases=["divinita"], invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_deities(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @swear_deities.command(name="list")
    async def swear_deities_list(self, ctx: commands.Context):
        values = await self.config.guild(ctx.guild).deities()
        await ctx.send("Divinita': " + ", ".join(f"`{x}`" for x in values))

    @swear_deities.command(name="add")
    async def swear_deities_add(self, ctx: commands.Context, *, term: str):
        term = term.strip()
        if not term:
            return await ctx.send("Inserisci un termine.")
        async with self.config.guild(ctx.guild).deities() as values:
            if self._normalize(term) in {self._normalize(x) for x in values}:
                return await ctx.send("Gia' presente.")
            values.append(term)
        await ctx.send(f"Divinita' aggiunta: `{term}`")

    @swear_deities.command(name="remove")
    async def swear_deities_remove(self, ctx: commands.Context, *, term: str):
        target = self._normalize(term)
        async with self.config.guild(ctx.guild).deities() as values:
            index = next((i for i, x in enumerate(values) if self._normalize(x) == target), None)
            if index is None:
                return await ctx.send("Non trovata.")
            removed = values.pop(index)
        await ctx.send(f"Rimossa: `{removed}`")

    @swear_deities.command(name="reset")
    async def swear_deities_reset(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).deities.set(DEFAULT_DEITIES)
        await ctx.send("Lista divinita' ripristinata.")

    @swearjar.group(name="profanities", aliases=["words", "parole", "parolacce"], invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_profanities(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @swear_profanities.command(name="list")
    async def swear_profanities_list(self, ctx: commands.Context):
        values = await self.config.guild(ctx.guild).profanities()
        text = "\n".join(f"`{i}.` {word}" for i, word in enumerate(values, 1))
        for start in range(0, len(text), 1800):
            await ctx.send(text[start:start + 1800])

    @swear_profanities.command(name="add")
    async def swear_profanities_add(self, ctx: commands.Context, *, term: str):
        term = term.strip()
        if not term:
            return await ctx.send("Inserisci una parola o frase.")
        async with self.config.guild(ctx.guild).profanities() as values:
            if self._normalize(term) in {self._normalize(x) for x in values}:
                return await ctx.send("Gia' presente.")
            values.append(term)
        await ctx.send(f"Aggiunta: `{term}`")

    @swear_profanities.command(name="remove", aliases=["del", "delete"])
    async def swear_profanities_remove(self, ctx: commands.Context, *, term: str):
        target = self._normalize(term)
        async with self.config.guild(ctx.guild).profanities() as values:
            index = next((i for i, x in enumerate(values) if self._normalize(x) == target), None)
            if index is None:
                return await ctx.send("Parola/frase non trovata.")
            removed = values.pop(index)
        await ctx.send(f"Rimossa: `{removed}`")

    @swear_profanities.command(name="reset")
    async def swear_profanities_reset(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).profanities.set(DEFAULT_PROFANITIES)
        await ctx.send("Lista parolacce/insulti ripristinata.")

    @swearjar.group(name="channels", aliases=["canali"], invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_channels(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @swear_channels.command(name="mode")
    async def swear_channels_mode(self, ctx: commands.Context, mode: str):
        mode = mode.lower().strip()
        if mode not in {"all", "include", "exclude"}:
            return await ctx.send("Modalita' valida: `all`, `include`, `exclude`.")
        await self.config.guild(ctx.guild).channel_mode.set(mode)
        await ctx.send(f"Modalita' canali impostata su **{mode}**.")

    @swear_channels.command(name="add")
    async def swear_channels_add(self, ctx: commands.Context, channel_id: int):
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            return await ctx.send("Canale non trovato.")
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel_id not in channels:
                channels.append(channel_id)
        await ctx.send(f"Canale aggiunto: {getattr(channel, 'mention', channel.name)}")

    @swear_channels.command(name="remove")
    async def swear_channels_remove(self, ctx: commands.Context, channel_id: int):
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel_id not in channels:
                return await ctx.send("Quel canale non e' nella lista.")
            channels.remove(channel_id)
        await ctx.send("Canale rimosso dalla lista.")

    @swear_channels.command(name="list")
    async def swear_channels_list(self, ctx: commands.Context):
        mode = await self.config.guild(ctx.guild).channel_mode()
        ids = await self.config.guild(ctx.guild).channels()
        lines: List[str] = []
        for cid in ids:
            channel = ctx.guild.get_channel(cid)
            lines.append(f"{getattr(channel, 'mention', None) or '`'+str(cid)+'`'}")
        await ctx.send(f"Modalita': **{mode}**\n" + ("\n".join(lines) if lines else "Nessun canale in lista."))

    @commands.command(name="leadswear")
    @commands.guild_only()
    async def leadswear(self, ctx: commands.Context):
        all_members = await self.config.all_members(ctx.guild)
        ranking = sorted(
            ((int(uid), data.get("count", 0)) for uid, data in all_members.items() if data.get("count", 0) > 0),
            key=lambda item: item[1],
            reverse=True,
        )[:10]
        if not ranking:
            return await ctx.send("La leaderboard e' ancora vuota.")

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
        embed.set_footer(text="Top 10 bestemmie rilevate")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
