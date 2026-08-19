from .leavefeed_v3 import LeaveFeed


async def setup(bot):
    await bot.add_cog(LeaveFeed(bot))
