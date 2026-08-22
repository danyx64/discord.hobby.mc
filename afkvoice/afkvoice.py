import asyncio

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


class AFKVoice(commands.Cog):
    """Mantiene il bot connesso a una vocale configurata tramite ID."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=481920734551, force_registration=True)
        self.config.register_guild(enabled=False, channel_id=0)
        self._reconnect_task = None

    async def cog_load(self):
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    def cog_unload(self):
        if self._reconnect_task:
            self._reconnect_task.cancel()

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

        voice = guild.voice_client
        try:
            if voice and voice.is_connected():
                if voice.channel and voice.channel.id == channel.id:
                    return True, "gia connesso"
                await voice.move_to(channel)
                return True, "spostato"

            await channel.connect(reconnect=True, timeout=30.0, self_deaf=True)
            return True, "connesso"
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError) as exc:
            return False, str(exc)

    async def _reconnect_loop(self):
        await self.bot.wait_until_red_ready()
        while True:
            try:
                for guild in list(self.bot.guilds):
                    cfg = self.config.guild(guild)
                    if not await cfg.enabled():
                        continue
                    voice = guild.voice_client
                    channel_id = await cfg.channel_id()
                    if not channel_id:
                        continue
                    if voice is None or not voice.is_connected() or not voice.channel or voice.channel.id != channel_id:
                        await self._connect_guild(guild)
                await asyncio.sleep(20)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(20)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in list(self.bot.guilds):
            if await self.config.guild(guild).enabled():
                await self._connect_guild(guild)

    @commands.group(name="afkvoice", aliases=["afkvc"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def afkvoice(self, ctx: commands.Context):
        """Configura la connessione vocale AFK persistente."""
        await ctx.send_help(ctx.command)

    @afkvoice.command(name="set")
    async def set_channel(self, ctx: commands.Context, channel_id: int):
        """Imposta il canale vocale tramite ID."""
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return await ctx.send("Canale non trovato o non vocale.")

        me = ctx.guild.me
        if me is None:
            return await ctx.send("Impossibile controllare i permessi del bot.")

        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.connect:
            return await ctx.send("Il bot non ha i permessi **View Channel** e **Connect** in quel canale.")

        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Canale AFK impostato su **{channel.name}** (`{channel.id}`).")

    @afkvoice.command(name="enable")
    async def enable(self, ctx: commands.Context):
        """Abilita la connessione automatica e prova a entrare subito."""
        channel_id = await self.config.guild(ctx.guild).channel_id()
        if not channel_id:
            return await ctx.send(f"Prima imposta un canale con `{ctx.clean_prefix}afkvoice set <ID>`.")

        await self.config.guild(ctx.guild).enabled.set(True)
        ok, reason = await self._connect_guild(ctx.guild)
        if ok:
            await ctx.send(f"AFKVoice **attivato**: {reason}.")
        else:
            await ctx.send(f"AFKVoice attivato, ma non sono riuscito a connettermi ora: `{reason}`. Riprovero automaticamente.")

    @afkvoice.command(name="disable")
    async def disable(self, ctx: commands.Context):
        """Disabilita la riconnessione automatica e disconnette il bot."""
        await self.config.guild(ctx.guild).enabled.set(False)
        voice = ctx.guild.voice_client
        if voice is not None:
            try:
                await voice.disconnect(force=True)
            except discord.HTTPException:
                pass
        await ctx.send("AFKVoice **disattivato** e bot disconnesso dalla vocale.")

    @afkvoice.command(name="connect")
    async def connect_now(self, ctx: commands.Context):
        """Forza un tentativo di connessione immediato."""
        ok, reason = await self._connect_guild(ctx.guild)
        await ctx.send(f"{'Connesso' if ok else 'Connessione fallita'}: `{reason}`")

    @afkvoice.command(name="disconnect")
    async def disconnect_now(self, ctx: commands.Context):
        """Disconnette il bot senza disabilitare l'autoreconnect."""
        voice = ctx.guild.voice_client
        if voice is None:
            return await ctx.send("Il bot non e' connesso a una vocale.")
        try:
            await voice.disconnect(force=True)
        except discord.HTTPException as exc:
            return await ctx.send(f"Errore durante la disconnessione: `{exc}`")
        await ctx.send("Bot disconnesso. Se AFKVoice e' attivo, si riconnettera automaticamente.")

    @afkvoice.command(name="status")
    async def status(self, ctx: commands.Context):
        """Mostra configurazione e stato della connessione."""
        cfg = self.config.guild(ctx.guild)
        enabled = await cfg.enabled()
        channel_id = await cfg.channel_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        voice = ctx.guild.voice_client

        if voice and voice.is_connected() and voice.channel:
            current = f"{voice.channel.mention} (`{voice.channel.id}`)"
        else:
            current = "non connesso"

        configured = (
            f"{channel.mention} (`{channel.id}`)"
            if isinstance(channel, (discord.VoiceChannel, discord.StageChannel))
            else (f"ID `{channel_id}` non valido" if channel_id else "nessuno")
        )

        await ctx.send(
            f"AFKVoice: **{'attivo' if enabled else 'disattivato'}**\n"
            f"Canale configurato: {configured}\n"
            f"Connessione attuale: {current}\n"
            "Controllo automatico: **ogni 20 secondi** + riconnessione all'avvio del bot."
        )

    @afkvoice.command(name="clear")
    async def clear(self, ctx: commands.Context):
        """Rimuove l'ID del canale configurato e disabilita il cog nel server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await self.config.guild(ctx.guild).channel_id.set(0)
        voice = ctx.guild.voice_client
        if voice:
            try:
                await voice.disconnect(force=True)
            except discord.HTTPException:
                pass
        await ctx.send("Configurazione AFKVoice rimossa.")
