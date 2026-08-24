import asyncio
import re
from typing import Dict, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.views import ConfirmView


COUNTER_DEFAULTS = {
    "total": {
        "enabled": False,
        "channel_id": None,
        "channel_type": "voice",
        "template": "👥 Totale: {count}",
        "last_count": None,
        "last_name": None,
    },
    "members": {
        "enabled": False,
        "channel_id": None,
        "channel_type": "voice",
        "template": "🧑 Membri: {count}",
        "last_count": None,
        "last_name": None,
    },
    "bots": {
        "enabled": False,
        "channel_id": None,
        "channel_type": "voice",
        "template": "🤖 Bot: {count}",
        "last_count": None,
        "last_name": None,
    },
}

COUNTER_LABELS = {
    "total": "Totale",
    "members": "Membri",
    "bots": "Bot",
}


class CounterView(discord.ui.View):
    def __init__(self, cog: "MemberCounter", guild: discord.Guild, author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Questo pannello non e' tuo.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Serve il permesso Gestisci server.", ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction: discord.Interaction, counter_type: str):
        await interaction.response.defer(ephemeral=True)
        enabled = await self.cog.toggle_counter(self.guild, counter_type)
        await self.cog.refresh_all(self.guild)
        await interaction.followup.send(
            f"{COUNTER_LABELS[counter_type]}: **{'attivo' if enabled else 'disattivato'}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="Totale", style=discord.ButtonStyle.primary, emoji="👥")
    async def total(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "total")

    @discord.ui.button(label="Membri", style=discord.ButtonStyle.primary, emoji="🧑")
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "members")

    @discord.ui.button(label="Bot", style=discord.ButtonStyle.primary, emoji="🤖")
    async def bots(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "bots")

    @discord.ui.button(label="Aggiorna ora", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.refresh_all(self.guild)
        await interaction.followup.send("Contatori aggiornati.", ephemeral=True)


class MemberCounter(commands.Cog):
    """Crea e mantiene canali contatore per membri, utenti e bot."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=731946205884114322, force_registration=True)
        self.config.register_guild(
            category_id=None,
            counters=COUNTER_DEFAULTS,
        )
        self._locks: Dict[int, asyncio.Lock] = {}
        self._background_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        self._background_task = asyncio.create_task(self._periodic_refresh())

    def cog_unload(self):
        if self._background_task:
            self._background_task.cancel()

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def _periodic_refresh(self):
        await self.bot.wait_until_red_ready()
        while True:
            try:
                for guild in list(self.bot.guilds):
                    await self.refresh_all(guild)
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(60)

    @staticmethod
    def _counts(guild: discord.Guild) -> Dict[str, int]:
        members = list(guild.members)
        humans = sum(1 for member in members if not member.bot)
        bots = sum(1 for member in members if member.bot)
        total = guild.member_count if guild.member_count is not None else len(members)
        return {"total": total, "members": humans, "bots": bots}

    @staticmethod
    def _derive_template(current_name: str, previous_count: Optional[int]) -> Optional[str]:
        if previous_count is not None:
            pattern = re.compile(rf"(?<!\d){re.escape(str(previous_count))}(?!\d)")
            matches = list(pattern.finditer(current_name))
            if matches:
                match = matches[-1]
                return current_name[:match.start()] + "{count}" + current_name[match.end():]

        matches = list(re.finditer(r"\d+", current_name))
        if matches:
            match = matches[-1]
            return current_name[:match.start()] + "{count}" + current_name[match.end():]
        return None

    async def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        category_id = await self.config.guild(guild).category_id()
        if category_id:
            category = guild.get_channel(category_id)
            if isinstance(category, discord.CategoryChannel):
                return category
        return None

    async def _ensure_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        category = await self._get_category(guild)
        if category:
            return category
        category = await guild.create_category("📊 Server Stats", reason="MemberCounter setup")
        await self.config.guild(guild).category_id.set(category.id)
        return category

    async def _create_counter_channel(self, guild: discord.Guild, counter_type: str, name: str, channel_type: str):
        category = await self._ensure_category(guild)
        everyone = guild.default_role

        if channel_type == "text":
            overwrites = {
                everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
            return await guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites,
                reason=f"MemberCounter {counter_type}",
            )

        overwrites = {
            everyone: discord.PermissionOverwrite(view_channel=True, connect=False, speak=False, stream=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
        }
        return await guild.create_voice_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=f"MemberCounter {counter_type}",
        )

    async def _delete_counter_channel(self, guild: discord.Guild, counter_type: str):
        counters = await self.config.guild(guild).counters()
        data = counters[counter_type]
        channel_id = data.get("channel_id")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete(reason=f"MemberCounter {counter_type} disabilitato")
                except discord.HTTPException:
                    pass
        data["channel_id"] = None
        data["last_count"] = None
        data["last_name"] = None
        counters[counter_type] = data
        await self.config.guild(guild).counters.set(counters)

    async def toggle_counter(self, guild: discord.Guild, counter_type: str) -> bool:
        counters = await self.config.guild(guild).counters()
        data = counters[counter_type]
        new_state = not data.get("enabled", False)
        data["enabled"] = new_state
        counters[counter_type] = data
        await self.config.guild(guild).counters.set(counters)
        if not new_state:
            await self._delete_counter_channel(guild, counter_type)
        return new_state

    async def refresh_all(self, guild: discord.Guild):
        if guild.me is None or not guild.me.guild_permissions.manage_channels:
            return

        async with self._lock_for(guild.id):
            counts = self._counts(guild)
            counters = await self.config.guild(guild).counters()
            changed = False

            for counter_type, data in counters.items():
                if not data.get("enabled", False):
                    continue

                count = counts[counter_type]
                channel = guild.get_channel(data.get("channel_id") or 0)

                if channel is not None:
                    last_name = data.get("last_name")
                    if last_name and channel.name != last_name:
                        derived = self._derive_template(channel.name, data.get("last_count"))
                        if derived:
                            data["template"] = derived
                            changed = True

                template = data.get("template") or COUNTER_DEFAULTS[counter_type]["template"]
                if "{count}" not in template:
                    template = template.rstrip() + " {count}"
                    data["template"] = template
                    changed = True

                desired_name = template.replace("{count}", str(count))[:100]

                if channel is None:
                    try:
                        channel = await self._create_counter_channel(
                            guild,
                            counter_type,
                            desired_name,
                            data.get("channel_type", "voice"),
                        )
                    except discord.HTTPException:
                        continue
                    data["channel_id"] = channel.id
                    changed = True
                elif channel.name != desired_name:
                    try:
                        await channel.edit(name=desired_name, reason=f"MemberCounter update {counter_type}")
                    except discord.HTTPException:
                        continue

                data["last_count"] = count
                data["last_name"] = desired_name
                counters[counter_type] = data
                changed = True

            if changed:
                await self.config.guild(guild).counters.set(counters)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.refresh_all(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.refresh_all(member.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        counters = await self.config.guild(after.guild).counters()
        if any(data.get("channel_id") == after.id for data in counters.values()):
            await asyncio.sleep(1)
            await self.refresh_all(after.guild)

    @commands.group(name="counter", aliases=["membercounter", "statscounter"], invoke_without_command=True)
    @commands.guild_only()
    async def counter(self, ctx: commands.Context):
        """Gestisce i canali contatore del server."""
        await ctx.send_help(ctx.command)

    @counter.command(name="menu")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_menu(self, ctx: commands.Context):
        """Apre il menu con pulsanti per attivare o disattivare i contatori."""
        counters = await self.config.guild(ctx.guild).counters()
        description = []
        for key in ("total", "members", "bots"):
            data = counters[key]
            description.append(
                f"{'✅' if data.get('enabled') else '❌'} **{COUNTER_LABELS[key]}** — "
                f"`{data.get('template')}` — `{data.get('channel_type', 'voice')}`"
            )
        embed = discord.Embed(
            title="📊 MemberCounter",
            description="\n".join(description),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="I vocali sono visibili ma bloccati per @everyone.")
        await ctx.send(embed=embed, view=CounterView(self, ctx.guild, ctx.author.id))

    @counter.command(name="setup")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_setup(self, ctx: commands.Context):
        """Crea la categoria dei contatori e apre il menu di configurazione."""
        await self._ensure_category(ctx.guild)
        await ctx.invoke(self.counter_menu)

    @counter.command(name="enable")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_enable(self, ctx: commands.Context, counter_type: str):
        """Attiva un contatore: total, members oppure bots."""
        counter_type = counter_type.lower()
        if counter_type not in COUNTER_DEFAULTS:
            return await ctx.send("Tipo valido: `total`, `members`, `bots`.")
        counters = await self.config.guild(ctx.guild).counters()
        counters[counter_type]["enabled"] = True
        await self.config.guild(ctx.guild).counters.set(counters)
        await self.refresh_all(ctx.guild)
        await ctx.send(f"Contatore **{COUNTER_LABELS[counter_type]}** attivato.")

    @counter.command(name="disable")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_disable(self, ctx: commands.Context, counter_type: str):
        """Disattiva un contatore e rimuove il relativo canale."""
        counter_type = counter_type.lower()
        if counter_type not in COUNTER_DEFAULTS:
            return await ctx.send("Tipo valido: `total`, `members`, `bots`.")
        counters = await self.config.guild(ctx.guild).counters()
        counters[counter_type]["enabled"] = False
        await self.config.guild(ctx.guild).counters.set(counters)
        await self._delete_counter_channel(ctx.guild, counter_type)
        await ctx.send(f"Contatore **{COUNTER_LABELS[counter_type]}** disattivato.")

    @counter.command(name="name")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_name(self, ctx: commands.Context, counter_type: str, *, template: str):
        """Imposta il nome di un contatore. Usa {count} dove deve comparire il numero."""
        counter_type = counter_type.lower()
        if counter_type not in COUNTER_DEFAULTS:
            return await ctx.send("Tipo valido: `total`, `members`, `bots`.")
        template = template.strip()
        if not template:
            return await ctx.send("Inserisci un nome.")
        if "{count}" not in template:
            template += " {count}"
        counters = await self.config.guild(ctx.guild).counters()
        counters[counter_type]["template"] = template[:100]
        await self.config.guild(ctx.guild).counters.set(counters)
        await self.refresh_all(ctx.guild)
        await ctx.send(f"Nome **{COUNTER_LABELS[counter_type]}** impostato su `{template[:100]}`.")

    @counter.command(name="type")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_type(self, ctx: commands.Context, counter_type: str, channel_type: str):
        """Imposta il tipo di canale del contatore: voice oppure text."""
        counter_type = counter_type.lower()
        channel_type = channel_type.lower()
        if counter_type not in COUNTER_DEFAULTS:
            return await ctx.send("Tipo contatore valido: `total`, `members`, `bots`.")
        if channel_type not in {"voice", "text"}:
            return await ctx.send("Tipo canale valido: `voice` oppure `text`.")

        counters = await self.config.guild(ctx.guild).counters()
        data = counters[counter_type]
        old_channel = ctx.guild.get_channel(data.get("channel_id") or 0)
        data["channel_type"] = channel_type
        data["channel_id"] = None
        data["last_name"] = None
        data["last_count"] = None
        counters[counter_type] = data
        await self.config.guild(ctx.guild).counters.set(counters)

        if old_channel:
            try:
                await old_channel.delete(reason="MemberCounter cambio tipo canale")
            except discord.HTTPException:
                pass

        await self.refresh_all(ctx.guild)
        await ctx.send(f"**{COUNTER_LABELS[counter_type]}** ora usa un canale `{channel_type}`.")

    @counter.command(name="category")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        """Imposta la categoria dove devono stare i canali contatore."""
        await self.config.guild(ctx.guild).category_id.set(category.id)
        counters = await self.config.guild(ctx.guild).counters()
        for data in counters.values():
            channel = ctx.guild.get_channel(data.get("channel_id") or 0)
            if channel and channel.category_id != category.id:
                try:
                    await channel.edit(category=category, reason="MemberCounter cambio categoria")
                except discord.HTTPException:
                    pass
        await ctx.send(f"Categoria impostata su **{category.name}**.")

    @counter.command(name="update")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_update(self, ctx: commands.Context):
        """Forza subito l'aggiornamento di tutti i contatori."""
        await self.refresh_all(ctx.guild)
        await ctx.send("Contatori aggiornati.")

    @counter.command(name="status")
    async def counter_status(self, ctx: commands.Context):
        """Mostra configurazione e stato dei contatori del server."""
        counters = await self.config.guild(ctx.guild).counters()
        lines = []
        for key in ("total", "members", "bots"):
            data = counters[key]
            channel = ctx.guild.get_channel(data.get("channel_id") or 0)
            lines.append(
                f"{'✅' if data.get('enabled') else '❌'} **{COUNTER_LABELS[key]}**\n"
                f"Canale: {channel.mention if channel else '`non creato`'}\n"
                f"Tipo: `{data.get('channel_type', 'voice')}`\n"
                f"Nome: `{data.get('template')}`"
            )
        await ctx.send("\n\n".join(lines))

    @counter.command(name="reset")
    @commands.admin_or_permissions(manage_guild=True)
    async def counter_reset(self, ctx: commands.Context):
        """Elimina tutti i canali contatore e ripristina la configurazione iniziale."""
        view = ConfirmView(ctx.author, timeout=30)
        message = await ctx.send("Vuoi eliminare tutti i contatori e resettare la configurazione?", view=view)
        await view.wait()
        if not view.result:
            return await message.edit(content="Reset annullato.", view=None)

        counters = await self.config.guild(ctx.guild).counters()
        for data in counters.values():
            channel = ctx.guild.get_channel(data.get("channel_id") or 0)
            if channel:
                try:
                    await channel.delete(reason="MemberCounter reset")
                except discord.HTTPException:
                    pass
        await self.config.guild(ctx.guild).clear()
        await message.edit(content="MemberCounter resettato.", view=None)
