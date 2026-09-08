import asyncio
import re
from typing import List, Optional, Tuple

import discord
from discord.http import Route
from redbot.core import Config, commands


CUSTOM_EMOJI_RE = re.compile(r"^<a?:([A-Za-z0-9_]+):(\d+)>$")
REACTION_PREFIXES = {
    "normal": "normal",
    "n": "normal",
    "burst": "burst",
    "super": "burst",
    "s": "burst",
}


class AutoReactions(commands.Cog):
    """Reazioni automatiche normali e BURST per canali e utenti specifici."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=64642026090801, force_registration=True
        )
        self.config.register_guild(
            enabled=True,
            channel_rules={},
            user_rules={},
        )

    @staticmethod
    def _unique(items: List[str]) -> List[str]:
        return list(dict.fromkeys(items))

    @staticmethod
    def _split_reaction_spec(raw: str) -> Tuple[str, str]:
        raw = raw.strip()
        if ":" in raw:
            prefix, value = raw.split(":", 1)
            reaction_type = REACTION_PREFIXES.get(prefix.lower())
            if reaction_type and value:
                return reaction_type, value.strip()
        # Retrocompatibilita: tutte le vecchie configurazioni senza prefisso
        # continuano a essere reazioni normali.
        return "normal", raw

    @classmethod
    def _normalize_spec(cls, raw: str) -> str:
        reaction_type, emoji = cls._split_reaction_spec(raw)
        return f"{reaction_type}:{emoji}"

    @classmethod
    def _display_spec(cls, raw: str) -> str:
        reaction_type, emoji = cls._split_reaction_spec(raw)
        marker = "⚡" if reaction_type == "burst" else "•"
        return f"{marker}{emoji}"

    @staticmethod
    def _emoji_from_text(raw: str):
        raw = raw.strip()
        match = CUSTOM_EMOJI_RE.match(raw)
        if match:
            return discord.PartialEmoji(
                name=match.group(1),
                id=int(match.group(2)),
                animated=raw.startswith("<a:"),
            )
        return raw

    @staticmethod
    def _emoji_api_key(raw: str) -> str:
        raw = raw.strip()
        match = CUSTOM_EMOJI_RE.match(raw)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
        return raw

    async def _validate_reaction_spec(self, guild: discord.Guild, raw: str):
        reaction_type, emoji = self._split_reaction_spec(raw)
        if reaction_type not in {"normal", "burst"}:
            return False, "Tipo reazione non valido. Usa `normal:` oppure `burst:`."
        if not emoji:
            return False, "Emoji vuota."

        match = CUSTOM_EMOJI_RE.match(emoji)
        if match:
            emoji_id = int(match.group(2))
            cached = self.bot.get_emoji(emoji_id)
            if cached is None:
                return False, (
                    "Non trovo questa emoji nella cache del bot. Il bot deve avere accesso "
                    "all'emoji personalizzata."
                )
        return True, None

    async def _resolve_text_channel(self, ctx, raw: str) -> Optional[discord.TextChannel]:
        value = raw.strip()
        if value.startswith("<#") and value.endswith(">"):
            value = value[2:-1]

        try:
            channel_id = int(value)
        except ValueError:
            return discord.utils.get(ctx.guild.text_channels, name=value.lstrip("#"))

        channel = ctx.guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _resolve_member(self, ctx, raw: str) -> Optional[discord.Member]:
        value = raw.strip()
        if value.startswith("<@") and value.endswith(">"):
            value = value[2:-1].lstrip("!")

        try:
            user_id = int(value)
        except ValueError:
            member = discord.utils.get(ctx.guild.members, name=value)
            if member is None:
                member = discord.utils.get(ctx.guild.members, display_name=value)
            return member

        member = ctx.guild.get_member(user_id)
        if member is None:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return member

    async def _reaction_specs_for(self, message: discord.Message) -> List[str]:
        data = await self.config.guild(message.guild).all()
        if not data["enabled"]:
            return []

        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        reactions = []

        channel_rule = data["channel_rules"].get(channel_id)
        if channel_rule:
            reactions.extend(channel_rule.get("reactions", []))

        user_rule = data["user_rules"].get(user_id)
        if user_rule:
            allowed_channels = [str(x) for x in user_rule.get("channels", [])]
            if not allowed_channels or channel_id in allowed_channels:
                reactions.extend(user_rule.get("reactions", []))

        # Normalizza anche le vecchie entry senza prefisso.
        return self._unique([self._normalize_spec(x) for x in reactions])

    async def _add_normal_reaction(self, message: discord.Message, emoji: str) -> Tuple[bool, str]:
        try:
            await message.add_reaction(self._emoji_from_text(emoji))
            return True, "ok"
        except discord.Forbidden:
            return False, "Discord ha negato il permesso di aggiungere reazioni"
        except discord.NotFound:
            return False, "Messaggio o emoji non trovato"
        except discord.HTTPException as exc:
            return False, f"HTTP {getattr(exc, 'status', '?')}: {exc}"

    async def _add_burst_reaction(self, message: discord.Message, emoji: str) -> Tuple[bool, str]:
        """Invia una super-reazione usando gli endpoint BURST del client Discord.

        Discord non documenta ancora ufficialmente la creazione BURST per bot.
        Usiamo per prima la variante `type=1` e poi due fallback osservati in
        implementazioni client compatibili.
        """
        api_key = self._emoji_api_key(emoji)
        common = {
            "channel_id": message.channel.id,
            "message_id": message.id,
            "emoji": api_key,
        }

        attempts = [
            (
                Route(
                    "PUT",
                    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
                    **common,
                ),
                {"location": "Message Inline Button", "type": 1},
                "type=1",
            ),
            (
                Route(
                    "PUT",
                    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/1/@me",
                    **common,
                ),
                {"location": "Message Inline Button", "burst": "true"},
                "typed burst fallback",
            ),
            (
                Route(
                    "PUT",
                    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
                    **common,
                ),
                {"burst": "true"},
                "burst=true fallback",
            ),
        ]

        last_error = "endpoint BURST rifiutato"
        for route, params, label in attempts:
            try:
                await self.bot.http.request(route, params=params)
                return True, label
            except discord.Forbidden:
                return False, "Discord ha negato il permesso di aggiungere la super-reazione"
            except discord.NotFound:
                last_error = "Messaggio, canale o emoji non trovato"
            except discord.HTTPException as exc:
                status = getattr(exc, "status", None)
                last_error = f"{label}: HTTP {status or '?'} - {exc}"
                # Prova il fallback solo per errori che possono indicare endpoint/parametri non accettati.
                if status not in {400, 404, 405}:
                    break

        return False, last_error

    async def _add_reaction_specs(self, message: discord.Message, reactions: List[str]):
        for raw in reactions:
            reaction_type, emoji = self._split_reaction_spec(raw)
            if reaction_type == "burst":
                await self._add_burst_reaction(message, emoji)
            else:
                await self._add_normal_reaction(message, emoji)
            await asyncio.sleep(0.15)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        reactions = await self._reaction_specs_for(message)
        if reactions:
            await self._add_reaction_specs(message, reactions)

    @commands.group(name="autoreact", aliases=["ar", "autoreactions"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def autoreact(self, ctx):
        """Configura auto-reazioni normali e super-reazioni BURST."""
        await ctx.send_help()

    @autoreact.command(name="on", aliases=["attiva", "enable"])
    async def autoreact_on(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ Auto-reazioni **attivate**.")

    @autoreact.command(name="off", aliases=["disattiva", "disable"])
    async def autoreact_off(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("⛔ Auto-reazioni **disattivate**. La configurazione è stata mantenuta.")

    @autoreact.group(name="channel", aliases=["canale", "ch"], invoke_without_command=True)
    async def autoreact_channel(self, ctx):
        """Gestisce le regole applicate a tutti i messaggi di un canale."""
        await ctx.send_help()

    @autoreact_channel.command(name="add", aliases=["aggiungi"])
    async def channel_add(self, ctx, channel: str, *reactions: str):
        """Aggiunge reazioni. Formati: 👍, normal:👍, burst:🔥, super:❤️."""
        target = await self._resolve_text_channel(ctx, channel)
        if target is None:
            await ctx.send("❌ Canale testuale non trovato. Usa mention, nome o ID.")
            return
        if not reactions:
            await ctx.send("❌ Devi indicare almeno una emoji/reazione.")
            return

        normalized = []
        for reaction in reactions:
            ok, error = await self._validate_reaction_spec(ctx.guild, reaction)
            if not ok:
                await ctx.send(f"❌ `{reaction}`: {error}")
                return
            normalized.append(self._normalize_spec(reaction))

        rules = await self.config.guild(ctx.guild).channel_rules()
        key = str(target.id)
        current = rules.get(key, {"reactions": []})
        existing = [self._normalize_spec(x) for x in current.get("reactions", [])]
        current["reactions"] = self._unique(existing + normalized)
        rules[key] = current
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send(
            f"✅ Regola aggiornata per {target.mention}.\n"
            f"Reazioni: {' '.join(self._display_spec(x) for x in current['reactions'])}"
        )

    @autoreact_channel.command(name="remove", aliases=["rimuovi", "del"])
    async def channel_remove(self, ctx, channel: str, reaction: str = None):
        target = await self._resolve_text_channel(ctx, channel)
        if target is None:
            await ctx.send("❌ Canale testuale non trovato.")
            return

        rules = await self.config.guild(ctx.guild).channel_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Questo canale non ha regole configurate.")
            return

        if reaction is None:
            del rules[key]
            await self.config.guild(ctx.guild).channel_rules.set(rules)
            await ctx.send(f"✅ Regola eliminata da {target.mention}.")
            return

        wanted = self._normalize_spec(reaction)
        configured = [self._normalize_spec(x) for x in rules[key].get("reactions", [])]
        if wanted not in configured:
            await ctx.send("❌ Questa reazione non è configurata per il canale.")
            return
        configured.remove(wanted)
        if configured:
            rules[key]["reactions"] = configured
        else:
            del rules[key]
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send(f"✅ Reazione `{wanted}` rimossa da {target.mention}.")

    @autoreact.group(name="user", aliases=["utente", "usr"], invoke_without_command=True)
    async def autoreact_user(self, ctx):
        """Gestisce le auto-reazioni per utenti specifici."""
        await ctx.send_help()

    @autoreact_user.command(name="add", aliases=["aggiungi"])
    async def user_add(self, ctx, user: str, *reactions: str):
        """Aggiunge reazioni a un utente. Valgono in tutti i canali finche non li limiti."""
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato. Usa mention, nome o ID.")
            return
        if not reactions:
            await ctx.send("❌ Devi indicare almeno una emoji/reazione.")
            return

        normalized = []
        for reaction in reactions:
            ok, error = await self._validate_reaction_spec(ctx.guild, reaction)
            if not ok:
                await ctx.send(f"❌ `{reaction}`: {error}")
                return
            normalized.append(self._normalize_spec(reaction))

        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        current = rules.get(key, {"reactions": [], "channels": []})
        existing = [self._normalize_spec(x) for x in current.get("reactions", [])]
        current["reactions"] = self._unique(existing + normalized)
        current.setdefault("channels", [])
        rules[key] = current
        await self.config.guild(ctx.guild).user_rules.set(rules)
        scope = "tutti i canali" if not current["channels"] else f"{len(current['channels'])} canali selezionati"
        await ctx.send(
            f"✅ Regola aggiornata per {member.mention}.\n"
            f"Reazioni: {' '.join(self._display_spec(x) for x in current['reactions'])}\n"
            f"Ambito: **{scope}**"
        )

    @autoreact_user.command(name="remove", aliases=["rimuovi", "del"])
    async def user_remove(self, ctx, user: str, reaction: str = None):
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato.")
            return

        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Questo utente non ha regole configurate.")
            return

        if reaction is None:
            del rules[key]
            await self.config.guild(ctx.guild).user_rules.set(rules)
            await ctx.send(f"✅ Regola eliminata per {member.mention}.")
            return

        wanted = self._normalize_spec(reaction)
        configured = [self._normalize_spec(x) for x in rules[key].get("reactions", [])]
        if wanted not in configured:
            await ctx.send("❌ Questa reazione non è configurata per l'utente.")
            return
        configured.remove(wanted)
        if configured:
            rules[key]["reactions"] = configured
        else:
            del rules[key]
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ Reazione `{wanted}` rimossa da {member.mention}.")

    @autoreact_user.command(name="channel", aliases=["canale", "ch"])
    async def user_channel(self, ctx, user: str, channel: str):
        member = await self._resolve_member(ctx, user)
        target = await self._resolve_text_channel(ctx, channel)
        if member is None:
            await ctx.send("❌ Utente non trovato.")
            return
        if target is None:
            await ctx.send("❌ Canale testuale non trovato.")
            return

        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Prima aggiungi l'utente con `[p]ar user add <utente> <emoji...>`.")
            return

        channels = [str(x) for x in rules[key].get("channels", [])]
        channel_id = str(target.id)
        if channel_id not in channels:
            channels.append(channel_id)
        rules[key]["channels"] = channels
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ {target.mention} aggiunto ai canali di {member.mention}.")

    @autoreact_user.command(name="unchannel", aliases=["rimuovicanale", "rmchannel"])
    async def user_unchannel(self, ctx, user: str, channel: str):
        member = await self._resolve_member(ctx, user)
        target = await self._resolve_text_channel(ctx, channel)
        if member is None or target is None:
            await ctx.send("❌ Utente o canale non trovato.")
            return

        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Questo utente non ha regole configurate.")
            return

        channels = [str(x) for x in rules[key].get("channels", [])]
        channel_id = str(target.id)
        if channel_id not in channels:
            await ctx.send("❌ Questo canale non è nella lista dell'utente.")
            return
        channels.remove(channel_id)
        rules[key]["channels"] = channels
        await self.config.guild(ctx.guild).user_rules.set(rules)
        if channels:
            await ctx.send(f"✅ {target.mention} rimosso dai canali di {member.mention}.")
        else:
            await ctx.send(
                f"✅ {target.mention} rimosso. La lista ora è vuota, quindi la regola di "
                f"{member.mention} torna valida in **tutti i canali**."
            )

    @autoreact_user.command(name="allchannels", aliases=["tutticanali", "global"])
    async def user_allchannels(self, ctx, user: str):
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato.")
            return
        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Questo utente non ha regole configurate.")
            return
        rules[key]["channels"] = []
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ Le reazioni di {member.mention} ora valgono in **tutti i canali**.")

    @autoreact.command(name="test", aliases=["prova"])
    async def autoreact_test(self, ctx, *reactions: str):
        """Prova reazioni sul messaggio del comando. Es: ar test normal:👍 burst:🔥"""
        if not reactions:
            await ctx.send("❌ Esempio: `[p]ar test normal:👍 burst:🔥`.")
            return

        results = []
        for raw in reactions:
            ok, error = await self._validate_reaction_spec(ctx.guild, raw)
            if not ok:
                results.append(f"❌ `{raw}`: {error}")
                continue
            reaction_type, emoji = self._split_reaction_spec(raw)
            if reaction_type == "burst":
                success, detail = await self._add_burst_reaction(ctx.message, emoji)
            else:
                success, detail = await self._add_normal_reaction(ctx.message, emoji)
            results.append(
                f"{'✅' if success else '❌'} `{self._normalize_spec(raw)}` — {detail}"
            )
            await asyncio.sleep(0.15)

        await ctx.send("**Test AutoReactions**\n" + "\n".join(results))

    @autoreact.command(name="list", aliases=["lista", "show", "mostra"])
    async def autoreact_list(self, ctx):
        data = await self.config.guild(ctx.guild).all()
        lines = [
            "**Configurazione AutoReactions**",
            f"Stato: {'✅ attivo' if data['enabled'] else '⛔ disattivato'}",
            "Legenda: `•` normale | `⚡` super/BURST",
            "",
            "**Regole canali**",
        ]

        if not data["channel_rules"]:
            lines.append("- Nessuna")
        else:
            for channel_id, rule in data["channel_rules"].items():
                channel = ctx.guild.get_channel(int(channel_id))
                name = channel.mention if channel else f"canale `{channel_id}`"
                specs = [self._normalize_spec(x) for x in rule.get("reactions", [])]
                lines.append(
                    f"- {name}: {' '.join(self._display_spec(x) for x in specs) or 'nessuna reazione'}"
                )

        lines.extend(["", "**Regole utenti**"])
        if not data["user_rules"]:
            lines.append("- Nessuna")
        else:
            for user_id, rule in data["user_rules"].items():
                member = ctx.guild.get_member(int(user_id))
                name = member.mention if member else f"utente `{user_id}`"
                channels = [str(x) for x in rule.get("channels", [])]
                if channels:
                    channel_names = []
                    for channel_id in channels:
                        channel = ctx.guild.get_channel(int(channel_id))
                        channel_names.append(channel.mention if channel else f"`{channel_id}`")
                    scope = ", ".join(channel_names)
                else:
                    scope = "tutti i canali"
                specs = [self._normalize_spec(x) for x in rule.get("reactions", [])]
                lines.append(
                    f"- {name}: {' '.join(self._display_spec(x) for x in specs) or 'nessuna reazione'} | {scope}"
                )

        lines.extend([
            "",
            "Esempi:",
            "`[p]ar channel add #generale normal:👍 burst:🔥 burst:❤️`",
            "`[p]ar user add @utente burst:💯 normal:😂`",
            "`[p]ar test burst:🔥`",
            "",
            "⚠️ Le BURST usano endpoint client non documentati ufficialmente da Discord; "
            "se Discord li modifica, il comando `test` mostra l'errore restituito dall'API.",
        ])

        text = "\n".join(lines)
        for page in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
            await ctx.send(page)

    @autoreact.command(name="super", aliases=["burst", "superreaction"])
    async def autoreact_super(self, ctx):
        await ctx.send(
            "⚡ **Supporto super-reazioni BURST attivo.**\n"
            "Usa `burst:EMOJI` oppure `super:EMOJI`.\n"
            "Esempio: `[p]ar test burst:🔥`\n"
            "Il cog usa prima `type=1` e, se necessario, endpoint BURST di fallback compatibili col client Discord."
        )

    @autoreact.command(name="clear", aliases=["reset"])
    async def autoreact_clear(self, ctx, confirm: bool = False):
        if not confirm:
            await ctx.send("⚠️ Per confermare usa `[p]ar clear true`.")
            return
        await self.config.guild(ctx.guild).channel_rules.set({})
        await self.config.guild(ctx.guild).user_rules.set({})
        await ctx.send("✅ Tutte le regole AutoReactions sono state cancellate.")
