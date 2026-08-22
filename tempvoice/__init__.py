import logging
from datetime import datetime, timezone

import discord

from . import tempvoice as tempvoice_module
from .tempvoice import TempVoice, UserActionView

log = logging.getLogger("red.danyx64.tempvoice")


class BitrateModal(discord.ui.Modal, title="Bitrate vocale"):
    kbps = discord.ui.TextInput(label="Bitrate in kbps", placeholder="8-384", max_length=3)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        room = await self.cog.require_owned_room(interaction)
        if room is None:
            return
        try:
            kbps = int(str(self.kbps))
        except ValueError:
            return await interaction.response.send_message("Inserisci un numero tra 8 e 384.", ephemeral=True)
        if not 8 <= kbps <= 384:
            return await interaction.response.send_message("Inserisci un numero tra 8 e 384.", ephemeral=True)
        value = min(kbps * 1000, interaction.guild.bitrate_limit)
        await room.edit(bitrate=value)
        await interaction.response.send_message(f"Bitrate impostato a **{value // 1000} kbps**.", ephemeral=True)


class ActionButton(discord.ui.Button):
    def __init__(self, emoji, custom_id, row, handler, style=discord.ButtonStyle.secondary):
        # Solo emoji: la spiegazione e' nell'embed, come richiesto.
        super().__init__(emoji=emoji, style=style, custom_id=custom_id, row=row)
        self.handler = handler

    async def callback(self, interaction):
        await self.handler(interaction)


class TempVoicePanel(tempvoice_module.TempVoicePanel):
    """Pannello completo: pulsanti solo emoji + tutte le azioni mancanti."""

    def __init__(self, cog):
        super().__init__(cog)

        # Rimuove qualsiasi label eventualmente ereditata da vecchie versioni.
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.label = None

        # Funzioni presenti nei comandi /voice ma mancanti dalla pulsantiera base.
        self.add_item(ActionButton("👤", "tempvoice:untrust", 2, self._untrust))
        self.add_item(ActionButton("🔓", "tempvoice:unblock", 2, self._unblock))
        self.add_item(ActionButton("🎚️", "tempvoice:bitrate", 2, self._bitrate))
        self.add_item(ActionButton("♻️", "tempvoice:reset", 2, self._reset))
        self.add_item(ActionButton("ℹ️", "tempvoice:info", 2, self._info))

    async def _untrust(self, interaction):
        if await self.owned(interaction):
            await interaction.response.send_message(
                "Scegli chi rimuovere dai fidati:", view=UserActionView(self.cog, "untrust"), ephemeral=True
            )

    async def _unblock(self, interaction):
        if await self.owned(interaction):
            await interaction.response.send_message(
                "Scegli chi sbloccare:", view=UserActionView(self.cog, "unblock"), ephemeral=True
            )

    async def _bitrate(self, interaction):
        if await self.owned(interaction):
            await interaction.response.send_modal(BitrateModal(self.cog))

    async def _reset(self, interaction):
        room = await self.owned(interaction)
        if room is None:
            return
        owner = interaction.user
        for target in list(room.overwrites):
            if target not in {interaction.guild.default_role, interaction.guild.me, owner}:
                try:
                    await room.set_permissions(target, overwrite=None)
                except discord.HTTPException:
                    pass
        await room.set_permissions(interaction.guild.default_role, view_channel=True, connect=False)
        await room.set_permissions(owner, view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True)
        observer = interaction.guild.get_role(await self.cog.config.guild(interaction.guild).observer_role())
        if observer:
            await room.set_permissions(observer, view_channel=True, connect=True)
        info = await self.cog.room_info(room)
        info.update({"privacy": "private", "trusted": [], "blocked": []})
        await self.cog.save_room_info(room, info)
        await interaction.response.send_message("Configurazione della vocale ripristinata.", ephemeral=True)

    async def _info(self, interaction):
        room = await self.cog.get_user_room(interaction.guild, interaction.user)
        if room is None:
            return await interaction.response.send_message("Devi essere in una vocale temporanea.", ephemeral=True)
        info = await self.cog.room_info(room)
        owner = interaction.guild.get_member(int(info.get("owner_id", 0)))
        created = int(info.get("created_at", 0))
        await interaction.response.send_message(
            f"**Vocale:** {room.mention}\n"
            f"**Proprietario:** {owner.mention if owner else info.get('owner_id')}\n"
            f"**Privacy:** `{info.get('privacy', 'private')}`\n"
            f"**Limite:** `{room.user_limit or 'nessuno'}`\n"
            f"**Bitrate:** `{room.bitrate // 1000} kbps`\n"
            f"**Fidati:** `{len(info.get('trusted', []))}` | **Bloccati:** `{len(info.get('blocked', []))}`\n"
            f"**Creata:** <t:{created}:R>",
            ephemeral=True,
        )


