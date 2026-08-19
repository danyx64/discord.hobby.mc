import re
from datetime import timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


ITALY_TZ = ZoneInfo("Europe/Rome")
KEY_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


class LeaveFeedButton(discord.ui.Button):
    def __init__(self, cog: "LeaveFeed", guild_id: int, modal_key: str, data: Dict):
        self.cog = cog
        self.guild_id = guild_id
        self.modal_key = modal_key
        style = STYLE_MAP.get(str(data.get("button_style", "primary")).lower(), discord.ButtonStyle.primary)
        super().__init__(
            label=str(data.get("button_label") or modal_key)[:80],
            style=style,
            custom_id=f"leavefeed:{guild_id}:{modal_key}",
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.open_modal(interaction, self.guild_id, self.modal_key)


class LeaveFeedView(discord.ui.View):
    def __init__(self, cog: "LeaveFeed", guild_id: int, modals: Dict):
        super().__init__(timeout=None)
        for key, data in list(modals.items())[:5]:
            self.add_item(LeaveFeedButton(cog, guild_id, key, data))


class LeaveFeedModal(discord.ui.Modal):
    def __init__(self, cog: "LeaveFeed", guild_id: int, modal_key: str, data: Dict):
        super().__init__(title=str(data.get("title") or "Feedback")[:45], timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.modal_key = modal_key
        self.inputs: List[discord.ui.TextInput] = []

        for index, question in enumerate(list(data.get("questions", []))[:5]):
            style_name = str(question.get("style", "long")).lower()
            style = discord.TextStyle.short if style_name == "short" else discord.TextStyle.paragraph
            min_length = int(question.get("min_length", 0) or 0)
            max_length = int(question.get("max_length", 1000) or 1000)
            item = discord.ui.TextInput(
                label=str(question.get("label") or f"Domanda {index + 1}")[:45],
                placeholder=(str(question.get("placeholder"))[:100] if question.get("placeholder") else None),
                style=style,
                required=bool(question.get("required", True)),
                min_length=(min_length if min_length > 0 else None),
                max_length=max(1, min(max_length, 4000)),
                custom_id=f"q{index}",
            )
            self.inputs.append(item)
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        answers = [str(item.value or "").strip() for item in self.inputs]
        ok = await self.cog.submit_feedback(
            guild_id=self.guild_id,
            modal_key=self.modal_key,
            user=interaction.user,
            answers=answers,
        )
        if ok:
            await interaction.response.send_message("Grazie per il feedback.")
        else:
            await interaction.response.send_message("Non sono riuscito a consegnare il feedback allo staff.")


class LeaveFeed(commands.Cog):
    """DM di feedback personalizzabile per i membri che lasciano il server."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=742951603118804261, force_registration=True)
        self.config.register_guild(
            enabled=False,
            feedback_channel_id=None,
            message="Ci dispiace vederti andare da {server}. Se vuoi, lasciaci un feedback usando uno dei pulsanti qui sotto.",
            modals={},
        )

    async def cog_load(self):
        all_guilds = await self.config.all_guilds()
        for guild_id, data in all_guilds.items():
            modals = data.get("modals") or {}
            if modals:
                self.bot.add_view(LeaveFeedView(self, int(guild_id), modals))

    @staticmethod
    def _render_message(template: str, user, guild: discord.Guild) -> str:
        return str(template).replace("{user}", getattr(user, "name", str(user))).replace("{server}", guild.name)

    @staticmethod
    def _clean(value: str, limit: int = 700) -> str:
        text = str(value or "—").strip() or "—"
        return text if len(text) <= limit else text[: limit - 1] + "…"

    async def _send_leave_dm(self, user, guild: discord.Guild) -> bool:
        data = await self.config.guild(guild).all()
        if not data.get("enabled"):
            return False
        message = self._render_message(data.get("message") or "", user, guild)
        modals = data.get("modals") or {}
        view = LeaveFeedView(self, guild.id, modals) if modals else None
        try:
            await user.send(content=message or None, view=view, allowed_mentions=discord.AllowedMentions.none())
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def open_modal(self, interaction: discord.Interaction, guild_id: int, modal_key: str):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return await interaction.response.send_message("Questo server non e piu disponibile.")
        modals = await self.config.guild(guild).modals()
        data = modals.get(modal_key)
        if not data:
            return await interaction.response.send_message("Questo modulo non e piu disponibile.")
        questions = data.get("questions") or []
        if not questions:
            return await interaction.response.send_message("Questo modulo non ha ancora domande configurate.")
        await interaction.response.send_modal(LeaveFeedModal(self, guild_id, modal_key, data))

    async def submit_feedback(self, guild_id: int, modal_key: str, user, answers: List[str]) -> bool:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False
        channel_id = await self.config.guild(guild).feedback_channel_id()
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return False

        modals = await self.config.guild(guild).modals()
        data = modals.get(modal_key) or {}
        questions = data.get("questions") or []
        now = discord.utils.utcnow().astimezone(ITALY_TZ)

        lines = [
            f"**Utente:** <@{user.id}>",
            f"**Data:** {now.strftime('%d/%m/%Y')}",
            f"**Ora:** {now.strftime('%H:%M:%S')}",
            f"**ID:** `{user.id}`",
            "**Motivo:**",
        ]
        for index, answer in enumerate(answers):
            label = questions[index].get("label") if index < len(questions) else f"Domanda {index + 1}"
            lines.append(f"**{self._clean(label, 80)}:** {self._clean(answer)}")

        embed = discord.Embed(description="\n".join(lines)[:4096], colour=discord.Colour.blurple())
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self._send_leave_dm(member, member.guild)

    @commands.group(name="leavefeed", invoke_without_command=True)
    @commands.guild_only()
    async def leavefeed(self, ctx: commands.Context):
        """Configura LeaveFeed."""
        await ctx.send_help(ctx.command)

    @leavefeed.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def setchannel(self, ctx: commands.Context, channel_id: int):
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Non trovo un canale testuale con questo ID.")
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await ctx.send("Mi servono Visualizza canale, Invia messaggi e Incorpora link in quel canale.")
        await self.config.guild(ctx.guild).feedback_channel_id.set(channel.id)
        await ctx.send(f"Canale feedback impostato su {channel.mention} (`{channel.id}`).")

    @leavefeed.command(name="message")
    @commands.admin_or_permissions(administrator=True)
    async def setmessage(self, ctx: commands.Context, *, message: str):
        if len(message) > 1900:
            return await ctx.send("Il messaggio deve essere lungo al massimo 1900 caratteri.")
        await self.config.guild(ctx.guild).message.set(message)
        await ctx.send("Messaggio DM aggiornato. Placeholder disponibili: `{user}` e `{server}`.")

    @leavefeed.command(name="enable")
    @commands.admin_or_permissions(administrator=True)
    async def enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("LeaveFeed abilitato.")

    @leavefeed.command(name="disable")
    @commands.admin_or_permissions(administrator=True)
    async def disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("LeaveFeed disabilitato.")

    @leavefeed.command(name="status")
    @commands.admin_or_permissions(administrator=True)
    async def status(self, ctx: commands.Context):
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data.get("feedback_channel_id")) if data.get("feedback_channel_id") else None
        modals = data.get("modals") or {}
        await ctx.send(
            f"Stato: **{'attivo' if data.get('enabled') else 'disattivato'}**\n"
            f"Canale: {channel.mention if channel else '—'}\n"
            f"Modali: **{len(modals)}**\n"
            f"Messaggio: {self._clean(data.get('message') or '—', 600)}"
        )

    @leavefeed.command(name="test")
    @commands.admin_or_permissions(administrator=True)
    async def test(self, ctx: commands.Context):
        ok = await self._send_leave_dm(ctx.author, ctx.guild)
        await ctx.send("DM di test inviato." if ok else "Non sono riuscito a mandarti il DM di test.")

    @leavefeed.group(name="modal", invoke_without_command=True)
    @commands.admin_or_permissions(administrator=True)
    async def modal_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @modal_group.command(name="add")
    async def modal_add(self, ctx: commands.Context, key: str, *, button_label: str):
        key = key.lower()
        if not KEY_RE.fullmatch(key):
            return await ctx.send("La chiave deve usare solo lettere minuscole, numeri, `_` o `-` e massimo 24 caratteri.")
        if len(button_label) > 80:
            return await ctx.send("Il testo del pulsante puo avere massimo 80 caratteri.")
        async with self.config.guild(ctx.guild).modals() as modals:
            if key in modals:
                return await ctx.send("Esiste gia un modal con questa chiave.")
            if len(modals) >= 5:
                return await ctx.send("Puoi configurare al massimo 5 pulsanti/modali.")
            modals[key] = {
                "title": button_label[:45],
                "button_label": button_label,
                "button_style": "primary",
                "questions": [],
            }
        await ctx.send(f"Modal `{key}` creato. Ora aggiungi le domande con `.leavefeed question add`. ")

    @modal_group.command(name="remove")
    async def modal_remove(self, ctx: commands.Context, key: str):
        key = key.lower()
        async with self.config.guild(ctx.guild).modals() as modals:
            if key not in modals:
                return await ctx.send("Modal non trovato.")
            del modals[key]
        await ctx.send(f"Modal `{key}` rimosso.")

    @modal_group.command(name="list")
    async def modal_list(self, ctx: commands.Context):
        modals = await self.config.guild(ctx.guild).modals()
        if not modals:
            return await ctx.send("Nessun modal configurato.")
        lines = [f"`{key}` — {data.get('button_label', key)} — {len(data.get('questions', []))} domande" for key, data in modals.items()]
        await ctx.send("\n".join(lines))

    @modal_group.command(name="title")
    async def modal_title(self, ctx: commands.Context, key: str, *, title: str):
        if not 1 <= len(title) <= 45:
            return await ctx.send("Il titolo deve essere lungo da 1 a 45 caratteri.")
        async with self.config.guild(ctx.guild).modals() as modals:
            data = modals.get(key.lower())
            if not data:
                return await ctx.send("Modal non trovato.")
            data["title"] = title
        await ctx.send("Titolo del modal aggiornato.")

    @modal_group.command(name="button")
    async def modal_button(self, ctx: commands.Context, key: str, *, label: str):
        if not 1 <= len(label) <= 80:
            return await ctx.send("Il testo del pulsante deve essere lungo da 1 a 80 caratteri.")
        async with self.config.guild(ctx.guild).modals() as modals:
            data = modals.get(key.lower())
            if not data:
                return await ctx.send("Modal non trovato.")
            data["button_label"] = label
        await ctx.send("Testo del pulsante aggiornato.")

    @modal_group.command(name="style")
    async def modal_style(self, ctx: commands.Context, key: str, style: str):
        style = style.lower()
        if style not in STYLE_MAP:
            return await ctx.send("Stili validi: `primary`, `secondary`, `success`, `danger`.")
        async with self.config.guild(ctx.guild).modals() as modals:
            data = modals.get(key.lower())
            if not data:
                return await ctx.send("Modal non trovato.")
            data["button_style"] = style
        await ctx.send("Stile del pulsante aggiornato.")

    @leavefeed.group(name="question", invoke_without_command=True)
    @commands.admin_or_permissions(administrator=True)
    async def question_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @question_group.command(name="add")
    async def question_add(self, ctx: commands.Context, modal_key: str, style: str, required: bool, min_length: int, max_length: int, *, label: str):
        style = style.lower()
        if style not in {"short", "long"}:
            return await ctx.send("Lo stile deve essere `short` oppure `long`.")
        if not 1 <= len(label) <= 45:
            return await ctx.send("La domanda deve essere lunga da 1 a 45 caratteri.")
        if min_length < 0 or max_length < 1 or max_length > 4000 or min_length > max_length:
            return await ctx.send("Lunghezze non valide: min >= 0, max tra 1 e 4000 e min <= max.")
        async with self.config.guild(ctx.guild).modals() as modals:
            data = modals.get(modal_key.lower())
            if not data:
                return await ctx.send("Modal non trovato.")
            questions = data.setdefault("questions", [])
            if len(questions) >= 5:
                return await ctx.send("Un modal puo avere al massimo 5 domande.")
            questions.append({
                "label": label,
                "placeholder": "",
                "style": style,
                "required": required,
                "min_length": min_length,
                "max_length": max_length,
            })
        await ctx.send("Domanda aggiunta.")

    @question_group.command(name="remove")
    async def question_remove(self, ctx: commands.Context, modal_key: str, index: int):
        async with self.config.guild(ctx.guild).modals() as modals:
            data = modals.get(modal_key.lower())
            if not data:
                return await ctx.send("Modal non trovato.")
            questions = data.get("questions", [])
            if index < 1 or index > len(questions):
                return await ctx.send("Indice domanda non valido.")
            questions.pop(index - 1)
        await ctx.send("Domanda rimossa.")

    @question_group.command(name="list")
    async def question_list(self, ctx: commands.Context, modal_key: str):
        modals = await self.config.guild(ctx.guild).modals()
        data = modals.get(modal_key.lower())
        if not data:
            return await ctx.send("Modal non trovato.")
        questions = data.get("questions", [])
        if not questions:
            return await ctx.send("Questo modal non ha domande.")
        lines = []
        for i, q in enumerate(questions, 1):
            lines.append(
                f"**{i}.** {q.get('label')} | {q.get('style')} | "
                f"{'obbligatoria' if q.get('required') else 'facoltativa'} | "
                f"{q.get('min_length', 0)}-{q.get('max_length', 1000)}"
            )
        await ctx.send("\n".join(lines))

    @question_group.command(name="label")
    async def question_label(self, ctx: commands.Context, modal_key: str, index: int, *, label: str):
        if not 1 <= len(label) <= 45:
            return await ctx.send("La domanda deve essere lunga da 1 a 45 caratteri.")
        question = await self._get_question_for_edit(ctx, modal_key, index)
        if question is None:
            return
        async with self.config.guild(ctx.guild).modals() as modals:
            modals[modal_key.lower()]["questions"][index - 1]["label"] = label
        await ctx.send("Testo della domanda aggiornato.")

    @question_group.command(name="placeholder")
    async def question_placeholder(self, ctx: commands.Context, modal_key: str, index: int, *, text: str):
        if text == "-":
            text = ""
        if len(text) > 100:
            return await ctx.send("Il placeholder puo avere massimo 100 caratteri.")
        question = await self._get_question_for_edit(ctx, modal_key, index)
        if question is None:
            return
        async with self.config.guild(ctx.guild).modals() as modals:
            modals[modal_key.lower()]["questions"][index - 1]["placeholder"] = text
        await ctx.send("Placeholder aggiornato.")

    @question_group.command(name="style")
    async def question_style(self, ctx: commands.Context, modal_key: str, index: int, style: str):
        style = style.lower()
        if style not in {"short", "long"}:
            return await ctx.send("Lo stile deve essere `short` oppure `long`.")
        question = await self._get_question_for_edit(ctx, modal_key, index)
        if question is None:
            return
        async with self.config.guild(ctx.guild).modals() as modals:
            modals[modal_key.lower()]["questions"][index - 1]["style"] = style
        await ctx.send("Stile della domanda aggiornato.")

    @question_group.command(name="required")
    async def question_required(self, ctx: commands.Context, modal_key: str, index: int, required: bool):
        question = await self._get_question_for_edit(ctx, modal_key, index)
        if question is None:
            return
        async with self.config.guild(ctx.guild).modals() as modals:
            modals[modal_key.lower()]["questions"][index - 1]["required"] = required
        await ctx.send("Obbligatorieta aggiornata.")

    @question_group.command(name="length")
    async def question_length(self, ctx: commands.Context, modal_key: str, index: int, min_length: int, max_length: int):
        if min_length < 0 or max_length < 1 or max_length > 4000 or min_length > max_length:
            return await ctx.send("Lunghezze non valide: min >= 0, max tra 1 e 4000 e min <= max.")
        question = await self._get_question_for_edit(ctx, modal_key, index)
        if question is None:
            return
        async with self.config.guild(ctx.guild).modals() as modals:
            q = modals[modal_key.lower()]["questions"][index - 1]
            q["min_length"] = min_length
            q["max_length"] = max_length
        await ctx.send("Lunghezza della risposta aggiornata.")

    async def _get_question_for_edit(self, ctx: commands.Context, modal_key: str, index: int) -> Optional[Dict]:
        modals = await self.config.guild(ctx.guild).modals()
        data = modals.get(modal_key.lower())
        if not data:
            await ctx.send("Modal non trovato.")
            return None
        questions = data.get("questions", [])
        if index < 1 or index > len(questions):
            await ctx.send("Indice domanda non valido.")
            return None
        return questions[index - 1]
