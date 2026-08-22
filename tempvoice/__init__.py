import discord

from . import tempvoice as tempvoice_module
from .tempvoice import TempVoice, UserActionView


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


class TempVoicePanel(tempvoice_module.TempVoicePanel):
    """Pannello completo in stile TempVoice, con etichette leggibili e tutte le azioni."""

    def __init__(self, cog):
        super().__init__(cog)
        labels = {
            "tempvoice:rename": "Rinomina",
            "tempvoice:limit": "Limite",
            "tempvoice:privacy": "Privacy",
            "tempvoice:trust": "Fidati",
            "tempvoice:block": "Blocca",
            "tempvoice:invite": "Invita",
            "tempvoice:kick": "Espelli",
            "tempvoice:claim": "Rivendica",
            "tempvoice:transfer": "Trasferisci",
            "tempvoice:delete": "Elimina",
        }
        for item in self.children:
            if getattr(item, "custom_id", None) in labels:
                item.label = labels[item.custom_id]

        # Funzioni presenti nei comandi /voice ma mancanti dalla vecchia pulsantiera.
        self.add_item(ActionButton("Sfiducia", "👤", "tempvoice:untrust", 2, self._untrust))
        self.add_item(ActionButton("Sblocca", "🔓", "tempvoice:unblock", 2, self._unblock))
        self.add_item(ActionButton("Bitrate", "🎚️", "tempvoice:bitrate", 2, self._bitrate))
        self.add_item(ActionButton("Reset", "♻️", "tempvoice:reset", 2, self._reset))
        self.add_item(ActionButton("Info", "ℹ️", "tempvoice:info", 2, self._info))

    async def _untrust(self, interaction):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi rimuovere dai fidati:", view=UserActionView(self.cog, "untrust"), ephemeral=True)

    async def _unblock(self, interaction):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi sbloccare:", view=UserActionView(self.cog, "unblock"), ephemeral=True)

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


class ActionButton(discord.ui.Button):
    def __init__(self, label, emoji, custom_id, row, handler):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=custom_id, row=row)
        self.handler = handler

    async def callback(self, interaction):
        await self.handler(interaction)


# Sostituisce il pannello nel modulo originale: anche /voice panel usera' questa versione.
tempvoice_module.TempVoicePanel = TempVoicePanel


async def setup(bot):
    cog = TempVoice(bot)

    async def safe_cog_load():
        bot.add_view(TempVoicePanel(cog))

    cog.cog_load = safe_cog_load
    await bot.add_cog(cog, override=True)
    await bot.enable_app_command("voice")
    await bot.tree.red_check_enabled()
    await bot.tree.sync()
