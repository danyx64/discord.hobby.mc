import asyncio
import re
from typing import List, Optional

import discord
from redbot.core import Config, commands


CUSTOM_EMOJI_RE = re.compile(r"^<a?:([A-Za-z0-9_]+):(\d+)>$")


class AutoReactions(commands.Cog):
    """Reazioni automatiche per canali e utenti specifici."""

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

    async def _validate_emoji(self, guild: discord.Guild, raw: str):
        raw = raw.strip()
        if not raw:
            return False, "Emoji vuota."

        match = CUSTOM_EMOJI_RE.match(raw)
        if match:
            emoji_id = int(match.group(2))
            emoji = self.bot.get_emoji(emoji_id)
            if emoji is None:
                return False, (
                    "Non trovo questa emoji nella cache del bot. Il bot deve avere accesso "
                    "all'emoji personalizzata."
                )
            return True, None

        # Le emoji Unicode vengono validate definitivamente da Discord quando
        # il bot prova ad aggiungere la reazione al messaggio.
        return True, None

    async def _resolve_text_channel(self, ctx, raw: str) -> Optional[discord.TextChannel]:
        value = raw.strip()
        if value.startswith("<#") and value.endswith(">"):
            value = value[2:-1]

        try:
            channel_id = int(value)
        except ValueError:
            channel = discord.utils.get(ctx.guild.text_channels, name=value.lstrip("#"))
            return channel

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

    async def _reaction_strings_for(self, message: discord.Message) -> List[str]:
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

        return self._unique(reactions)

    async def _add_reactions(self, message: discord.Message, reactions: List[str]):
        for raw in reactions:
            try:
                await message.add_reaction(self._emoji_from_text(raw))
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException:
                continue
            # Piccolo intervallo per evitare raffiche inutili verso l'API quando
            # sono configurate molte reazioni sullo stesso messaggio.
            await asyncio.sleep(0.15)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        reactions = await self._reaction_strings_for(message)
        if reactions:
            await self._add_reactions(message, reactions)

    @commands.group(name="autoreact", aliases=["ar", "autoreactions"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def autoreact(self, ctx):
        """Configura le reazioni automatiche."""
        await ctx.send_help()

    @autoreact.command(name="on", aliases=["attiva", "enable"])
    async def autoreact_on(self, ctx):
        """Attiva tutte le auto-reazioni del server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ Auto-reazioni **attivate**.")

    @autoreact.command(name="off", aliases=["disattiva", "disable"])
    async def autoreact_off(self, ctx):
        """Disattiva tutte le auto-reazioni del server senza cancellare le regole."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("⛔ Auto-reazioni **disattivate**. La configurazione è stata mantenuta.")

    @autoreact.group(name="channel", aliases=["canale", "ch"], invoke_without_command=True)
    async def autoreact_channel(self, ctx):
        """Gestisce le regole applicate a tutti i messaggi di un canale."""
        await ctx.send_help()

    @autoreact_channel.command(name="add", aliases=["aggiungi"])
    async def channel_add(self, ctx, channel: str, *reactions: str):
        """Aggiunge una o più reazioni a ogni messaggio del canale."""
        target = await self._resolve_text_channel(ctx, channel)
        if target is None:
            await ctx.send("❌ Canale testuale non trovato. Usa mention, nome o ID.")
            return
        if not reactions:
            await ctx.send("❌ Devi indicare almeno una emoji/reazione.")
            return

        for reaction in reactions:
            ok, error = await self._validate_emoji(ctx.guild, reaction)
            if not ok:
                await ctx.send(f"❌ `{reaction}`: {error}")
                return

        rules = await self.config.guild(ctx.guild).channel_rules()
        key = str(target.id)
        current = rules.get(key, {"reactions": []})
        current["reactions"] = self._unique(current.get("reactions", []) + list(reactions))
        rules[key] = current
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send(
            f"✅ Regola aggiornata per {target.mention}.\n"
            f"Reazioni: {' '.join(current['reactions'])}"
        )

    @autoreact_channel.command(name="remove", aliases=["rimuovi", "del"])
    async def channel_remove(self, ctx, channel: str, reaction: str = None):
        """Rimuove una reazione; senza emoji elimina l'intera regola del canale."""
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

        reactions = rules[key].get("reactions", [])
        if reaction not in reactions:
            await ctx.send("❌ Questa reazione non è configurata per il canale.")
            return
        reactions.remove(reaction)
        if reactions:
            rules[key]["reactions"] = reactions
        else:
            del rules[key]
        await self.config.guild(ctx.guild).channel_rules.set(rules)
        await ctx.send(f"✅ Reazione `{reaction}` rimossa da {target.mention}.")

    @autoreact.group(name="user", aliases=["utente", "usr"], invoke_without_command=True)
    async def autoreact_user(self, ctx):
        """Gestisce le auto-reazioni per utenti specifici."""
        await ctx.send_help()

    @autoreact_user.command(name="add", aliases=["aggiungi"])
    async def user_add(self, ctx, user: str, *reactions: str):
        """Aggiunge reazioni a un utente. Per default valgono in tutti i canali."""
        member = await self._resolve_member(ctx, user)
        if member is None:
            await ctx.send("❌ Utente non trovato. Usa mention, nome o ID.")
            return
        if not reactions:
            await ctx.send("❌ Devi indicare almeno una emoji/reazione.")
            return

        for reaction in reactions:
            ok, error = await self._validate_emoji(ctx.guild, reaction)
            if not ok:
                await ctx.send(f"❌ `{reaction}`: {error}")
                return

        rules = await self.config.guild(ctx.guild).user_rules()
        key = str(member.id)
        current = rules.get(key, {"reactions": [], "channels": []})
        current["reactions"] = self._unique(current.get("reactions", []) + list(reactions))
        current.setdefault("channels", [])
        rules[key] = current
        await self.config.guild(ctx.guild).user_rules.set(rules)
        scope = "tutti i canali" if not current["channels"] else f"{len(current['channels'])} canali selezionati"
        await ctx.send(
            f"✅ Regola aggiornata per {member.mention}.\n"
            f"Reazioni: {' '.join(current['reactions'])}\nAmbito: **{scope}**"
        )

    @autoreact_user.command(name="remove", aliases=["rimuovi", "del"])
    async def user_remove(self, ctx, user: str, reaction: str = None):
        """Rimuove una reazione; senza emoji elimina completamente l'utente."""
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

        reactions = rules[key].get("reactions", [])
        if reaction not in reactions:
            await ctx.send("❌ Questa reazione non è configurata per l'utente.")
            return
        reactions.remove(reaction)
        if reactions:
            rules[key]["reactions"] = reactions
        else:
            del rules[key]
        await self.config.guild(ctx.guild).user_rules.set(rules)
        await ctx.send(f"✅ Reazione `{reaction}` rimossa da {member.mention}.")

    @autoreact_user.command(name="channel", aliases=["canale", "ch"])
    async def user_channel(self, ctx, user: str, channel: str):
        """Aggiunge un canale all'ambito di un utente specifico."""
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
        """Rimuove un canale dall'ambito di un utente."""
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
        """Imposta la regola dell'utente su tutti i canali."""
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

    @autoreact.command(name="list", aliases=["lista", "show", "mostra"])
    async def autoreact_list(self, ctx):
        """Mostra tutte le regole configurate."""
        data = await self.config.guild(ctx.guild).all()
        lines = [
            "**Configurazione AutoReactions**",
            f"Stato: {'✅ attivo' if data['enabled'] else '⛔ disattivato'}",
            "",
            "**Regole canali**",
        ]

        if not data["channel_rules"]:
            lines.append("- Nessuna")
        else:
            for channel_id, rule in data["channel_rules"].items():
                channel = ctx.guild.get_channel(int(channel_id))
                name = channel.mention if channel else f"canale `{channel_id}`"
                lines.append(f"- {name}: {' '.join(rule.get('reactions', [])) or 'nessuna reazione'}")

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
                lines.append(
                    f"- {name}: {' '.join(rule.get('reactions', [])) or 'nessuna reazione'} | {scope}"
                )

        lines.extend([
            "",
            "ℹ️ **Super-reazioni:** Discord non permette ai bot di crearle tramite l'API ufficiale. "
            "Il cog usa quindi reazioni normali, comprese emoji Unicode, custom e animate accessibili al bot.",
        ])

        text = "\n".join(lines)
        for page in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
            await ctx.send(page)

    @autoreact.command(name="super", aliases=["burst", "superreaction"])
    async def autoreact_super(self, ctx):
        """Spiega lo stato del supporto alle super-reazioni."""
        await ctx.send(
            "⚠️ **Le super-reazioni non possono essere inviate dai bot tramite l'API ufficiale di Discord.**\n"
            "Discord espone il tipo `BURST` per leggere/ricevere eventi relativi alle super-reazioni, "
            "ma l'endpoint usato dai bot per creare una reazione non permette di scegliere `BURST`.\n"
            "Per questo il cog non usa workaround non ufficiali o user-token."
        )

    @autoreact.command(name="clear", aliases=["reset"])
    async def autoreact_clear(self, ctx, confirm: bool = False):
        """Cancella tutte le regole. Richiede `true` come conferma."""
        if not confirm:
            await ctx.send("⚠️ Per confermare usa `[p]ar clear true`.")
            return
        await self.config.guild(ctx.guild).channel_rules.set({})
        await self.config.guild(ctx.guild).user_rules.set({})
        await ctx.send("✅ Tutte le regole AutoReactions sono state cancellate.")
