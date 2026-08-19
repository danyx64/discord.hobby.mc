import asyncio
from .leavefeed_base import LeaveFeed as BaseLeaveFeed


class LeaveFeed(BaseLeaveFeed):
    """LeaveFeed v1.1: non invia feedback a utenti kickati o bannati."""

    __version__ = "1.1.0"

    async def _was_kicked_or_banned(self, member):
        guild = member.guild
        me = guild.me
        if me is None or not me.guild_permissions.view_audit_log:
            return False

        # Discord puo consegnare on_member_remove prima che la voce Audit Log
        # sia immediatamente visibile. Facciamo pochi retry brevi prima del DM.
        for delay in (0.35, 0.75, 1.25):
            await asyncio.sleep(delay)
            now = discord.utils.utcnow()
            for action in (discord.AuditLogAction.kick, discord.AuditLogAction.ban):
                try:
                    async for entry in guild.audit_logs(limit=6, action=action):
                        target = getattr(entry, "target", None)
                        if getattr(target, "id", None) != member.id:
                            continue
                        age = (now - entry.created_at).total_seconds()
                        if 0 <= age <= 12:
                            return True
                except (discord.Forbidden, discord.HTTPException):
                    return False
        return False

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        if await self._was_kicked_or_banned(member):
            return
        await self._send_leave_dm(member, member.guild)
