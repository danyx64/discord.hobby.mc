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
    """Auto-reazioni normali e BURST per canali, utenti e ruoli."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=64642026090801, force_registration=True
        )
        self.config.register_guild(
            enabled=True,
            channel_rules={},
            user_rules={},
            role_rules={},
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
        return "normal", raw

    @classmethod
    def _normalize_spec(cls, raw: str) -> str:
        reaction_type, emoji = cls._split_reaction_spec(raw)
        return f"{reaction_type}:{emoji}"

    @classmethod
    def _display_spec(cls, raw: str) -> str:
        reaction_type, emoji = cls._split_reaction_spec(raw)
        return f"{'⚡' if reaction_type == 'burst' else '•'}{emoji}"

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
            return False, "Tipo non valido. Usa `normal:` oppure `burst:`."
        if not emoji:
            return False, "Emoji vuota."

        match = CUSTOM_EMOJI_RE.match(emoji)
        if match and self.bot.get_emoji(int(match.group(2))) is None:
            return False, "Il bot non ha accesso a questa emoji personalizzata."
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
            return member or discord.utils.get(ctx.guild.members, display_name=value)
        member = ctx.guild.get_member(user_id)
        if member is None:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return member

    async def _resolve_role(self, ctx, raw: str) -> Optional[discord.Role]:
        value = raw.strip()
        if value.startswith("<@&") and value.endswith(">"):
            value = value[3:-1]
        try:
            role_id = int(value)
        except ValueError:
            return discord.utils.get(ctx.guild.roles, name=value.lstrip("@"))
        return ctx.guild.get_role(role_id)

    async def _reaction_specs_for(self, message: discord.Message) -> List[str]:
        data = await self.config.guild(message.guild).all()
        if not data["enabled"]:
            return []

        channel_id = str(message.channel.id)
        reactions = []

        channel_rule = data["channel_rules"].get(channel_id)
        if channel_rule:
            reactions.extend(channel_rule.get("reactions", []))

        user_rule = data["user_rules"].get(str(message.author.id))
        if user_rule:
            allowed = [str(x) for x in user_rule.get("channels", [])]
            if not allowed or channel_id in allowed:
                reactions.extend(user_rule.get("reactions", []))

        role_rules = data.get("role_rules", {})
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                rule = role_rules.get(str(role.id))
                if not rule:
                    continue
                allowed = [str(x) for x in rule.get("channels", [])]
                if not allowed or channel_id in allowed:
                    reactions.extend(rule.get("reactions", []))

        return self._unique([self._normalize_spec(x) for x in reactions])

    async def _add_normal_reaction(self, message: discord.Message, emoji: str) -> Tuple[bool, str]:
        try:
            await message.add_reaction(self._emoji_from_text(emoji))
            return True, "ok"
        except discord.Forbidden:
            return False, "permesso negato"
        except discord.NotFound:
            return False, "messaggio o emoji non trovato"
        except discord.HTTPException as exc:
            return False, f"HTTP {getattr(exc, 'status', '?')}: {exc}"

    async def _add_burst_reaction(self, message: discord.Message, emoji: str) -> Tuple[bool, str]:
        api_key = self._emoji_api_key(emoji)
        common = {
            "channel_id": message.channel.id,
            "message_id": message.id,
            "emoji": api_key,
        }
        attempts = [
            (
                Route("PUT", "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me", **common),
                {"location": "Message Inline Button", "type": 1},
                "type=1",
            ),
            (
                Route("PUT", "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/1/@me", **common),
                {"location": "Message Inline Button", "burst": "true"},
                "typed burst fallback",
            ),
            (
                Route("PUT", "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me", **common),
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
                return False, "permesso negato"
            except discord.NotFound:
                last_error = "messaggio, canale o emoji non trovato"
            except discord.HTTPException as exc:
                status = getattr(exc, "status", None)
                last_error = f"{label}: HTTP {status or '?'} - {exc}"
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
        """Configura auto-reazioni per canali, utenti e ruoli."""
        await ctx.send_help()

    @autoreact.command(name="on", aliases=["attiva", "enable"])
    async def autoreact_on(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ Auto-reazioni **attivate**.")

    @autoreact.command(name="off", aliases=["disattiva", "disable"])
    async def autoreact_off(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("⛔ Auto-reazioni **disattivate**. Configurazione mantenuta.")

    async def _validate_many(self, guild, reactions):
        normalized = []
        for reaction in reactions:
            ok, error = await self._validate_reaction_spec(guild, reaction)
            if not ok:
                return None, f"`{reaction}`: {error}"
            normalized.append(self._normalize_spec(reaction))
        return normalized, None

    @autoreact.group(name="channel", aliases=["canale", "ch"], invoke_without_command=True)
    async def autoreact_channel(self, ctx):
        await ctx.send_help()

    @autoreact_channel.command(name="add", aliases=["aggiungi"])
    async def channel_add(self, ctx, channel: str, *reactions: str):
        target = await self._resolve_text_channel(ctx, channel)
        if target is None or not reactions:
            await ctx.send("❌ Canale non trovato o nessuna reazione indicata.")
            return
        normalized, error = await self._validate_many(ctx.guild, reactions)
        if error:
            await ctx.send(f"❌ {error}")
            return
        rules = await self.config.guild(ctx.guild).channel_rules()
        key = str(target.id)
        current = rules.get(key, {"reactions": []})
        existing = [self._normalize_spec(x) for x in current.get("reactions", [])]
        current["reactions"] = self._unique(existing + normalized)
        rules[key] = current
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send(f"✅ {target.mention}: {' '.join(self._display_spec(x) for x in current['reactions'])}")

    @autoreact_channel.command(name="remove", aliases=["rimuovi", "del"])
    async def channel_remove(self, ctx, channel: str, reaction: str = None):
        target = await self._resolve_text_channel(ctx, channel)
        if target is None:
            await ctx.send("❌ Canale non trovato.")
            return
        rules = await self.config.guild(ctx.guild).channel_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo canale.")
            return
        if reaction is None:
            del rules[key]
        else:
            wanted = self._normalize_spec(reaction)
            configured = [self._normalize_spec(x) for x in rules[key].get("reactions", [])]
            if wanted not in configured:
                await ctx.send("❌ Reazione non configurata.")
                return
            configured.remove(wanted)
            if configured:
                rules[key]["reactions"] = configured
            else:
                del rules[key]
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send("✅ Regola canale aggiornata.")

    @autoreact.group(name="user", aliases=["utente", "usr"], invoke_without_command=True)
    async def autoreact_user(self, ctx):
        await ctx.send_help()

    @autoreact_user.command(name="add", aliases=["aggiungi"])
    async def user_add(self, ctx, user: str, *reactions: str):
        member = await self._resolve_member(ctx, user)
        if member is None or not reactions:
            await ctx.send("❌ Utente non trovato o nessuna reazione indicata.")
            return
        normalized, error = await self._validate_many(ctx.guild, reactions)
        if error:
            await ctx.send(f"❌ {error}")
            return
        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        current = rules.get(key, {"reactions": [], "channels": []})
        existing = [self._normalize_spec(x) for x in current.get("reactions", [])]
        current["reactions"] = self._unique(existing + normalized)
        current.setdefault("channels", [])
        rules[key] = current
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ Regola aggiornata per {member.mention}.")

    @autoreact_user.command(name="remove", aliases=["rimuovi", "del"])
    async def user_remove(self, ctx, user: str, reaction: str = None):
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato.")
            return
        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo utente.")
            return
        if reaction is None:
            del rules[key]
        else:
            wanted = self._normalize_spec(reaction)
            configured = [self._normalize_spec(x) for x in rules[key].get("reactions", [])]
            if wanted not in configured:
                await ctx.send("❌ Reazione non configurata.")
                return
            configured.remove(wanted)
            if configured:
                rules[key]["reactions"] = configured
            else:
                del rules[key]
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send("✅ Regola utente aggiornata.")

    @autoreact_user.command(name="channel", aliases=["canale", "ch"])
    async def user_channel(self, ctx, user: str, channel: str):
        member = await self._resolve_member(ctx, user)
        target = await self._resolve_text_channel(ctx, channel)
        if member is None or target is None:
            await ctx.send("❌ Utente o canale non trovato.")
            return
        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Prima aggiungi l'utente con `.ar user add`.")
            return
        channels = [str(x) for x in rules[key].get("channels", [])]
        if str(target.id) not in channels:
            channels.append(str(target.id))
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
            await ctx.send("❌ Nessuna regola per questo utente.")
            return
        channels = [str(x) for x in rules[key].get("channels", [])]
        if str(target.id) in channels:
            channels.remove(str(target.id))
        rules[key]["channels"] = channels
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send("✅ Canale rimosso dalla regola utente.")

    @autoreact_user.command(name="allchannels", aliases=["tutticanali", "global"])
    async def user_allchannels(self, ctx, user: str):
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato.")
            return
        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo utente.")
            return
        rules[key]["channels"] = []
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ {member.mention}: regola valida in tutti i canali.")

    @autoreact.group(name="role", aliases=["ruolo", "r"], invoke_without_command=True)
    async def autoreact_role(self, ctx):
        """Gestisce auto-reazioni per chi possiede un determinato ruolo."""
        await ctx.send_help()

    @autoreact_role.command(name="add", aliases=["aggiungi"])
    async def role_add(self, ctx, role: str, *reactions: str):
        target = await self._resolve_role(ctx, role)
        if target is None or not reactions:
            await ctx.send("❌ Ruolo non trovato o nessuna reazione indicata.")
            return
        normalized, error = await self._validate_many(ctx.guild, reactions)
        if error:
            await ctx.send(f"❌ {error}")
            return
        rules = await self.config.guild(ctx.guild).role_rules()
        key = str(target.id)
        current = rules.get(key, {"reactions": [], "channels": []})
        existing = [self._normalize_spec(x) for x in current.get("reactions", [])]
        current["reactions"] = self._unique(existing + normalized)
        current.setdefault("channels", [])
        rules[key] = current
        await self.config.guild(ctx.guild).role_rules.set(rules)
        await ctx.send(
            f"✅ Regola aggiornata per {target.mention}.\n"
            f"Reazioni: {' '.join(self._display_spec(x) for x in current['reactions'])}"
        )

    @autoreact_role.command(name="remove", aliases=["rimuovi", "del"])
    async def role_remove(self, ctx, role: str, reaction: str = None):
        target = await self._resolve_role(ctx, role)
        if target is None:
            await ctx.send("❌ Ruolo non trovato.")
            return
        rules = await self.config.guild(ctx.guild).role_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo ruolo.")
            return
        if reaction is None:
            del rules[key]
        else:
            wanted = self._normalize_spec(reaction)
            configured = [self._normalize_spec(x) for x in rules[key].get("reactions", [])]
            if wanted not in configured:
                await ctx.send("❌ Reazione non configurata per questo ruolo.")
                return
            configured.remove(wanted)
            if configured:
                rules[key]["reactions"] = configured
            else:
                del rules[key]
        await self.config.guild(ctx.guild).role_rules.set(rules)
        await ctx.send("✅ Regola ruolo aggiornata.")

    @autoreact_role.command(name="channel", aliases=["canale", "ch"])
    async def role_channel(self, ctx, role: str, channel: str):
        target = await self._resolve_role(ctx, role)
        channel_obj = await self._resolve_text_channel(ctx, channel)
        if target is None or channel_obj is None:
            await ctx.send("❌ Ruolo o canale non trovato.")
            return
        rules = await self.config.guild(ctx.guild).role_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Prima aggiungi il ruolo con `.ar role add`.")
            return
        channels = [str(x) for x in rules[key].get("channels", [])]
        if str(channel_obj.id) not in channels:
            channels.append(str(channel_obj.id))
        rules[key]["channels"] = channels
        await self.config.guild(ctx.guild).role_rules.set(rules)
        await ctx.send(f"✅ {channel_obj.mention} aggiunto alla regola di {target.mention}.")

    @autoreact_role.command(name="unchannel", aliases=["rimuovicanale", "rmchannel"])
    async def role_unchannel(self, ctx, role: str, channel: str):
        target = await self._resolve_role(ctx, role)
        channel_obj = await self._resolve_text_channel(ctx, channel)
        if target is None or channel_obj is None:
            await ctx.send("❌ Ruolo o canale non trovato.")
            return
        rules = await self.config.guild(ctx.guild).role_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo ruolo.")
            return
        channels = [str(x) for x in rules[key].get("channels", [])]
        if str(channel_obj.id) in channels:
            channels.remove(str(channel_obj.id))
        rules[key]["channels"] = channels
        await self.config.guild(ctx.guild).role_rules.set(rules)
        await ctx.send("✅ Canale rimosso dalla regola ruolo.")

    @autoreact_role.command(name="allchannels", aliases=["tutticanali", "global"])
    async def role_allchannels(self, ctx, role: str):
        target = await self._resolve_role(ctx, role)
        if target is None:
            await ctx.send("❌ Ruolo non trovato.")
            return
        rules = await self.config.guild(ctx.guild).role_rules()
        key = str(target.id)
        if key not in rules:
            await ctx.send("❌ Nessuna regola per questo ruolo.")
            return
        rules[key]["channels"] = []
        await self.config.guild(ctx.guild).role_rules.set(rules)
        await ctx.send(f"✅ {target.mention}: regola valida in tutti i canali.")

    @autoreact.command(name="test", aliases=["prova"])
    async def autoreact_test(self, ctx, *reactions: str):
        if not reactions:
            await ctx.send("❌ Esempio: `.ar test normal:👍 burst:🔥`.")
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
            results.append(f"{'✅' if success else '❌'} `{self._normalize_spec(raw)}` — {detail}")
            await asyncio.sleep(0.15)
        await ctx.send("**Test AutoReactions**\n" + "\n".join(results))

    @autoreact.command(name="list", aliases=["lista", "show", "mostra"])
    async def autoreact_list(self, ctx):
        data = await self.config.guild(ctx.guild).all()
        lines = [
            "**Configurazione AutoReactions**",
            f"Stato: {'✅ attivo' if data['enabled'] else '⛔ disattivato'}",
            "Legenda: `•` normale | `⚡` BURST",
            "",
            "**Canali**",
        ]
        if not data["channel_rules"]:
            lines.append("- Nessuno")
        else:
            for channel_id, rule in data["channel_rules"].items():
                channel = ctx.guild.get_channel(int(channel_id))
                name = channel.mention if channel else f"`{channel_id}`"
                specs = [self._normalize_spec(x) for x in rule.get("reactions", [])]
                lines.append(f"- {name}: {' '.join(self._display_spec(x) for x in specs)}")

        lines.extend(["", "**Utenti**"])
        if not data["user_rules"]:
            lines.append("- Nessuno")
        else:
            for user_id, rule in data["user_rules"].items():
                member = ctx.guild.get_member(int(user_id))
                name = member.mention if member else f"`{user_id}`"
                specs = [self._normalize_spec(x) for x in rule.get("reactions", [])]
                channels = rule.get("channels", [])
                scope = "tutti i canali" if not channels else f"{len(channels)} canali"
                lines.append(f"- {name}: {' '.join(self._display_spec(x) for x in specs)} | {scope}")

        lines.extend(["", "**Ruoli**"])
        role_rules = data.get("role_rules", {})
        if not role_rules:
            lines.append("- Nessuno")
        else:
            for role_id, rule in role_rules.items():
                role = ctx.guild.get_role(int(role_id))
                name = role.mention if role else f"`{role_id}`"
                specs = [self._normalize_spec(x) for x in rule.get("reactions", [])]
                channels = rule.get("channels", [])
                scope = "tutti i canali" if not channels else f"{len(channels)} canali"
                lines.append(f"- {name}: {' '.join(self._display_spec(x) for x in specs)} | {scope}")

        lines.extend([
            "",
            "Esempi:",
            "`.ar role add @VIP normal:👍 burst:🔥`",
            "`.ar role channel @VIP #generale`",
            "`.ar user add @utente burst:💯`",
            "`.ar channel add #foto normal:❤️`",
        ])
        text = "\n".join(lines)
        for page in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
            await ctx.send(page)

    @autoreact.command(name="super", aliases=["burst", "superreaction"])
    async def autoreact_super(self, ctx):
        await ctx.send(
            "⚡ **Supporto BURST attivo.**\n"
            "Usa `burst:EMOJI` oppure `super:EMOJI`.\n"
            "Esempio: `.ar test burst:🔥`"
        )

    @autoreact.command(name="clear", aliases=["reset"])
    async def autoreact_clear(self, ctx, confirm: bool = False):
        if not confirm:
            await ctx.send("⚠️ Per confermare usa `.ar clear true`.")
            return
        await self.config.guild(ctx.guild).channel_rules.set({})
        await self.config.guild(ctx.guild).user_rules.set({})
        await self.config.guild(ctx.guild).role_rules.set({})
        await ctx.send("✅ Tutte le regole AutoReactions sono state cancellate.")
