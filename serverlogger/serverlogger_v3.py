import asyncio

import discord
from redbot.core import commands

from .serverlogger_v2 import ServerLogger as BaseServerLogger


class ServerLogger(BaseServerLogger):
    """ServerLogger v1.6: ignora le azioni del bot e pulisce DB + canale log."""

    __version__ = "1.6.0"

    def __init__(self, bot):
        super().__init__(bot)
        self._suppress_guild_events = set()

    async def _emit(
        self,
        guild,
        action,
        *,
        staffer=None,
        user=None,
        channel=None,
        details=None,
        when=None,
    ):
        if guild is not None and guild.id in self._suppress_guild_events:
            return

        bot_user = self.bot.user
        bot_id = bot_user.id if bot_user is not None else None

        staffer_id = self._object_id(staffer)
        user_id = self._object_id(user)

        # Non registrare azioni compiute dal bot stesso.
        if bot_id is not None and staffer_id == bot_id:
            return

        # Eventi autonomi del bot (senza uno staffer distinto) vengono ignorati.
        # Se invece uno staffer umano modifica il bot, l'azione resta loggata.
        if bot_id is not None and staffer_id is None and user_id == bot_id:
            return

        await super()._emit(
            guild,
            action,
            staffer=staffer,
            user=user,
            channel=channel,
            details=details,
            when=when,
        )

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Dopo `.log clear CONFERMO`, svuota anche il canale log configurato."""
        if ctx.guild is None or ctx.command is None:
            return
        if ctx.command.qualified_name != "log clear":
            return

        parts = ctx.message.content.strip().split()
        if not parts or parts[-1].upper() != "CONFERMO":
            return

        channel_id = await self.config.guild(ctx.guild).log_channel_id()
        if not channel_id:
            return

        channel = ctx.guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        me = ctx.guild.me
        if me is None:
            return
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.read_message_history and perms.manage_messages):
            await ctx.send(
                "Database pulito, ma non posso pulire il canale log: mi servono "
                "Visualizza canale, Leggi cronologia messaggi e Gestisci messaggi."
            )
            return

        self._suppress_guild_events.add(ctx.guild.id)
        try:
            await channel.purge(limit=None, check=lambda _message: True, bulk=True)
            # Lascia il filtro attivo per un istante: gli eventi raw delle cancellazioni
            # possono arrivare subito dopo il completamento del purge.
            await asyncio.sleep(1.0)
        except discord.Forbidden:
            await ctx.send("Database pulito, ma Discord mi ha negato la pulizia del canale log.")
        except discord.HTTPException:
            await ctx.send("Database pulito, ma si e verificato un errore Discord durante la pulizia del canale log.")
        finally:
            self._suppress_guild_events.discard(ctx.guild.id)