async def robust_create_room(self, member: discord.Member):
    """Crea e sposta nella stanza, registrando sempre il motivo di eventuali fallimenti."""
    guild = member.guild
    cfg = self.config.guild(guild)
    category_id = await cfg.category_id()
    category = guild.get_channel(category_id)

    if not isinstance(category, discord.CategoryChannel):
        log.error(
            "[TempVoice] Creazione fallita per %s (%s): category_id=%s non e' una categoria valida",
            member,
            member.id,
            category_id,
        )
        return None

    me = guild.me
    if me is None:
        log.error("[TempVoice] Creazione fallita: guild.me non disponibile")
        return None

    category_perms = category.permissions_for(me)
    missing = []
    if not category_perms.view_channel:
        missing.append("View Channel")
    if not category_perms.manage_channels:
        missing.append("Manage Channels")
    if not category_perms.connect:
        missing.append("Connect")
    if not category_perms.move_members:
        missing.append("Move Members")
    if missing:
        log.error(
            "[TempVoice] Permessi mancanti nella categoria %s (%s): %s",
            category.name,
            category.id,
            ", ".join(missing),
        )
        return None

    observer_id = await cfg.observer_role()
    observer = guild.get_role(observer_id) if observer_id else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
        member: discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True
        ),
        me: discord.PermissionOverwrite(
            view_channel=True, connect=True, manage_channels=True, move_members=True
        ),
    }
    if observer:
        overwrites[observer] = discord.PermissionOverwrite(view_channel=True, connect=True)

    bitrate = max(8000, min(int(await cfg.default_bitrate()), guild.bitrate_limit))
    try:
        room = await guild.create_voice_channel(
            self.format_name(await cfg.name_template(), member),
            category=category,
            overwrites=overwrites,
            user_limit=max(0, min(int(await cfg.default_limit()), 99)),
            bitrate=bitrate,
            reason=f"TempVoice created for {member}",
        )
    except discord.Forbidden as exc:
        log.exception("[TempVoice] 403 durante creazione vocale per %s: %s", member, exc)
        return None
    except discord.HTTPException as exc:
        log.exception("[TempVoice] Errore HTTP durante creazione vocale per %s: %s", member, exc)
        return None

    await self.save_room_info(
        room,
        {
            "owner_id": member.id,
            "created_at": int(datetime.now(timezone.utc).timestamp()),
            "privacy": "private",
            "trusted": [],
            "blocked": [],
        },
    )
    log.info("[TempVoice] Creata %s (%s) per %s (%s)", room.name, room.id, member, member.id)

    try:
        await member.move_to(room, reason="TempVoice join-to-create")
        log.info("[TempVoice] Spostato %s (%s) in %s (%s)", member, member.id, room.name, room.id)
        return room
    except discord.Forbidden as exc:
        log.exception("[TempVoice] 403 durante lo spostamento di %s: %s", member, exc)
    except discord.HTTPException as exc:
        log.exception("[TempVoice] Errore HTTP durante lo spostamento di %s: %s", member, exc)

    await self.delete_room(room)
    return None


# Usa sempre la versione diagnostica per il join-to-create.
TempVoice.create_room = robust_create_room
# Fa usare al comando /voice panel questa View emoji-only.
tempvoice_module.TempVoicePanel = TempVoicePanel


