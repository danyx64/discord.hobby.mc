import re

import discord
from redbot.core import commands
from redbot.core.bot import Red


class SwearJarResetStats(commands.Cog):
    """Comandi amministrativi per azzerare le statistiche di SwearJar."""

    __author__ = "danyx64"
    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot

    @staticmethod
    def _extract_user_id(value: str):
        value = value.strip()
        mention_match = re.fullmatch(r"<@!?(\d{15,25})>", value)
        if mention_match:
            return int(mention_match.group(1))
        if value.isdigit() and 15 <= len(value) <= 25:
            return int(value)
        return None

    @commands.command(name="swearreset", aliases=["swearjarreset", "resetbestemmie"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_reset_member(self, ctx: commands.Context, *, target: str):
        """Azzera le statistiche SwearJar di un utente nel server corrente.

        Funziona anche se l'utente ha gia' lasciato il server.

        Esempi:
        [p]swearreset @utente
        [p]swearreset 123456789012345678
        """
        swearjar = self.bot.get_cog("SwearJar")
        if swearjar is None:
            return await ctx.send("Il cog SwearJar non risulta caricato.")

        user_id = self._extract_user_id(target)
        member = None

        if user_id is not None:
            member = ctx.guild.get_member(user_id)
        else:
            converter = commands.MemberConverter()
            try:
                member = await converter.convert(ctx, target)
                user_id = member.id
            except commands.BadArgument:
                return await ctx.send(
                    "Utente non trovato. Se ha gia' lasciato il server, usa il suo **ID Discord**.\n"
                    "Esempio: `[p]swearreset 123456789012345678`"
                )

        member_group = swearjar.config.member_from_ids(ctx.guild.id, user_id)
        previous_count = await member_group.count()
        await member_group.count.set(0)

        if member is not None:
            label = member.mention
        else:
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                label = f"{user} (`{user_id}`)"
            except (discord.NotFound, discord.HTTPException):
                label = f"utente `{user_id}`"

        await ctx.send(
            f"Statistiche SwearJar di {label} azzerate. "
            f"Conteggio precedente: **{previous_count}** → **0**."
        )
