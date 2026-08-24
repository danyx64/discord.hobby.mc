from .membercounter import MemberCounter


async def setup(bot):
    await bot.add_cog(MemberCounter(bot))
