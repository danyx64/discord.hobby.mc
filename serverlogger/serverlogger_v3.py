from .serverlogger_v2 import ServerLogger as BaseServerLogger


class ServerLogger(BaseServerLogger):
    """ServerLogger v1.5: ignora tutte le azioni eseguite dal bot stesso."""

    __version__ = "1.5.0"

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
