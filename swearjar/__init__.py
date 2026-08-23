import re

import discord
from redbot.core import commands

from .swearjar import SwearJar


async def setup(bot):
    cog = SwearJar(bot)
    await bot.add_cog(cog)

    parent = bot.get_command("swearjar")
    if parent is None:
        return

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_reset(ctx: commands.Context, *, target: str):
        """Azzera le statistiche SwearJar di un utente nel server corrente.

        Accetta mention, membro presente oppure ID Discord di un utente che ha
        gia' lasciato il server.
        """
        value = target.strip()
        mention_match = re.fullmatch(r"<@!?(\d{15,25})>", value)

        member = None
        user_id = None

        if mention_match:
            user_id = int(mention_match.group(1))
            member = ctx.guild.get_member(user_id)
        elif value.isdigit() and 15 <= len(value) <= 25:
            user_id = int(value)
            member = ctx.guild.get_member(user_id)
        else:
            converter = commands.MemberConverter()
            try:
                member = await converter.convert(ctx, value)
                user_id = member.id
            except commands.BadArgument:
                return await ctx.send(
                    "Utente non trovato. Se ha gia' lasciato il server, usa il suo **ID Discord**.\n"
                    "Esempio: `[p]swear reset 123456789012345678`"
                )

        member_group = cog.config.member_from_ids(ctx.guild.id, user_id)
        previous_count = await member_group.count()
        await member_group.count.set(0)

        if member is not None:
            label = member.mention
        else:
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                label = f"{user} (`{user_id}`)"
            except (discord.NotFound, discord.HTTPException):
                label = f"utente `{user_id}`"

        await ctx.send(
            f"Statistiche SwearJar di {label} azzerate. "
            f"Conteggio precedente: **{previous_count}** -> **0**."
        )

    reset_command = commands.command(
        name="reset",
        aliases=["resetstats", "resetbestemmie"],
    )(swear_reset)
    parent.add_command(reset_command)
