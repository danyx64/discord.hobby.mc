import asyncio

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


class StreamStatus(commands.Cog):
    """Presenza Streaming viola con testi a rotazione."""

    __author__ = "danyx64"
    __version__ = "2.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self._task = None
        self._wake_event = asyncio.Event()
        self.config = Config.get_conf(self, identifier=724019583621904771, force_registration=True)
        self.config.register_global(
            enabled=False,
            url="https://www.twitch.tv/4vv0c4t0",
            statuses=["Hobby MC"],
            interval=60,
            index=0,
        )

    async def cog_load(self):
        self._task = asyncio.create_task(self._rotation_loop())

    def cog_unload(self):
        if self._task:
            self._task.cancel()

    async def _apply_current(self):
        data = await self.config.all()
        if not data["enabled"]:
            return

        statuses = [str(x).strip() for x in data.get("statuses", []) if str(x).strip()]
        if not statuses:
            statuses = ["Hobby MC"]

        index = int(data.get("index", 0)) % len(statuses)
        activity = discord.Streaming(
            name=statuses[index][:128],
            url=data["url"],
        )

        # Non forza online/idle/dnd: modifica solo l'attivita' Streaming.
        await self.bot.change_presence(activity=activity)

    async def _rotation_loop(self):
        await self.bot.wait_until_ready()

        while True:
            try:
                data = await self.config.all()
                interval = max(15, int(data.get("interval", 60)))

                if data.get("enabled"):
                    statuses = [str(x).strip() for x in data.get("statuses", []) if str(x).strip()]
                    if not statuses:
                        statuses = ["Hobby MC"]

                    index = int(data.get("index", 0)) % len(statuses)
                    activity = discord.Streaming(
                        name=statuses[index][:128],
                        url=data["url"],
                    )
                    await self.bot.change_presence(activity=activity)
                    await self.config.index.set((index + 1) % len(statuses))

                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(10)

    def _wake(self):
        self._wake_event.set()

    @commands.group(name="streamstatus", aliases=["stream"], invoke_without_command=True)
    @commands.is_owner()
    async def streamstatus(self, ctx: commands.Context):
        """Configura la presenza Streaming a rotazione."""
        await ctx.send_help(ctx.command)

    @streamstatus.command(name="enable")
    async def stream_enable(self, ctx: commands.Context):
        """Abilita lo stato Streaming viola e il ciclo."""
        await self.config.enabled.set(True)
        await self.config.index.set(0)
        await self._apply_current()
        self._wake()
        await ctx.send("🟣 Streaming e rotazione abilitati.")

    @streamstatus.command(name="disable")
    async def stream_disable(self, ctx: commands.Context):
        """Disabilita questo cog e rimuove la sua attivita'."""
        await self.config.enabled.set(False)
        self._wake()
        await self.bot.change_presence(activity=None)
        await ctx.send("Streaming disabilitato.")

    @streamstatus.command(name="url")
    async def stream_url(self, ctx: commands.Context, url: str):
        """Imposta il link Twitch usato dalla presenza Streaming."""
        if not url.lower().startswith(("https://www.twitch.tv/", "https://twitch.tv/")):
            return await ctx.send("Usa un URL Twitch valido.")
        await self.config.url.set(url)
        await self._apply_current()
        self._wake()
        await ctx.send(f"URL impostato su <{url}>.")

    @streamstatus.command(name="interval")
    async def stream_interval(self, ctx: commands.Context, seconds: int):
        """Imposta ogni quanti secondi cambia testo. Minimo 15 secondi."""
        if seconds < 15:
            return await ctx.send("L'intervallo minimo e' 15 secondi.")
        if seconds > 86400:
            return await ctx.send("L'intervallo massimo e' 86400 secondi.")
        await self.config.interval.set(seconds)
        self._wake()
        await ctx.send(f"Cambio stato ogni **{seconds} secondi**.")

    @streamstatus.command(name="add")
    async def stream_add(self, ctx: commands.Context, *, text: str):
        """Aggiunge un testo alla rotazione."""
        text = text.strip()
        if not text:
            return await ctx.send("Il testo non puo' essere vuoto.")
        if len(text) > 128:
            return await ctx.send("Massimo 128 caratteri.")

        async with self.config.statuses() as statuses:
            statuses.append(text)

        self._wake()
        await ctx.send(f"Aggiunto alla rotazione: **{text}**")

    @streamstatus.command(name="remove", aliases=["del"])
    async def stream_remove(self, ctx: commands.Context, number: int):
        """Rimuove uno stato usando il numero mostrato da [p]stream list."""
        async with self.config.statuses() as statuses:
            if number < 1 or number > len(statuses):
                return await ctx.send("Numero non valido. Usa `.stream list`.")
            removed = statuses.pop(number - 1)

        await self.config.index.set(0)
        self._wake()
        await ctx.send(f"Rimosso: **{removed}**")

    @streamstatus.command(name="clear")
    async def stream_clear(self, ctx: commands.Context):
        """Svuota la lista degli stati."""
        await self.config.statuses.set([])
        await self.config.index.set(0)
        self._wake()
        await ctx.send("Lista degli stati svuotata.")

    @streamstatus.command(name="list")
    async def stream_list(self, ctx: commands.Context):
        """Mostra i testi nella rotazione."""
        statuses = await self.config.statuses()
        if not statuses:
            return await ctx.send("Nessuno stato configurato.")
        lines = [f"`{i}.` {text}" for i, text in enumerate(statuses, 1)]
        await ctx.send("**Rotazione Streaming:**\n" + "\n".join(lines))

    @streamstatus.command(name="set")
    async def stream_set(self, ctx: commands.Context, *, text: str):
        """Sostituisce la rotazione con un solo testo."""
        text = text.strip()
        if not text or len(text) > 128:
            return await ctx.send("Inserisci un testo da 1 a 128 caratteri.")
        await self.config.statuses.set([text])
        await self.config.index.set(0)
        await self.config.enabled.set(True)
        await self._apply_current()
        self._wake()
        await ctx.send(f"🟣 Streaming impostato su **{text}**.")

    @streamstatus.command(name="next")
    async def stream_next(self, ctx: commands.Context):
        """Passa subito allo stato successivo."""
        statuses = await self.config.statuses()
        if not statuses:
            return await ctx.send("Nessuno stato configurato.")
        index = (await self.config.index()) % len(statuses)
        await self.config.index.set((index + 1) % len(statuses))
        await self._apply_current()
        self._wake()
        await ctx.send("Stato Streaming cambiato.")

    @streamstatus.command(name="status")
    async def stream_status(self, ctx: commands.Context):
        """Mostra la configurazione corrente."""
        data = await self.config.all()
        statuses = data.get("statuses", [])
        await ctx.send(
            f"Versione: **{self.__version__}**\n"
            f"Stato: **{'attivo' if data['enabled'] else 'disattivato'}**\n"
            f"URL: <{data['url']}>\n"
            f"Intervallo: **{data['interval']}s**\n"
            f"Testi in rotazione: **{len(statuses)}**"
        )
