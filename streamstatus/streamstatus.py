import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


class StreamStatus(commands.Cog):
    """Imposta una presenza Streaming viola personalizzabile per il bot."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=724019583621904771, force_registration=True)
        self.config.register_global(
            enabled=False,
            name="Hobby MC",
            url="https://www.twitch.tv/twitch",
        )

    async def cog_load(self):
        await self._apply_presence()

    async def _apply_presence(self):
        data = await self.config.all()
        if not data["enabled"]:
            return
        activity = discord.Streaming(name=data["name"], url=data["url"])
        await self.bot.change_presence(status=discord.Status.online, activity=activity)

    @commands.group(name="streamstatus", aliases=["stream"], invoke_without_command=True)
    @commands.is_owner()
    async def streamstatus(self, ctx: commands.Context):
        """Configura lo stato Streaming del bot."""
        await ctx.send_help(ctx.command)

    @streamstatus.command(name="set")
    async def stream_set(self, ctx: commands.Context, url: str, *, name: str):
        """Imposta URL e testo. Esempio: [p]stream set https://twitch.tv/twitch Hobby MC"""
        if not url.lower().startswith(("https://www.twitch.tv/", "https://twitch.tv/")):
            return await ctx.send("Usa un URL Twitch valido, ad esempio `https://twitch.tv/twitch`.")
        await self.config.url.set(url)
        await self.config.name.set(name[:128])
        await self.config.enabled.set(True)
        await self._apply_presence()
        await ctx.send(f"🟣 Streaming impostato su **{name[:128]}**.")

    @streamstatus.command(name="name")
    async def stream_name(self, ctx: commands.Context, *, name: str):
        """Cambia solo il testo mostrato nello stato Streaming."""
        await self.config.name.set(name[:128])
        await self._apply_presence()
        await ctx.send("Testo streaming aggiornato.")

    @streamstatus.command(name="url")
    async def stream_url(self, ctx: commands.Context, url: str):
        """Cambia solo il link Twitch usato dalla presenza."""
        if not url.lower().startswith(("https://www.twitch.tv/", "https://twitch.tv/")):
            return await ctx.send("Usa un URL Twitch valido.")
        await self.config.url.set(url)
        await self._apply_presence()
        await ctx.send("URL streaming aggiornato.")

    @streamstatus.command(name="enable")
    async def stream_enable(self, ctx: commands.Context):
        """Abilita la presenza Streaming configurata."""
        await self.config.enabled.set(True)
        await self._apply_presence()
        await ctx.send("🟣 Stato Streaming abilitato.")

    @streamstatus.command(name="disable")
    async def stream_disable(self, ctx: commands.Context):
        """Disabilita la presenza Streaming e pulisce l'attivita'."""
        await self.config.enabled.set(False)
        await self.bot.change_presence(status=discord.Status.online, activity=None)
        await ctx.send("Stato Streaming disabilitato.")

    @streamstatus.command(name="status")
    async def stream_status(self, ctx: commands.Context):
        """Mostra la configurazione corrente."""
        data = await self.config.all()
        await ctx.send(
            f"Versione: **{self.__version__}**\n"
            f"Stato: **{'attivo' if data['enabled'] else 'disattivato'}**\n"
            f"Testo: **{data['name']}**\n"
            f"URL: <{data['url']}>"
        )
