from .autoreactions import AutoReactions
from .fakenitro import patch_autoreactions


patch_autoreactions(AutoReactions)


async def setup(bot):
    await bot.add_cog(AutoReactions(bot))
