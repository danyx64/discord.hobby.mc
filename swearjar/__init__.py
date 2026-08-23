from .swearjar import SwearJar
from .resetstats import SwearJarResetStats


async def setup(bot):
    await bot.add_cog(SwearJar(bot))
    await bot.add_cog(SwearJarResetStats(bot))