# Migliora /voice panel: risposta immediata (evita Unknown interaction) + legenda completa.
panel_command = TempVoice.voice.get_command("panel")
if panel_command is not None:
    async def panel_callback(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="Gestione vocale temporanea",
            description=(
                "Entra nella tua vocale temporanea e usa i pulsanti qui sotto.\n\n"
                "✏️ **Rinomina** — cambia il nome della stanza\n"
                "👥 **Limite** — imposta il numero massimo di utenti\n"
                "🔒 **Privacy** — apre o blocca la stanza\n"
                "🙋 **Fidati** — autorizza sempre un utente\n"
                "🚫 **Blocca** — nasconde e impedisce l'accesso a un utente\n"
                "📨 **Invita** — invia in DM un invito alla stanza\n"
                "🥾 **Espelli** — rimuove un utente dalla stanza\n"
                "👑 **Rivendica** — prende la proprieta' se il proprietario non c'e'\n"
                "🔁 **Trasferisci** — passa la proprieta' a un altro utente\n"
                "🗑️ **Elimina** — elimina la tua stanza\n"
                "👤 **Sfiducia** — rimuove un utente dai fidati\n"
                "🔓 **Sblocca** — rimuove un utente dai bloccati\n"
                "🎚️ **Bitrate** — modifica la qualita' audio\n"
                "♻️ **Reset** — ripristina permessi e impostazioni\n"
                "ℹ️ **Info** — mostra proprietario e configurazione"
            ),
            colour=discord.Colour.blurple(),
        )
        msg = await channel.send(embed=embed, view=TempVoicePanel(self))
        cfg = self.config.guild(interaction.guild)
        await cfg.panel_channel.set(channel.id)
        await cfg.panel_message.set(msg.id)
        await interaction.followup.send(f"Pannello inviato in {channel.mention}.", ephemeral=True)

    panel_command._callback = panel_callback


# Estende /voice status con una diagnosi pratica del join-to-create.
status_command = TempVoice.voice.get_command("status")
if status_command is not None:
    async def status_callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = self.config.guild(guild)
        enabled = await cfg.enabled()
        creator_id = await cfg.creator_channel()
        category_id = await cfg.category_id()
        creator = guild.get_channel(creator_id)
        category = guild.get_channel(category_id)
        observer = guild.get_role(await cfg.observer_role())
        rooms = await cfg.rooms()
        me = guild.me

        checks = []
        checks.append(f"{'✅' if enabled else '❌'} TempVoice abilitato")
        checks.append(f"{'✅' if isinstance(creator, discord.VoiceChannel) else '❌'} Vocale creatore valida (`{creator_id}`)")
        checks.append(f"{'✅' if isinstance(category, discord.CategoryChannel) else '❌'} Categoria valida (`{category_id}`)")

        if isinstance(category, discord.CategoryChannel) and me:
            perms = category.permissions_for(me)
            for label, value in (
                ("View Channel", perms.view_channel),
                ("Manage Channels", perms.manage_channels),
                ("Connect", perms.connect),
                ("Move Members", perms.move_members),
            ):
                checks.append(f"{'✅' if value else '❌'} Bot: {label}")

        embed = discord.Embed(title="TempVoice - stato e diagnostica", colour=discord.Colour.blurple())
        embed.add_field(name="Configurazione", value="\n".join(checks), inline=False)
        embed.add_field(
            name="Dettagli",
            value=(
                f"**Creatore:** {getattr(creator, 'mention', 'non configurato')}\n"
                f"**Categoria:** **{getattr(category, 'name', 'non configurata')}**\n"
                f"**Template:** `{await cfg.name_template()}`\n"
                f"**Ruolo osservatore:** {observer.mention if observer else 'nessuno'}\n"
                f"**Vocali attive:** **{len(rooms)}**"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    status_command._callback = status_callback


async def setup(bot):
    cog = TempVoice(bot)

    async def safe_cog_load():
        bot.add_view(TempVoicePanel(cog))

    cog.cog_load = safe_cog_load
    await bot.add_cog(cog, override=True)
    await bot.enable_app_command("voice")
    await bot.tree.red_check_enabled()
    await bot.tree.sync()
