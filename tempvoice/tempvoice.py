import asyncio
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red


class RenameModal(discord.ui.Modal, title="Rinomina vocale"):
    room_name = discord.ui.TextInput(label="Nuovo nome", max_length=100)

    def __init__(self, cog: "TempVoice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        room = await self.cog.require_owned_room(interaction)
        if room is None:
            return
        await room.edit(name=str(self.room_name)[:100], reason=f"TempVoice rename by {interaction.user}")
        await interaction.response.send_message(f"Nome aggiornato: **{room.name}**", ephemeral=True)


class LimitModal(discord.ui.Modal, title="Limite utenti"):
    limit = discord.ui.TextInput(label="Limite (0 = nessun limite)", placeholder="0-99", max_length=2)

    def __init__(self, cog: "TempVoice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        room = await self.cog.require_owned_room(interaction)
        if room is None:
            return
        try:
            value = int(str(self.limit))
        except ValueError:
            return await interaction.response.send_message("Inserisci un numero da 0 a 99.", ephemeral=True)
        if not 0 <= value <= 99:
            return await interaction.response.send_message("Inserisci un numero da 0 a 99.", ephemeral=True)
        await room.edit(user_limit=value, reason=f"TempVoice limit by {interaction.user}")
        await interaction.response.send_message(f"Limite impostato a **{value if value else 'nessun limite'}**.", ephemeral=True)


class UserActionSelect(discord.ui.UserSelect):
    def __init__(self, cog: "TempVoice", action: str):
        super().__init__(placeholder="Seleziona un utente", min_values=1, max_values=1)
        self.cog = cog
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.cog.member_action(interaction, self.action, self.values[0])


class UserActionView(discord.ui.View):
    def __init__(self, cog: "TempVoice", action: str):
        super().__init__(timeout=60)
        self.add_item(UserActionSelect(cog, action))


class TempVoicePanel(discord.ui.View):
    def __init__(self, cog: "TempVoice"):
        super().__init__(timeout=None)
        self.cog = cog

    async def owned(self, interaction: discord.Interaction):
        return await self.cog.require_owned_room(interaction)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="tempvoice:rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_modal(RenameModal(self.cog))

    @discord.ui.button(emoji="👥", style=discord.ButtonStyle.secondary, custom_id="tempvoice:limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_modal(LimitModal(self.cog))

    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="tempvoice:privacy", row=0)
    async def privacy(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.owned(interaction)
        if room is None:
            return
        info = await self.cog.room_info(room)
        new_mode = "open" if info.get("privacy") != "open" else "private"
        await self.cog.set_privacy(room, new_mode)
        await interaction.response.send_message(
            "Vocale aperta." if new_mode == "open" else "Vocale privata/bloccata.", ephemeral=True
        )

    @discord.ui.button(emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="tempvoice:trust", row=0)
    async def trust(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi rendere fidato:", view=UserActionView(self.cog, "trust"), ephemeral=True)

    @discord.ui.button(emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="tempvoice:block", row=0)
    async def block(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi bloccare:", view=UserActionView(self.cog, "block"), ephemeral=True)

    @discord.ui.button(emoji="📨", style=discord.ButtonStyle.secondary, custom_id="tempvoice:invite", row=1)
    async def invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi invitare:", view=UserActionView(self.cog, "invite"), ephemeral=True)

    @discord.ui.button(emoji="🥾", style=discord.ButtonStyle.secondary, custom_id="tempvoice:kick", row=1)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli chi espellere:", view=UserActionView(self.cog, "kick"), ephemeral=True)

    @discord.ui.button(emoji="👑", style=discord.ButtonStyle.secondary, custom_id="tempvoice:claim", row=1)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.claim_room(interaction)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="tempvoice:transfer", row=1)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.owned(interaction):
            await interaction.response.send_message("Scegli il nuovo proprietario:", view=UserActionView(self.cog, "transfer"), ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="tempvoice:delete", row=1)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.owned(interaction)
        if room is None:
            return
        await interaction.response.send_message("Vocale eliminata.", ephemeral=True)
        await self.cog.delete_room(room)


class TempVoice(commands.Cog):
    """TempVoice join-to-create con slash /voice e pannello persistente."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    voice = app_commands.Group(name="voice", description="Gestisci i canali vocali temporanei")

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=513702889314221607, force_registration=True)
        self.config.register_guild(
            enabled=False,
            creator_channel=0,
            category_id=0,
            panel_channel=0,
            panel_message=0,
            observer_role=0,
            name_template="Vocale-{owner}",
            default_limit=0,
            default_bitrate=64000,
            rooms={},
        )

    async def cog_load(self):
        self.bot.add_view(TempVoicePanel(self))
        try:
            self.bot.tree.add_command(self.voice)
        except app_commands.CommandAlreadyRegistered:
            pass

    async def cog_unload(self):
        try:
            self.bot.tree.remove_command("voice", type=discord.AppCommandType.chat_input)
        except Exception:
            pass

    async def room_info(self, channel: discord.VoiceChannel):
        rooms = await self.config.guild(channel.guild).rooms()
        return rooms.get(str(channel.id), {})

    async def save_room_info(self, channel: discord.VoiceChannel, data: dict):
        async with self.config.guild(channel.guild).rooms() as rooms:
            rooms[str(channel.id)] = data

    async def delete_room_info(self, channel: discord.VoiceChannel):
        async with self.config.guild(channel.guild).rooms() as rooms:
            rooms.pop(str(channel.id), None)

    async def get_user_room(self, guild: discord.Guild, user: discord.Member) -> Optional[discord.VoiceChannel]:
        if not user.voice or not isinstance(user.voice.channel, discord.VoiceChannel):
            return None
        channel = user.voice.channel
        return channel if await self.room_info(channel) else None

    async def get_owned_room(self, guild: discord.Guild, owner_id: int):
        rooms = await self.config.guild(guild).rooms()
        for cid, data in rooms.items():
            if int(data.get("owner_id", 0)) == owner_id:
                channel = guild.get_channel(int(cid))
                if isinstance(channel, discord.VoiceChannel):
                    return channel
        return None

    async def is_owner(self, channel: discord.VoiceChannel, user: discord.abc.User) -> bool:
        return int((await self.room_info(channel)).get("owner_id", 0)) == user.id

    async def require_owned_room(self, interaction: discord.Interaction):
        room = await self.get_user_room(interaction.guild, interaction.user)
        if room is None:
            if interaction.response.is_done():
                await interaction.followup.send("Devi essere dentro una vocale temporanea.", ephemeral=True)
            else:
                await interaction.response.send_message("Devi essere dentro una vocale temporanea.", ephemeral=True)
            return None
        if not await self.is_owner(room, interaction.user):
            if interaction.response.is_done():
                await interaction.followup.send("Solo il proprietario può usare questa azione.", ephemeral=True)
            else:
                await interaction.response.send_message("Solo il proprietario può usare questa azione.", ephemeral=True)
            return None
        return room

    async def set_privacy(self, room: discord.VoiceChannel, mode: str):
        info = await self.room_info(room)
        overwrite = room.overwrites_for(room.guild.default_role)
        if mode == "open":
            overwrite.view_channel = True
            overwrite.connect = True
        elif mode == "hidden":
            overwrite.view_channel = False
            overwrite.connect = False
        else:
            mode = "private"
            overwrite.view_channel = True
            overwrite.connect = False
        await room.set_permissions(room.guild.default_role, overwrite=overwrite, reason="TempVoice privacy")
        info["privacy"] = mode
        await self.save_room_info(room, info)

    async def member_action(self, interaction: discord.Interaction, action: str, target: discord.Member):
        room = await self.require_owned_room(interaction)
        if room is None:
            return
        info = await self.room_info(room)
        trusted = set(info.get("trusted", []))
        blocked = set(info.get("blocked", []))

        if target.id == interaction.user.id and action in {"kick", "block", "transfer"}:
            return await interaction.response.send_message("Non puoi usare questa azione su te stesso.", ephemeral=True)

        if action == "trust":
            trusted.add(target.id)
            blocked.discard(target.id)
            await room.set_permissions(target, view_channel=True, connect=True)
            text = f"{target.mention} ora è fidato."
        elif action == "untrust":
            trusted.discard(target.id)
            await room.set_permissions(target, overwrite=None)
            text = f"{target.mention} rimosso dai fidati."
        elif action == "block":
            blocked.add(target.id)
            trusted.discard(target.id)
            await room.set_permissions(target, view_channel=False, connect=False)
            if target.voice and target.voice.channel == room:
                try:
                    await target.move_to(None, reason="TempVoice block")
                except discord.HTTPException:
                    pass
            text = f"{target.mention} bloccato."
        elif action == "unblock":
            blocked.discard(target.id)
            await room.set_permissions(target, overwrite=None)
            text = f"{target.mention} sbloccato."
        elif action == "kick":
            if not target.voice or target.voice.channel != room:
                text = "Quell'utente non è nella tua vocale."
            else:
                await target.move_to(None, reason=f"TempVoice kick by {interaction.user}")
                text = f"{target.mention} espulso dalla vocale."
        elif action == "transfer":
            if not target.voice or target.voice.channel != room:
                return await interaction.response.send_message("Il nuovo proprietario deve essere nella vocale.", ephemeral=True)
            old_owner = interaction.guild.get_member(int(info.get("owner_id", 0)))
            if old_owner:
                await room.set_permissions(old_owner, overwrite=None)
            await room.set_permissions(target, view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True)
            info["owner_id"] = target.id
            text = f"Proprietà trasferita a {target.mention}."
        elif action == "invite":
            await room.set_permissions(target, view_channel=True, connect=True)
            try:
                invite = await room.create_invite(max_age=300, max_uses=1, unique=True, reason="TempVoice invite")
                await target.send(f"{interaction.user.mention} ti ha invitato nella sua vocale temporanea **{room.name}**: {invite.url}")
                text = f"Invito inviato in DM a {target.mention}."
            except discord.Forbidden:
                text = "Non posso inviare il DM a quell'utente."
        else:
            text = "Azione sconosciuta."

        info["trusted"] = list(trusted)
        info["blocked"] = list(blocked)
        await self.save_room_info(room, info)
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def claim_room(self, interaction: discord.Interaction):
        room = await self.get_user_room(interaction.guild, interaction.user)
        if room is None:
            return await interaction.response.send_message("Devi essere in una vocale temporanea.", ephemeral=True)
        info = await self.room_info(room)
        owner = interaction.guild.get_member(int(info.get("owner_id", 0)))
        if owner and owner.voice and owner.voice.channel == room:
            return await interaction.response.send_message("Il proprietario è ancora nella vocale.", ephemeral=True)
        if owner:
            await room.set_permissions(owner, overwrite=None)
        await room.set_permissions(interaction.user, view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True)
        info["owner_id"] = interaction.user.id
        await self.save_room_info(room, info)
        await interaction.response.send_message("Hai rivendicato la proprietà della vocale.", ephemeral=True)

    async def delete_room(self, room: discord.VoiceChannel):
        await self.delete_room_info(room)
        try:
            await room.delete(reason="TempVoice empty/deleted")
        except discord.HTTPException:
            pass

    def format_name(self, template: str, member: discord.Member):
        values = {
            "owner": member.display_name,
            "username": member.name,
            "displayname": member.display_name,
            "user_id": str(member.id),
            "guild": member.guild.name,
            "server": member.guild.name,
        }
        try:
            return template.format(**values)[:100]
        except (KeyError, ValueError):
            return f"Vocale-{member.display_name}"[:100]

    async def create_room(self, member: discord.Member):
        guild = member.guild
        cfg = self.config.guild(guild)
        category = guild.get_channel(await cfg.category_id())
        if not isinstance(category, discord.CategoryChannel):
            return
        observer_id = await cfg.observer_role()
        observer = guild.get_role(observer_id) if observer_id else None
        bot_member = guild.me
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            member: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True),
        }
        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True)
        if observer:
            overwrites[observer] = discord.PermissionOverwrite(view_channel=True, connect=True)

        bitrate = max(8000, min(int(await cfg.default_bitrate()), guild.bitrate_limit))
        room = await guild.create_voice_channel(
            self.format_name(await cfg.name_template(), member),
            category=category,
            overwrites=overwrites,
            user_limit=max(0, min(int(await cfg.default_limit()), 99)),
            bitrate=bitrate,
            reason=f"TempVoice created for {member}",
        )
        await self.save_room_info(room, {
            "owner_id": member.id,
            "created_at": int(datetime.now(timezone.utc).timestamp()),
            "privacy": "private",
            "trusted": [],
            "blocked": [],
        })
        try:
            await member.move_to(room, reason="TempVoice join-to-create")
        except discord.HTTPException:
            await self.delete_room(room)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or not await self.config.guild(member.guild).enabled():
            return
        creator_id = await self.config.guild(member.guild).creator_channel()
        if after.channel and after.channel.id == creator_id:
            existing = await self.get_owned_room(member.guild, member.id)
            if existing:
                try:
                    await member.move_to(existing, reason="TempVoice existing room")
                except discord.HTTPException:
                    pass
            else:
                try:
                    await self.create_room(member)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if before.channel and isinstance(before.channel, discord.VoiceChannel) and await self.room_info(before.channel):
            if not before.channel.members:
                await asyncio.sleep(1)
                current = member.guild.get_channel(before.channel.id)
                if isinstance(current, discord.VoiceChannel) and not current.members:
                    await self.delete_room(current)

    @voice.command(name="setup", description="Configura creatore, categoria e ruolo che vede tutte le vocali")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_setup(self, interaction: discord.Interaction, creator: discord.VoiceChannel, category: discord.CategoryChannel, observer_role: Optional[discord.Role] = None):
        cfg = self.config.guild(interaction.guild)
        await cfg.creator_channel.set(creator.id)
        await cfg.category_id.set(category.id)
        await cfg.observer_role.set(observer_role.id if observer_role else 0)
        await interaction.response.send_message(
            f"Creatore: {creator.mention}\nCategoria: **{category.name}**\nRuolo osservatore: {observer_role.mention if observer_role else 'nessuno'}",
            ephemeral=True,
        )

    @voice.command(name="panel", description="Invia la pulsantiera TempVoice")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = discord.Embed(
            title="TempVoice Interface",
            description="Questa interfaccia può essere usata per gestire i canali vocali temporanei. Altre opzioni sono disponibili tramite **/voice**.\n\nUsa i pulsanti sottostanti mentre sei nella tua vocale temporanea.",
            colour=discord.Colour.blurple(),
        )
        msg = await channel.send(embed=embed, view=TempVoicePanel(self))
        cfg = self.config.guild(interaction.guild)
        await cfg.panel_channel.set(channel.id)
        await cfg.panel_message.set(msg.id)
        await interaction.response.send_message(f"Pannello inviato in {channel.mention}.", ephemeral=True)

    @voice.command(name="enable", description="Abilita TempVoice")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_enable(self, interaction: discord.Interaction):
        await self.config.guild(interaction.guild).enabled.set(True)
        await interaction.response.send_message("TempVoice abilitato.", ephemeral=True)

    @voice.command(name="disable", description="Disabilita TempVoice")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_disable(self, interaction: discord.Interaction):
        await self.config.guild(interaction.guild).enabled.set(False)
        await interaction.response.send_message("TempVoice disabilitato.", ephemeral=True)

    @voice.command(name="status", description="Mostra la configurazione TempVoice")
    async def slash_status(self, interaction: discord.Interaction):
        cfg = self.config.guild(interaction.guild)
        creator = interaction.guild.get_channel(await cfg.creator_channel())
        category = interaction.guild.get_channel(await cfg.category_id())
        observer = interaction.guild.get_role(await cfg.observer_role())
        rooms = await cfg.rooms()
        await interaction.response.send_message(
            f"Stato: **{'attivo' if await cfg.enabled() else 'disattivato'}**\n"
            f"Creatore: {getattr(creator, 'mention', 'non configurato')}\n"
            f"Categoria: **{getattr(category, 'name', 'non configurata')}**\n"
            f"Template: `{await cfg.name_template()}`\n"
            f"Ruolo osservatore: {observer.mention if observer else 'nessuno'}\n"
            f"Vocali attive: **{len(rooms)}**",
            ephemeral=True,
        )

    @voice.command(name="template", description="Imposta il nome predefinito delle vocali")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_template(self, interaction: discord.Interaction, template: str):
        await self.config.guild(interaction.guild).name_template.set(template[:100])
        await interaction.response.send_message(
            "Template aggiornato. Placeholder: `{owner}`, `{username}`, `{displayname}`, `{user_id}`, `{guild}`, `{server}`.", ephemeral=True
        )

    @voice.command(name="invite", description="Invia un messaggio privato per unirti alla tua vocale")
    async def slash_invite(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "invite", user)

    @voice.command(name="kick", description="Espelli un utente dalla tua vocale temporanea")
    async def slash_kick(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "kick", user)

    @voice.command(name="limit", description="Modifica il limite utenti della tua vocale")
    async def slash_limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        room = await self.require_owned_room(interaction)
        if room:
            await room.edit(user_limit=limit)
            await interaction.response.send_message(f"Limite impostato a **{limit if limit else 'nessun limite'}**.", ephemeral=True)

    @voice.command(name="name", description="Cambia il nome della tua vocale temporanea")
    async def slash_name(self, interaction: discord.Interaction, name: str):
        room = await self.require_owned_room(interaction)
        if room:
            await room.edit(name=name[:100])
            await interaction.response.send_message(f"Nome aggiornato: **{room.name}**", ephemeral=True)

    @voice.command(name="privacy", description="Apri, blocca o nascondi la tua vocale")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Aperta", value="open"),
        app_commands.Choice(name="Privata/Bloccata", value="private"),
        app_commands.Choice(name="Nascosta", value="hidden"),
    ])
    async def slash_privacy(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        room = await self.require_owned_room(interaction)
        if room:
            await self.set_privacy(room, mode.value)
            await interaction.response.send_message(f"Privacy impostata su **{mode.name}**.", ephemeral=True)

    @voice.command(name="transfer", description="Trasferisci la proprietà della tua vocale")
    async def slash_transfer(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "transfer", user)

    @voice.command(name="trust", description="Rendi un utente fidato")
    async def slash_trust(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "trust", user)

    @voice.command(name="untrust", description="Rimuovi un utente dai fidati")
    async def slash_untrust(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "untrust", user)

    @voice.command(name="block", description="Blocca un utente dalla tua vocale")
    async def slash_block(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "block", user)

    @voice.command(name="unblock", description="Sblocca un utente")
    async def slash_unblock(self, interaction: discord.Interaction, user: discord.Member):
        await self.member_action(interaction, "unblock", user)

    @voice.command(name="reset", description="Ripristina la configurazione della tua vocale")
    async def slash_reset(self, interaction: discord.Interaction):
        room = await self.require_owned_room(interaction)
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
        observer = interaction.guild.get_role(await self.config.guild(interaction.guild).observer_role())
        if observer:
            await room.set_permissions(observer, view_channel=True, connect=True)
        info = await self.room_info(room)
        info.update({"privacy": "private", "trusted": [], "blocked": []})
        await self.save_room_info(room, info)
        await interaction.response.send_message("Configurazione ripristinata.", ephemeral=True)

    @voice.command(name="bitrate", description="Cambia il bitrate della tua vocale")
    async def slash_bitrate(self, interaction: discord.Interaction, kbps: app_commands.Range[int, 8, 384]):
        room = await self.require_owned_room(interaction)
        if room:
            value = min(kbps * 1000, interaction.guild.bitrate_limit)
            await room.edit(bitrate=value)
            await interaction.response.send_message(f"Bitrate impostato a **{value // 1000} kbps**.", ephemeral=True)

    @voice.command(name="claim", description="Rivendica una vocale temporanea")
    async def slash_claim(self, interaction: discord.Interaction):
        await self.claim_room(interaction)

    @voice.command(name="info", description="Mostra informazioni sulla vocale temporanea")
    async def slash_info(self, interaction: discord.Interaction):
        room = await self.get_user_room(interaction.guild, interaction.user)
        if room is None:
            return await interaction.response.send_message("Devi essere in una vocale temporanea.", ephemeral=True)
        info = await self.room_info(room)
        owner = interaction.guild.get_member(int(info.get("owner_id", 0)))
        created = int(info.get("created_at", 0))
        await interaction.response.send_message(
            f"**Vocale:** {room.mention}\n"
            f"**Proprietario:** {owner.mention if owner else info.get('owner_id')}\n"
            f"**Privacy:** `{info.get('privacy', 'private')}`\n"
            f"**Limite:** `{room.user_limit or 'nessuno'}`\n"
            f"**Bitrate:** `{room.bitrate // 1000} kbps`\n"
            f"**Fidati:** `{len(info.get('trusted', []))}`\n"
            f"**Bloccati:** `{len(info.get('blocked', []))}`\n"
            f"**Creata:** <t:{created}:R>",
            ephemeral=True,
        )
