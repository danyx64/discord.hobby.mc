import asyncio

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


class AFKVoice(commands.Cog):
    """Mantiene il bot connesso a una vocale configurata tramite ID."""

    __author__ = "danyx64"
    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=481920734551, force_registration=True)
        self.config.register_guild(
            enabled=False,
            channel_id=0,
            self_mute=False,
            self_deaf=True,
            server_mute=False,
            server_deaf=False,
            reconnect_interval=20,
        )
        self._reconnect_task = None

    async def cog_load(self):
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    def cog_unload(self):
        if self._reconnect_task:
            self._reconnect_task.cancel()

    async def _apply_voice_state(self, guild: discord.Guild):
        voice = guild.voice_client
        if not voice or not voice.is_connected() or not voice.channel:
            return False, "bot non connesso"

        cfg = self.config.guild(guild)
        self_mute = await cfg.self_mute()
        self_deaf = await cfg.self_deaf()

        try:
            await guild.change_voice_state(
                channel=voice.channel,
                self_mute=self_mute,
                self_deaf=self_deaf,
            )
        except (discord.HTTPException, discord.Forbidden) as exc:
            return False, f"self state: {exc}"

        me = guild.me
        if me is not None:
            server_mute = await cfg.server_mute()
            server_deaf = await cfg.server_deaf()
            try:
                if me.voice and (me.voice.mute != server_mute or me.voice.deaf != server_deaf):
                    await me.edit(
                        mute=server_mute,
                        deafen=server_deaf,
                        reason="AFKVoice persistent voice state",
                    )
            except (discord.Forbidden, discord.HTTPException):
                # Il bot puo' restare AFK anche se Discord non consente di
                # server-mutare/deafenare il proprio membro.
                pass

        return True, "stato vocale applicato"

    async def _connect_guild(self, guild: discord.Guild):
        cfg = self.config.guild(guild)
        if not await cfg.enabled():
            return False, "disabilitato"

        channel_id = await cfg.channel_id()
        if not channel_id:
            return False, "nessun canale configurato"

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return False, "canale non trovato o non vocale"

        me = guild.me
        if me is None:
            return False, "bot non disponibile nel server"

        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.connect:
            return False, "mancano View Channel o Connect"

        try:
            voice = guild.voice_client
            if voice and voice.is_connected():
                if not voice.channel or voice.channel.id != channel.id:
                    await voice.move_to(channel)
            else:
                await channel.connect(
                    reconnect=True,
                    timeout=30.0,
                    self_deaf=await cfg.self_deaf(),
                    self_mute=await cfg.self_mute(),
                )
            await self._apply_voice_state(guild)
            return True, "connesso e configurato"
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError) as exc:
            return False, str(exc)

    async def _reconnect_loop(self):
        await self.bot.wait_until_red_ready()
        while True:
            try:
                enabled_guilds = []
                for guild in list(self.bot.guilds):
                    cfg = self.config.guild(guild)
                    if not await cfg.enabled():
                        continue
                    enabled_guilds.append(guild)
                    channel_id = await cfg.channel_id()
                    voice = guild.voice_client
                    if channel_id and (
                        voice is None
                        or not voice.is_connected()
                        or not voice.channel
                        or voice.channel.id != channel_id
                    ):
                        await self._connect_guild(guild)
                    elif voice and voice.is_connected():
                        await self._apply_voice_state(guild)

                interval = 20
                if enabled_guilds:
                    values = [await self.config.guild(g).reconnect_interval() for g in enabled_guilds]
                    interval = max(5, min(values or [20]))
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(20)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in list(self.bot.guilds):
            if await self.config.guild(guild).enabled():
                await self._connect_guild(guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.bot.user or member.id != self.bot.user.id:
            return
        guild = member.guild
        cfg = self.config.guild(guild)
        if not await cfg.enabled():
            return
        target_id = await cfg.channel_id()
        if not target_id:
            return
        if after.channel is None or after.channel.id != target_id:
            await asyncio.sleep(2)
            await self._connect_guild(guild)

    @commands.group(name="afkvoice", aliases=["afkvc"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def afkvoice(self, ctx: commands.Context):
        """Configura la connessione vocale AFK persistente."""
        await ctx.send_help(ctx.command)

    @afkvoice.command(name="set")
    async def set_channel(self, ctx: commands.Context, channel_id: int):
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return await ctx.send("Canale non trovato o non vocale.")
        me = ctx.guild.me
        if me is None:
            return await ctx.send("Impossibile controllare i permessi del bot.")
        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.connect:
            return await ctx.send("Il bot non ha **View Channel** e **Connect** in quel canale.")
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Canale AFK impostato su **{channel.name}** (`{channel.id}`).")

    @afkvoice.command(name="enable")
    async def enable(self, ctx: commands.Context):
        if not await self.config.guild(ctx.guild).channel_id():
            return await ctx.send(f"Prima usa `{ctx.clean_prefix}afkvoice set <ID>`.")
        await self.config.guild(ctx.guild).enabled.set(True)
        ok, reason = await self._connect_guild(ctx.guild)
        await ctx.send(f"AFKVoice **attivato**. Stato: `{reason}`" if ok else f"AFKVoice attivato, connessione fallita: `{reason}`. Riprovero automaticamente.")

    @afkvoice.command(name="disable")
    async def disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        voice = ctx.guild.voice_client
        if voice:
            try:
                await voice.disconnect(force=True)
            except discord.HTTPException:
                pass
        await ctx.send("AFKVoice **disattivato** e bot disconnesso.")

    @afkvoice.command(name="connect")
    async def connect_now(self, ctx: commands.Context):
        ok, reason = await self._connect_guild(ctx.guild)
        await ctx.send(f"{'Connesso' if ok else 'Connessione fallita'}: `{reason}`")

    @afkvoice.command(name="disconnect")
    async def disconnect_now(self, ctx: commands.Context):
        voice = ctx.guild.voice_client
        if voice is None:
            return await ctx.send("Il bot non e' connesso a una vocale.")
        try:
            await voice.disconnect(force=True)
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore: `{exc}`")
        await ctx.send("Bot disconnesso. Se AFKVoice e' attivo, rientrera automaticamente.")

    @afkvoice.command(name="selfmute")
    async def self_mute(self, ctx: commands.Context, mode: str):
        """Imposta il self-mute persistente: on/off."""
        mode = mode.lower()
        if mode not in {"on", "off"}:
            return await ctx.send(f"Uso: `{ctx.clean_prefix}afkvoice selfmute on|off`")
        await self.config.guild(ctx.guild).self_mute.set(mode == "on")
        ok, reason = await self._apply_voice_state(ctx.guild)
        await ctx.send(f"Self mute **{mode}**. `{reason}`")

    @afkvoice.command(name="selfdeaf")
    async def self_deaf(self, ctx: commands.Context, mode: str):
        """Imposta il self-deafen persistente: on/off."""
        mode = mode.lower()
        if mode not in {"on", "off"}:
            return await ctx.send(f"Uso: `{ctx.clean_prefix}afkvoice selfdeaf on|off`")
        await self.config.guild(ctx.guild).self_deaf.set(mode == "on")
        ok, reason = await self._apply_voice_state(ctx.guild)
        await ctx.send(f"Self deaf **{mode}**. `{reason}`")

    @afkvoice.command(name="servermute")
    async def server_mute(self, ctx: commands.Context, mode: str):
        """Prova ad applicare server-mute al bot: on/off."""
        mode = mode.lower()
        if mode not in {"on", "off"}:
            return await ctx.send(f"Uso: `{ctx.clean_prefix}afkvoice servermute on|off`")
        await self.config.guild(ctx.guild).server_mute.set(mode == "on")
        me = ctx.guild.me
        if me is None or not me.voice:
            return await ctx.send("Impostazione salvata; il bot non e' attualmente in vocale.")
        try:
            await me.edit(mute=mode == "on", reason="AFKVoice server mute")
            await ctx.send(f"Server mute **{mode}**.")
        except discord.Forbidden:
            await ctx.send("Impostazione salvata, ma Discord non consente al bot di applicare il server-mute con i permessi attuali.")
        except discord.HTTPException as exc:
            await ctx.send(f"Impostazione salvata, errore Discord: `{exc}`")

    @afkvoice.command(name="serverdeaf")
    async def server_deaf(self, ctx: commands.Context, mode: str):
        """Prova ad applicare server-deafen al bot: on/off."""
        mode = mode.lower()
        if mode not in {"on", "off"}:
            return await ctx.send(f"Uso: `{ctx.clean_prefix}afkvoice serverdeaf on|off`")
        await self.config.guild(ctx.guild).server_deaf.set(mode == "on")
        me = ctx.guild.me
        if me is None or not me.voice:
            return await ctx.send("Impostazione salvata; il bot non e' attualmente in vocale.")
        try:
            await me.edit(deafen=mode == "on", reason="AFKVoice server deaf")
            await ctx.send(f"Server deaf **{mode}**.")
        except discord.Forbidden:
            await ctx.send("Impostazione salvata, ma Discord non consente il server-deafen con i permessi attuali.")
        except discord.HTTPException as exc:
            await ctx.send(f"Impostazione salvata, errore Discord: `{exc}`")

    @afkvoice.command(name="interval")
    async def interval(self, ctx: commands.Context, seconds: int):
        """Imposta ogni quanti secondi controllare la riconnessione (5-300)."""
        if not 5 <= seconds <= 300:
            return await ctx.send("Intervallo valido: **5-300 secondi**.")
        await self.config.guild(ctx.guild).reconnect_interval.set(seconds)
        await ctx.send(f"Controllo riconnessione impostato ogni **{seconds}s**.")

    @afkvoice.command(name="reapply")
    async def reapply(self, ctx: commands.Context):
        """Riapplica subito mute/deaf configurati."""
        ok, reason = await self._apply_voice_state(ctx.guild)
        await ctx.send(f"{'Fatto' if ok else 'Fallito'}: `{reason}`")

    @afkvoice.command(name="status")
    async def status(self, ctx: commands.Context):
        cfg = self.config.guild(ctx.guild)
        enabled = await cfg.enabled()
        channel_id = await cfg.channel_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        voice = ctx.guild.voice_client
        me = ctx.guild.me
        current = f"{voice.channel.mention} (`{voice.channel.id}`)" if voice and voice.is_connected() and voice.channel else "non connesso"
        configured = f"{channel.mention} (`{channel.id}`)" if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else (f"ID `{channel_id}` non valido" if channel_id else "nessuno")
        server_state = "n/d"
        if me and me.voice:
            server_state = f"mute={me.voice.mute}, deaf={me.voice.deaf}, self_mute={me.voice.self_mute}, self_deaf={me.voice.self_deaf}"
        await ctx.send(
            f"AFKVoice: **{'attivo' if enabled else 'disattivato'}**\n"
            f"Canale configurato: {configured}\n"
            f"Connessione attuale: {current}\n"
            f"Self mute: **{await cfg.self_mute()}** | Self deaf: **{await cfg.self_deaf()}**\n"
            f"Server mute richiesto: **{await cfg.server_mute()}** | Server deaf richiesto: **{await cfg.server_deaf()}**\n"
            f"Stato Discord: `{server_state}`\n"
            f"Controllo automatico: ogni **{await cfg.reconnect_interval()}s** + reconnect immediato se viene spostato/disconnesso."
        )

    @afkvoice.command(name="clear")
    async def clear(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await self.config.guild(ctx.guild).channel_id.set(0)
        voice = ctx.guild.voice_client
        if voice:
            try:
                await voice.disconnect(force=True)
            except discord.HTTPException:
                pass
        await ctx.send("Configurazione AFKVoice rimossa.")
