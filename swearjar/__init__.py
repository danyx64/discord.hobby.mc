from .swearjar import SwearJar


async def setup(bot):
    await bot.add_cog(SwearJar(bot))
